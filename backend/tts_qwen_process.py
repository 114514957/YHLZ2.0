"""Process transport for the isolated Qwen TTS provider.

``QwenTTSWorker`` owns a model inside one Python process.  This module places
that worker in a spawned child process so the target chain can prove a separate
CUDA/model lifetime instead of treating a thread as process isolation.  The
parent only exposes the existing ``TTSProviderPort`` shape; it never receives a
model object and it never opens an audio device.

The IPC protocol stays deliberately small:

* commands: open, push, commit, cancel, shutdown;
* events: READY, PCM_CHUNK, DONE, ERROR, STOPPED;
* observations: health, metrics, child exit and bounded stop confirmation.

Raw PCM is transferred only over the local child-process connection and is
never written to memory storage, a sound cache, or the application database.
"""

from __future__ import annotations

import multiprocessing as mp
import os
import queue
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Iterator, Mapping, Optional

from backend.tts_provider_port import (
    TTSEventKind,
    TTSProviderCapabilities,
    TTSProviderEvent,
    TTSProviderPortError,
    TTSRequest,
)
from backend.tts_provider_worker import PersistentTTSProvider
from backend.tts_qwen_provider import (
    QWEN_PROVIDER_ID,
    QwenTTSAdapterError,
    QwenTTSConfig,
    QwenTTSWorker,
    qwen_capabilities,
)


_STREAM_END = object()
_DEFAULT_STARTUP_TIMEOUT_S = 90.0


@dataclass(slots=True)
class _PendingCall:
    event: threading.Event
    response: Optional[dict] = None


def _error_parts(exc: BaseException, fallback: str) -> tuple[str, str]:
    if isinstance(exc, TTSProviderPortError):
        return exc.code, exc.detail
    return fallback, str(exc)[:400]


def _child_send(connection: Any, lock: threading.Lock, message: Mapping[str, Any]) -> bool:
    try:
        with lock:
            connection.send(dict(message))
        return True
    except (BrokenPipeError, EOFError, OSError):
        return False


def _child_response(
    connection: Any,
    lock: threading.Lock,
    request_id: str,
    *,
    result: Any = None,
    error: Optional[BaseException] = None,
) -> None:
    if error is None:
        _child_send(
            connection,
            lock,
            {"type": "response", "id": request_id, "ok": True, "result": result},
        )
        return
    code, detail = _error_parts(error, "VOICE-TTS-QWEN-PROCESS-COMMAND-FAILED")
    _child_send(
        connection,
        lock,
        {
            "type": "response",
            "id": request_id,
            "ok": False,
            "code": code,
            "detail": detail,
        },
    )


def _child_error_event(request: TTSRequest, code: str, detail: str) -> TTSProviderEvent:
    return TTSProviderEvent(
        kind=TTSEventKind.ERROR.value,
        speech_id=request.speech_id,
        provider_epoch=request.provider_epoch,
        code=code,
        detail=detail[:400],
    )


def _qwen_process_main(config: QwenTTSConfig, connection: Any, worker_id: str) -> None:
    """Child-process command loop.  Kept module-level for Windows spawn."""
    os.environ.update({"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"})
    send_lock = threading.Lock()
    worker = QwenTTSWorker(config, worker_isolated=True, worker_id=worker_id)
    active_session: Any = None
    forwarder: Optional[threading.Thread] = None

    def forward_events(session: Any) -> None:
        try:
            for event in session.audio_events():
                if not _child_send(
                    connection,
                    send_lock,
                    {"type": "event", "speech_id": session.request.speech_id, "event": event},
                ):
                    session.cancel("parent_connection_lost")
                    return
        except Exception as exc:
            code, detail = _error_parts(exc, "VOICE-TTS-QWEN-PROCESS-STREAM-FAILED")
            _child_send(
                connection,
                send_lock,
                {
                    "type": "event",
                    "speech_id": session.request.speech_id,
                    "event": _child_error_event(session.request, code, detail),
                },
            )
        finally:
            _child_send(
                connection,
                send_lock,
                {
                    "type": "stream_end",
                    "speech_id": session.request.speech_id,
                    "metrics": dict(session.metrics()),
                },
            )

    try:
        worker.start()
        if not _child_send(
            connection,
            send_lock,
            {"type": "ready", "ok": True, "health": dict(worker.health())},
        ):
            return
    except Exception as exc:
        code, detail = _error_parts(exc, "VOICE-TTS-QWEN-PROCESS-START-FAILED")
        _child_send(
            connection,
            send_lock,
            {"type": "ready", "ok": False, "code": code, "detail": detail},
        )
        try:
            worker.stop("startup_failed")
        except Exception:
            pass
        return

    try:
        while True:
            try:
                if not connection.poll(0.1):
                    continue
                command = connection.recv()
            except (EOFError, OSError):
                break
            if not isinstance(command, Mapping) or command.get("type") != "command":
                continue
            request_id = str(command.get("id", ""))
            operation = str(command.get("op", ""))
            payload = command.get("payload", {})
            if not isinstance(payload, Mapping):
                payload = {}
            try:
                if operation == "open":
                    request = payload.get("request")
                    if not isinstance(request, TTSRequest):
                        raise QwenTTSAdapterError("VOICE-TTS-QWEN-PROCESS-REQUEST-INVALID")
                    active_session = worker.open(request)
                    forwarder = threading.Thread(
                        target=forward_events,
                        args=(active_session,),
                        name="qwen-tts-ipc-forwarder",
                        daemon=True,
                    )
                    forwarder.start()
                    _child_response(connection, send_lock, request_id, result=True)
                    continue
                if operation == "push":
                    _require_session(active_session, payload)
                    _child_response(
                        connection,
                        send_lock,
                        request_id,
                        result=active_session.push_text(str(payload.get("delta", ""))),
                    )
                    continue
                if operation == "commit":
                    _require_session(active_session, payload)
                    _child_response(connection, send_lock, request_id, result=active_session.commit_text())
                    continue
                if operation == "cancel":
                    _require_session(active_session, payload)
                    _child_response(
                        connection,
                        send_lock,
                        request_id,
                        result=active_session.cancel(str(payload.get("reason", "cancelled"))),
                    )
                    continue
                if operation == "health":
                    _child_response(connection, send_lock, request_id, result=dict(worker.health()))
                    continue
                if operation == "metrics":
                    _child_response(connection, send_lock, request_id, result=dict(worker.metrics()))
                    continue
                if operation == "shutdown":
                    if active_session is not None and not active_session.is_finished:
                        active_session.cancel(str(payload.get("reason", "shutdown")))
                        active_session.wait_stopped(config.stop_timeout_s)
                    if forwarder is not None:
                        forwarder.join(config.stop_timeout_s)
                    worker.stop(str(payload.get("reason", "shutdown")))
                    _child_response(connection, send_lock, request_id, result=True)
                    break
                raise QwenTTSAdapterError(
                    "VOICE-TTS-QWEN-PROCESS-COMMAND-INVALID", operation[:160]
                )
            except Exception as exc:
                _child_response(connection, send_lock, request_id, error=exc)
    finally:
        try:
            if active_session is not None and not active_session.is_finished:
                active_session.cancel("process_exiting")
                active_session.wait_stopped(config.stop_timeout_s)
            if forwarder is not None:
                forwarder.join(config.stop_timeout_s)
            worker.stop("process_exiting")
        except Exception:
            pass
        try:
            connection.close()
        except Exception:
            pass


def _require_session(session: Any, payload: Mapping[str, Any]) -> None:
    speech_id = str(payload.get("speech_id", ""))
    if session is None or session.request.speech_id != speech_id:
        raise QwenTTSAdapterError("VOICE-TTS-QWEN-PROCESS-SESSION-STALE")


class QwenProcessWorker:
    """Parent-side proxy to one spawned Qwen model worker process."""

    def __init__(
        self,
        config: QwenTTSConfig,
        *,
        worker_id: Optional[str] = None,
        startup_timeout_s: float = _DEFAULT_STARTUP_TIMEOUT_S,
    ) -> None:
        if not isinstance(config, QwenTTSConfig):
            raise TypeError("config must be QwenTTSConfig")
        if float(startup_timeout_s) <= 0:
            raise ValueError("startup_timeout_s must be positive")
        self.config = config
        self.worker_id = str(worker_id or ("qwen-process-" + uuid.uuid4().hex[:12]))
        self.startup_timeout_s = float(startup_timeout_s)
        self._ctx = mp.get_context("spawn")
        self._lock = threading.RLock()
        self._send_lock = threading.Lock()
        self._process: Any = None
        self._connection: Any = None
        self._receiver: Optional[threading.Thread] = None
        self._ready_event = threading.Event()
        self._ready_error: Optional[QwenTTSAdapterError] = None
        self._pending_calls: Dict[str, _PendingCall] = {}
        self._sessions: Dict[str, QwenProcessSession] = {}
        self._pending_events: Dict[str, list[TTSProviderEvent]] = {}
        self._last_error_code: Optional[str] = None
        self._last_error_detail = ""
        self._last_metrics: Dict[str, Any] = {}
        self._started_at: Optional[float] = None
        self._stopping = False

    def describe_capabilities(self) -> TTSProviderCapabilities:
        return qwen_capabilities(worker_isolated=True)

    def start(self) -> None:
        with self._lock:
            if self.is_alive():
                return
            self._close_connection_locked()
            self._ready_event.clear()
            self._ready_error = None
            self._pending_calls.clear()
            self._sessions.clear()
            self._pending_events.clear()
            self._stopping = False
            parent, child = self._ctx.Pipe(duplex=True)
            process = self._ctx.Process(
                target=_qwen_process_main,
                args=(self.config, child, self.worker_id),
                name=self.worker_id,
                daemon=True,
            )
            process.start()
            child.close()
            self._process = process
            self._connection = parent
            self._receiver = threading.Thread(
                target=self._receive_loop,
                name=self.worker_id + "-receiver",
                daemon=True,
            )
            self._receiver.start()
        if not self._ready_event.wait(self.startup_timeout_s):
            self._record_error(
                "VOICE-TTS-QWEN-PROCESS-START-TIMEOUT", "child did not report ready"
            )
            self.terminate()
            raise QwenTTSAdapterError(
                "VOICE-TTS-QWEN-PROCESS-START-TIMEOUT", "child did not report ready"
            )
        if self._ready_error is not None:
            error = self._ready_error
            self.terminate()
            raise error
        with self._lock:
            if not self.is_alive():
                error = QwenTTSAdapterError(
                    "VOICE-TTS-QWEN-PROCESS-START-FAILED", "child exited after ready"
                )
                self._record_error(error.code, error.detail)
                raise error
            self._started_at = time.time()

    def open(self, request: TTSRequest) -> "QwenProcessSession":
        if not isinstance(request, TTSRequest):
            raise TypeError("request must be TTSRequest")
        self._command("open", {"request": request})
        session = QwenProcessSession(self, request, self.config.queue_maxsize)
        with self._lock:
            if request.speech_id in self._sessions:
                raise QwenTTSAdapterError("VOICE-TTS-QWEN-PROCESS-SESSION-BUSY")
            self._sessions[request.speech_id] = session
            pending = self._pending_events.pop(request.speech_id, ())
        for event in pending:
            session._offer_event(event)
        return session

    def stop(self, reason: str = "worker_stop") -> None:
        with self._lock:
            process = self._process
            alive = process is not None and process.is_alive()
            self._stopping = True
        if not alive:
            self._mark_process_exit("VOICE-TTS-QWEN-PROCESS-EXITED", "worker is not alive")
            return
        try:
            self._command(
                "shutdown",
                {"reason": str(reason or "worker_stop")[:160]},
                timeout_s=self.config.stop_timeout_s,
            )
        except QwenTTSAdapterError:
            # Let the lifecycle facade decide whether a forced terminate is
            # acceptable; a normal stop must not silently hide this failure.
            raise
        process.join(self.config.stop_timeout_s)
        if process.is_alive():
            raise QwenTTSAdapterError(
                "VOICE-TTS-QWEN-PROCESS-STOP-TIMEOUT", "child process remains alive"
            )
        self._mark_process_exit("VOICE-TTS-QWEN-PROCESS-STOPPED", "shutdown complete")

    close = stop

    def terminate(self) -> None:
        with self._lock:
            process = self._process
        if process is not None and process.is_alive():
            process.terminate()
            process.join(self.config.stop_timeout_s)
        self._mark_process_exit("VOICE-TTS-QWEN-PROCESS-TERMINATED", "forced termination")

    def wait_stopped(self, timeout_s: float) -> bool:
        with self._lock:
            process = self._process
        if process is None:
            return True
        process.join(max(float(timeout_s), 0.0))
        if process.is_alive():
            return False
        self._mark_process_exit("VOICE-TTS-QWEN-PROCESS-STOPPED", "process exited")
        return True

    def is_alive(self) -> bool:
        with self._lock:
            return bool(self._process is not None and self._process.is_alive())

    def health(self) -> Mapping[str, Any]:
        with self._lock:
            process = self._process
            alive = bool(process is not None and process.is_alive())
            state = "stopping" if self._stopping and alive else ("ready" if alive else "stopped")
            if self._last_error_code and not alive:
                state = "failed" if "STOPPED" not in self._last_error_code else "stopped"
            result: Dict[str, Any] = {
                "provider_id": QWEN_PROVIDER_ID,
                "worker_id": self.worker_id,
                "state": state,
                "alive": alive,
                "pid": getattr(process, "pid", None),
                "worker_isolated": True,
                "started_at": self._started_at,
            }
            if self._last_error_code:
                result["last_error_code"] = self._last_error_code
                result["last_error_detail"] = self._last_error_detail
            return result

    def metrics(self) -> Mapping[str, Any]:
        with self._lock:
            process = self._process
            return {
                "provider_id": QWEN_PROVIDER_ID,
                "worker_id": self.worker_id,
                "pid": getattr(process, "pid", None),
                "alive": bool(process is not None and process.is_alive()),
                "worker_isolated": True,
                "sessions": list(self._sessions),
                "last": dict(self._last_metrics),
            }

    def _command(
        self,
        operation: str,
        payload: Mapping[str, Any],
        *,
        timeout_s: Optional[float] = None,
    ) -> Any:
        with self._lock:
            if self._process is None or not self._process.is_alive() or self._connection is None:
                raise QwenTTSAdapterError("VOICE-TTS-QWEN-PROCESS-NOT-READY")
            request_id = uuid.uuid4().hex
            pending = _PendingCall(threading.Event())
            self._pending_calls[request_id] = pending
        try:
            self._send(
                {
                    "type": "command",
                    "id": request_id,
                    "op": operation,
                    "payload": dict(payload),
                }
            )
            timeout = self.config.stop_timeout_s if timeout_s is None else max(float(timeout_s), 0.0)
            if not pending.event.wait(timeout):
                raise QwenTTSAdapterError(
                    "VOICE-TTS-QWEN-PROCESS-COMMAND-TIMEOUT", operation[:160]
                )
            response = pending.response or {}
            if not response.get("ok"):
                raise QwenTTSAdapterError(
                    str(response.get("code") or "VOICE-TTS-QWEN-PROCESS-COMMAND-FAILED"),
                    str(response.get("detail") or operation)[:400],
                )
            return response.get("result")
        finally:
            with self._lock:
                self._pending_calls.pop(request_id, None)

    def _send(self, message: Mapping[str, Any]) -> None:
        with self._send_lock:
            with self._lock:
                connection = self._connection
            if connection is None:
                raise QwenTTSAdapterError("VOICE-TTS-QWEN-PROCESS-NOT-READY")
            try:
                connection.send(dict(message))
            except (BrokenPipeError, EOFError, OSError) as exc:
                self._mark_process_exit("VOICE-TTS-QWEN-PROCESS-IPC-FAILED", type(exc).__name__)
                raise QwenTTSAdapterError(
                    "VOICE-TTS-QWEN-PROCESS-IPC-FAILED", type(exc).__name__
                ) from exc

    def _receive_loop(self) -> None:
        while True:
            with self._lock:
                connection = self._connection
                process = self._process
            if connection is None:
                return
            try:
                if not connection.poll(0.1):
                    if process is not None and not process.is_alive():
                        self._mark_process_exit(
                            "VOICE-TTS-QWEN-PROCESS-EXITED", "child process exited"
                        )
                        return
                    continue
                message = connection.recv()
            except (EOFError, OSError):
                self._mark_process_exit("VOICE-TTS-QWEN-PROCESS-EXITED", "ipc closed")
                return
            self._handle_message(message)

    def _handle_message(self, message: Any) -> None:
        if not isinstance(message, Mapping):
            return
        message_type = str(message.get("type", ""))
        if message_type == "ready":
            if not message.get("ok"):
                self._ready_error = QwenTTSAdapterError(
                    str(message.get("code") or "VOICE-TTS-QWEN-PROCESS-START-FAILED"),
                    str(message.get("detail") or "child startup failed")[:400],
                )
            self._ready_event.set()
            return
        if message_type == "response":
            request_id = str(message.get("id", ""))
            with self._lock:
                pending = self._pending_calls.get(request_id)
            if pending is not None:
                pending.response = dict(message)
                pending.event.set()
            return
        if message_type == "event":
            event = message.get("event")
            speech_id = str(message.get("speech_id", ""))
            if not isinstance(event, TTSProviderEvent) or not speech_id:
                return
            with self._lock:
                session = self._sessions.get(speech_id)
                if session is None:
                    self._pending_events.setdefault(speech_id, []).append(event)
                    return
            session._offer_event(event)
            return
        if message_type == "stream_end":
            speech_id = str(message.get("speech_id", ""))
            metrics = message.get("metrics", {})
            with self._lock:
                session = self._sessions.get(speech_id)
                if isinstance(metrics, Mapping):
                    self._last_metrics = dict(metrics)
            if session is not None:
                session._finish_stream(metrics if isinstance(metrics, Mapping) else {})
            return

    def _session_drained(self, session: "QwenProcessSession") -> None:
        with self._lock:
            current = self._sessions.get(session.request.speech_id)
            if current is session:
                self._sessions.pop(session.request.speech_id, None)

    def _record_error(self, code: str, detail: str) -> None:
        with self._lock:
            self._last_error_code = str(code)[:160]
            self._last_error_detail = str(detail)[:400]

    def _mark_process_exit(self, code: str, detail: str) -> None:
        with self._lock:
            if self._last_error_code is None or "STOPPED" not in code:
                self._last_error_code = str(code)[:160]
                self._last_error_detail = str(detail)[:400]
            sessions = tuple(self._sessions.values())
            self._sessions.clear()
            pending = tuple(self._pending_calls.values())
            self._pending_calls.clear()
            self._stopping = False
        for call in pending:
            if call.response is None:
                call.response = {
                    "ok": False,
                    "code": code,
                    "detail": detail,
                }
                call.event.set()
        for session in sessions:
            session._process_exited(code, detail)

    def _close_connection_locked(self) -> None:
        connection = self._connection
        self._connection = None
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass


class QwenProcessSession:
    """Parent-side request proxy whose event queue is fed by the child."""

    def __init__(self, owner: QwenProcessWorker, request: TTSRequest, queue_maxsize: int) -> None:
        self.owner = owner
        self.request = request
        self._queue: queue.Queue[Any] = queue.Queue(maxsize=max(1, int(queue_maxsize)))
        self._finished_event = threading.Event()
        self._drained_event = threading.Event()
        self._lock = threading.RLock()
        self._committed = False
        self._cancelled = False
        self._error_code: Optional[str] = None
        self._metrics: Dict[str, Any] = {}
        self._terminal_enqueued = False

    @property
    def is_finished(self) -> bool:
        return self._finished_event.is_set()

    @property
    def is_drained(self) -> bool:
        return self._finished_event.is_set() and self._drained_event.is_set()

    def push_text(self, delta: str) -> Any:
        self._require_active()
        return self.owner._command(
            "push", {"speech_id": self.request.speech_id, "delta": str(delta or "")}
        )

    def commit_text(self) -> Any:
        self._require_active()
        result = self.owner._command("commit", {"speech_id": self.request.speech_id})
        with self._lock:
            self._committed = True
        return result

    def cancel(self, reason: str = "cancelled") -> bool:
        with self._lock:
            self._cancelled = True
        if self.is_finished:
            return True
        try:
            return bool(
                self.owner._command(
                    "cancel",
                    {
                        "speech_id": self.request.speech_id,
                        "reason": str(reason or "cancelled")[:160],
                    },
                )
            )
        except QwenTTSAdapterError:
            if self.is_finished:
                return True
            raise

    def audio_events(self) -> Iterator[TTSProviderEvent]:
        while True:
            item = self._queue.get()
            if item is _STREAM_END:
                self._drained_event.set()
                self.owner._session_drained(self)
                return
            yield item

    def wait_stopped(self, timeout_s: float) -> bool:
        return self._finished_event.wait(max(float(timeout_s), 0.0))

    def health(self) -> Mapping[str, Any]:
        with self._lock:
            if self._error_code:
                state = "failed"
            elif self._cancelled and not self.is_finished:
                state = "stopping"
            elif self._committed and not self.is_finished:
                state = "streaming"
            elif self.is_finished:
                state = "stopped"
            else:
                state = "ready"
            return {
                "provider_id": QWEN_PROVIDER_ID,
                "speech_id": self.request.speech_id,
                "provider_epoch": self.request.provider_epoch,
                "state": state,
                "queue_depth": self._queue.qsize(),
            }

    def metrics(self) -> Mapping[str, Any]:
        with self._lock:
            result = dict(self._metrics)
            result.update(
                {
                    "provider_id": QWEN_PROVIDER_ID,
                    "speech_id": self.request.speech_id,
                    "provider_epoch": self.request.provider_epoch,
                    "committed": self._committed,
                    "cancelled": self._cancelled,
                    "queue_depth": self._queue.qsize(),
                    "error_code": self._error_code,
                }
            )
            return result

    def _require_active(self) -> None:
        if self.is_finished:
            raise QwenTTSAdapterError("VOICE-TTS-QWEN-PROCESS-SESSION-STOPPED")

    def _offer_event(self, event: TTSProviderEvent) -> None:
        with self._lock:
            if self._terminal_enqueued:
                return
        try:
            self._queue.put_nowait(event)
        except queue.Full:
            self._fail_local(
                "VOICE-TTS-QWEN-PROCESS-QUEUE-OVERFLOW",
                "parent event queue is full",
            )

    def _finish_stream(self, metrics: Mapping[str, Any]) -> None:
        with self._lock:
            self._metrics = dict(metrics)
            for key in ("error_code", "error_detail"):
                if key in self._metrics and self._metrics[key] is not None:
                    self._error_code = str(self._metrics[key])[:160]
            self._finished_event.set()
        self._enqueue_terminal()

    def _process_exited(self, code: str, detail: str) -> None:
        if not self.is_finished:
            self._fail_local(code, detail)
        else:
            self._enqueue_terminal()

    def _fail_local(self, code: str, detail: str) -> None:
        with self._lock:
            if self._error_code is not None:
                return
            self._error_code = str(code)[:160]
            self._finished_event.set()
        self._force_put(
            TTSProviderEvent(
                kind=TTSEventKind.ERROR.value,
                speech_id=self.request.speech_id,
                provider_epoch=self.request.provider_epoch,
                code=self._error_code,
                detail=str(detail)[:400],
            )
        )
        self._force_put(
            TTSProviderEvent(
                kind=TTSEventKind.STOPPED.value,
                speech_id=self.request.speech_id,
                provider_epoch=self.request.provider_epoch,
                payload={"reason": "process_exit"},
            )
        )
        self._enqueue_terminal()

    def _enqueue_terminal(self) -> None:
        with self._lock:
            if self._terminal_enqueued:
                return
            self._terminal_enqueued = True
        self._force_put(_STREAM_END)

    def _force_put(self, value: Any) -> None:
        while True:
            try:
                self._queue.put_nowait(value)
                return
            except queue.Full:
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    continue


def create_qwen_process_provider(
    config: QwenTTSConfig,
    *,
    worker_id: Optional[str] = None,
    startup_timeout_s: float = _DEFAULT_STARTUP_TIMEOUT_S,
) -> PersistentTTSProvider:
    """Build the process-isolated Qwen provider without touching app entrypoints."""

    def factory() -> QwenProcessWorker:
        return QwenProcessWorker(
            config,
            worker_id=worker_id,
            startup_timeout_s=startup_timeout_s,
        )

    return PersistentTTSProvider(
        factory,
        capabilities=qwen_capabilities(worker_isolated=True),
        provider_id=QWEN_PROVIDER_ID,
        worker_isolated=True,
        worker_persistent=True,
        stop_timeout_s=config.stop_timeout_s,
        worker_id=worker_id,
    )


__all__ = [
    "QwenProcessSession",
    "QwenProcessWorker",
    "create_qwen_process_provider",
]
