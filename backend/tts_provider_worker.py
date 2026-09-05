"""Lifecycle boundary for persistent, recyclable TTS workers.

The target chain owns turn semantics; this module owns the smaller resource
boundary around one selected TTS provider.  A worker factory may return a
thread or process backed provider proxy.  The boundary deliberately does not
know how a model is loaded or how audio is played.  It only guarantees:

* one provider worker is reused for a runtime epoch;
* a worker can be stopped and rebuilt only after a strict idle check;
* sessions from an old worker generation cannot leak events into a new one;
* health, lifecycle errors, and resource counters stay provider-neutral.

Real model/process adapters are injected later.  Keeping the factory and the
transport explicit lets the contract be tested without installing a model,
opening a sound device, or touching ``memory``.
"""

from __future__ import annotations

import asyncio
import inspect
import threading
import time
import uuid
from dataclasses import dataclass, replace
from enum import Enum
from typing import Any, AsyncIterator, Dict, Mapping, Optional, Protocol, Set, Tuple

from backend.tts_provider_port import (
    TTSEventKind,
    TTSProviderCapabilities,
    TTSProviderEvent,
    TTSProviderPortError,
    TTSRequest,
    coerce_capabilities,
    coerce_provider_event,
    is_tts_provider_port,
    is_tts_provider_session,
)


class WorkerLifecycleState(str, Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    READY = "ready"
    BUSY = "busy"
    STOPPING = "stopping"
    FAILED = "failed"


class WorkerLifecycleError(TTSProviderPortError):
    """A fail-closed lifecycle error with a stable operational code."""


class WorkerProviderFactory(Protocol):
    """Factory used to create one provider worker instance."""

    def __call__(self) -> Any: ...


_SENSITIVE_KEYS = frozenset(
    {
        "audio",
        "audio_ref",
        "content",
        "input",
        "raw_audio",
        "text",
        "transcript",
    }
)


def _safe_value(value: Any, key: str = "") -> Any:
    """Keep metrics useful without retaining source text or audio."""
    if key.lower() in _SENSITIVE_KEYS:
        return "[redacted]"
    if isinstance(value, Mapping):
        return {str(k): _safe_value(v, str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe_value(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)[:160]


def _error_code(error: BaseException, fallback: str) -> str:
    if isinstance(error, TTSProviderPortError):
        return error.code
    return fallback


def _call_lifecycle(method: Any, *args: Any) -> Any:
    """Call a synchronous lifecycle method and reject hidden async work."""
    try:
        value = method(*args)
    except TypeError:
        # A number of process wrappers expose ``stop()`` without a reason.
        if args:
            value = method()
        else:
            raise
    if inspect.isawaitable(value):
        close = getattr(value, "close", None)
        if callable(close):
            close()
        raise WorkerLifecycleError(
            "VOICE-TTS-WORKER-ASYNC-LIFECYCLE",
            "worker lifecycle methods must be synchronous at this boundary",
        )
    return value


def _read_alive(worker: Any) -> Optional[bool]:
    """Read an optional process/thread liveness signal without side effects."""
    for name in ("is_alive", "alive"):
        value = getattr(worker, name, None)
        if value is None:
            continue
        try:
            value = value() if callable(value) else value
        except Exception:
            return False
        return bool(value)
    return None


async def _invoke_async(method: Any, *args: Any) -> Any:
    """Invoke sync provider methods off the event loop, preserving awaitables."""
    if inspect.iscoroutinefunction(method):
        return await method(*args)
    if inspect.isasyncgenfunction(method):
        return method(*args)
    value = await asyncio.to_thread(method, *args)
    return await value if inspect.isawaitable(value) else value


@dataclass(frozen=True, slots=True)
class WorkerIdleSnapshot:
    """A point-in-time explanation of the strict idle gate."""

    strict_idle: bool
    reusable_idle: bool
    reasons: Tuple[str, ...] = ()
    active_turns: int = 0
    active_sessions: int = 0
    finished_unstopped_sessions: int = 0
    pending_open_ops: int = 0
    pending_lifecycle_ops: int = 0
    pending_text_ops: int = 0
    playback_active: bool = False
    playback_queue_depth: int = 0
    playback_queue_duration_ms: int = 0
    worker_alive: bool = False
    stop_confirmed: bool = True

    def to_dict(self) -> dict:
        return {
            "strict_idle": self.strict_idle,
            "reusable_idle": self.reusable_idle,
            "reasons": list(self.reasons),
            "active_turns": self.active_turns,
            "active_sessions": self.active_sessions,
            "finished_unstopped_sessions": self.finished_unstopped_sessions,
            "pending_open_ops": self.pending_open_ops,
            "pending_lifecycle_ops": self.pending_lifecycle_ops,
            "pending_text_ops": self.pending_text_ops,
            "playback_active": self.playback_active,
            "playback_queue_depth": self.playback_queue_depth,
            "playback_queue_duration_ms": self.playback_queue_duration_ms,
            "worker_alive": self.worker_alive,
            "stop_confirmed": self.stop_confirmed,
        }


class StrictIdleGate:
    """Thread-safe gate for provider switching and worker recycling.

    ``reusable_idle`` permits another session on the same live worker.  The
    stronger ``strict_idle`` additionally requires a stop observation for any
    finished session, which is the only state in which a worker may be
    replaced or a provider may be switched.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._active_turns: Set[str] = set()
        self._active_sessions: Set[str] = set()
        self._finished_unstopped: Set[str] = set()
        self._pending_open_ops = 0
        self._pending_lifecycle_ops = 0
        self._pending_text_ops = 0
        self._playback_active = False
        self._playback_queue_depth = 0
        self._playback_queue_duration_ms = 0
        self._worker_alive = False
        self._stop_confirmed = True

    def set_worker_alive(self, alive: bool) -> None:
        with self._lock:
            self._worker_alive = bool(alive)
            # Process exit is equivalent to physical stop evidence only when
            # there is no still-owned session waiting for its final callback.
            if not alive and not self._active_sessions:
                self._finished_unstopped.clear()
                self._stop_confirmed = True

    def begin_turn(self, turn_id: str) -> None:
        self._require_id(turn_id, "turn_id")
        with self._lock:
            self._active_turns.add(str(turn_id))

    def end_turn(self, turn_id: str) -> None:
        with self._lock:
            self._active_turns.discard(str(turn_id))

    def begin_session(self, speech_id: str) -> None:
        self._require_id(speech_id, "speech_id")
        with self._lock:
            sid = str(speech_id)
            self._active_sessions.add(sid)
            self._finished_unstopped.discard(sid)
            self._stop_confirmed = False

    def mark_session_done(self, speech_id: str) -> None:
        with self._lock:
            sid = str(speech_id)
            self._active_sessions.discard(sid)
            self._finished_unstopped.add(sid)
            self._stop_confirmed = False

    def mark_session_stopped(self, speech_id: str) -> None:
        with self._lock:
            sid = str(speech_id)
            self._active_sessions.discard(sid)
            self._finished_unstopped.discard(sid)
            if not self._active_sessions and not self._finished_unstopped:
                self._stop_confirmed = True

    def mark_session_abandoned(self, speech_id: str) -> None:
        """Drop ownership after a worker exit has supplied stop evidence."""
        with self._lock:
            sid = str(speech_id)
            self._active_sessions.discard(sid)
            self._finished_unstopped.discard(sid)
            if not self._active_sessions:
                self._stop_confirmed = True

    def mark_stop_unconfirmed(self) -> None:
        """Record a failed worker-stop observation until force recovery."""
        with self._lock:
            self._stop_confirmed = False

    def begin_open(self) -> None:
        """Reserve the worker while a session is being opened."""
        with self._lock:
            self._pending_open_ops += 1

    def end_open(self) -> None:
        with self._lock:
            self._pending_open_ops = max(0, self._pending_open_ops - 1)

    def begin_lifecycle(self) -> None:
        """Reserve an exclusive stop/recycle operation."""
        with self._lock:
            self._pending_lifecycle_ops += 1

    def end_lifecycle(self) -> None:
        with self._lock:
            self._pending_lifecycle_ops = max(0, self._pending_lifecycle_ops - 1)

    def begin_text(self) -> None:
        with self._lock:
            self._pending_text_ops += 1

    def end_text(self) -> None:
        with self._lock:
            self._pending_text_ops = max(0, self._pending_text_ops - 1)

    def set_playback(
        self,
        *,
        active: bool,
        queue_depth: int = 0,
        queue_duration_ms: int = 0,
    ) -> None:
        if int(queue_depth) < 0 or int(queue_duration_ms) < 0:
            raise ValueError("playback queue values must not be negative")
        with self._lock:
            self._playback_active = bool(active)
            self._playback_queue_depth = int(queue_depth)
            self._playback_queue_duration_ms = int(queue_duration_ms)

    def snapshot(self) -> WorkerIdleSnapshot:
        with self._lock:
            reasons = []
            if self._active_turns:
                reasons.append("active_turn")
            if self._active_sessions:
                reasons.append("active_session")
            if self._finished_unstopped:
                reasons.append("provider_stop_unconfirmed")
            if self._pending_open_ops:
                reasons.append("pending_open")
            if self._pending_lifecycle_ops:
                reasons.append("pending_lifecycle")
            if self._pending_text_ops:
                reasons.append("pending_text")
            if self._playback_active or self._playback_queue_depth or self._playback_queue_duration_ms:
                reasons.append("playback_not_empty")
            if not self._worker_alive:
                reasons.append("worker_not_alive")
            base_idle = not (
                self._active_turns
                or self._active_sessions
                or self._pending_open_ops
                or self._pending_lifecycle_ops
                or self._pending_text_ops
                or self._playback_active
                or self._playback_queue_depth
                or self._playback_queue_duration_ms
            )
            reusable = base_idle and self._worker_alive
            # A dead worker is already a stop boundary once no session remains
            # owned.  This is what lets a crashed process be recycled; it does
            # not make the dead worker reusable for a new request.
            strict = base_idle and not self._finished_unstopped and self._stop_confirmed
            return WorkerIdleSnapshot(
                strict_idle=bool(strict),
                reusable_idle=bool(reusable),
                reasons=tuple(reasons),
                active_turns=len(self._active_turns),
                active_sessions=len(self._active_sessions),
                finished_unstopped_sessions=len(self._finished_unstopped),
                pending_open_ops=self._pending_open_ops,
                pending_lifecycle_ops=self._pending_lifecycle_ops,
                pending_text_ops=self._pending_text_ops,
                playback_active=self._playback_active,
                playback_queue_depth=self._playback_queue_depth,
                playback_queue_duration_ms=self._playback_queue_duration_ms,
                worker_alive=self._worker_alive,
                stop_confirmed=self._stop_confirmed,
            )

    def is_strict_idle(self) -> bool:
        return self.snapshot().strict_idle

    @staticmethod
    def _require_id(value: str, name: str) -> None:
        if not str(value).strip():
            raise ValueError(name + " must not be empty")


class PersistentTTSProvider:
    """Provider-port facade backed by one persistent, recyclable worker.

    ``worker_factory`` is intentionally injected.  It can return a process
    proxy, a thread worker, or a deterministic fake; the facade never imports
    a model package or opens an audio device.  Set ``worker_isolated`` only
    when the supplied factory really owns an independent process/thread.
    """

    def __init__(
        self,
        worker_factory: WorkerProviderFactory | Any,
        *,
        capabilities: Optional[TTSProviderCapabilities | Mapping[str, Any]] = None,
        provider_id: str = "",
        worker_isolated: bool = False,
        worker_persistent: bool = True,
        stop_timeout_s: float = 3.0,
        worker_id: Optional[str] = None,
    ) -> None:
        if not callable(worker_factory) and not is_tts_provider_port(worker_factory):
            raise TypeError("worker_factory must be callable or a TTSProviderPort")
        if float(stop_timeout_s) <= 0:
            raise ValueError("stop_timeout_s must be positive")
        self._template = worker_factory if is_tts_provider_port(worker_factory) else None
        self._factory: WorkerProviderFactory = (
            (lambda: worker_factory)
            if self._template is not None
            else worker_factory
        )
        self._explicit_capabilities = (
            coerce_capabilities(capabilities) if capabilities is not None else None
        )
        self._provider_id = str(provider_id or "").strip()
        self._worker_isolated = bool(worker_isolated)
        self._worker_persistent = bool(worker_persistent)
        self.stop_timeout_s = float(stop_timeout_s)
        self.worker_id = str(worker_id or ("tts-worker-" + uuid.uuid4().hex[:12]))

        self._lock = threading.RLock()
        self._start_lock = threading.Lock()
        self._worker: Any = None
        self._state = WorkerLifecycleState.STOPPED
        # These reservations are guarded by ``_lock`` and span the potentially
        # asynchronous provider call.  They close the race between an open and
        # a concurrent recycle/switch without holding a thread lock across an
        # await point.
        self._open_in_progress = 0
        self._lifecycle_in_progress = False
        self._generation = 0
        self._epoch_floor = -1
        self._active_sessions: Dict[str, WorkerTTSSession] = {}
        self._finished_sessions: Dict[str, WorkerTTSSession] = {}
        self._last_error_code: Optional[str] = None
        self._last_error_detail = ""
        self._started_at: Optional[float] = None
        self._last_recycled_at: Optional[float] = None
        self._recycle_count = 0
        self._stale_event_count = 0
        self._gate = StrictIdleGate()

    # ------------------------------------------------------------------
    # Provider-port surface
    # ------------------------------------------------------------------
    def describe_capabilities(self) -> TTSProviderCapabilities:
        """Return a declaration without starting a worker."""
        with self._lock:
            base = self._explicit_capabilities
            template = self._template
            worker = self._worker
        if base is None:
            candidate = template or worker
            if candidate is not None:
                method = getattr(candidate, "describe_capabilities", None)
                if callable(method):
                    try:
                        base = coerce_capabilities(method())
                    except Exception as exc:
                        raise WorkerLifecycleError(
                            "VOICE-TTS-CAPABILITY-ERROR", str(exc)[:400]
                        ) from exc
        if base is None:
            if not self._provider_id:
                raise WorkerLifecycleError(
                    "VOICE-TTS-CAPABILITY-UNAVAILABLE",
                    "capabilities must be supplied before a factory is started",
                )
            # A conservative declaration is preferable to loading a model just
            # to discover metadata.  It can never qualify for C on its own.
            base = TTSProviderCapabilities(provider_id=self._provider_id)
        return replace(
            base,
            worker_isolated=self._worker_isolated,
            worker_persistent=self._worker_persistent,
        )

    async def open(self, request: TTSRequest) -> "WorkerTTSSession":
        if not isinstance(request, TTSRequest):
            raise TypeError("request must be TTSRequest")
        with self._lock:
            if request.provider_epoch < self._epoch_floor:
                raise WorkerLifecycleError(
                    "VOICE-TTS-WORKER-EPOCH-STALE",
                    f"request epoch {request.provider_epoch} < {self._epoch_floor}",
                )
            if self._lifecycle_in_progress:
                raise WorkerLifecycleError(
                    "VOICE-TTS-WORKER-BUSY",
                    "worker lifecycle transition is in progress",
                )
            if self._open_in_progress:
                raise WorkerLifecycleError(
                    "VOICE-TTS-WORKER-BUSY",
                    "another session is opening",
                )
            if self._active_sessions:
                raise WorkerLifecycleError(
                    "VOICE-TTS-WORKER-BUSY",
                    "one persistent provider owns at most one active session",
                )
            if request.speech_id in self._finished_sessions:
                raise WorkerLifecycleError(
                    "VOICE-TTS-SESSION-ID-BUSY",
                    "speech_id still awaits stop evidence",
                )
            self._open_in_progress += 1
            self._gate.begin_open()

        try:
            # The reservation is visible to the idle gate while startup is
            # performed.  ``allow_pending_open`` lets this operation cross the
            # initial stopped -> started boundary without weakening callers'
            # normal idle checks.
            await asyncio.to_thread(self._ensure_started, allow_pending_open=True)
            with self._lock:
                self._epoch_floor = max(self._epoch_floor, request.provider_epoch)
                self._refresh_liveness_locked()
                if self._state is not WorkerLifecycleState.READY:
                    raise WorkerLifecycleError(
                        "VOICE-TTS-WORKER-NOT-READY", self._state.value
                    )
                if self._active_sessions:
                    raise WorkerLifecycleError(
                        "VOICE-TTS-WORKER-BUSY",
                        "one persistent provider owns at most one active session",
                    )
                if request.speech_id in self._finished_sessions:
                    raise WorkerLifecycleError(
                        "VOICE-TTS-SESSION-ID-BUSY",
                        "speech_id still awaits stop evidence",
                    )
                worker = self._worker
                generation = self._generation
            if worker is None:
                raise WorkerLifecycleError(
                    "VOICE-TTS-WORKER-NOT-READY", "worker is unavailable"
                )
            # Provider ``open`` may be synchronous or asynchronous.  Keep a
            # synchronous model/process proxy off the event loop just like the
            # session methods below.
            raw_session = await _invoke_async(worker.open, request)
            if not is_tts_provider_session(raw_session):
                raise WorkerLifecycleError(
                    "VOICE-TTS-SESSION-INVALID",
                    "worker.open() did not return TTSProviderSession",
                )
            session = WorkerTTSSession(self, raw_session, request, generation)
            generation_stale = False
            with self._lock:
                # A worker may have exited while open() was awaiting.  Do not
                # publish a session from that dead/old generation.
                self._refresh_liveness_locked()
                if (
                    generation != self._generation
                    or worker is not self._worker
                    or self._state is not WorkerLifecycleState.READY
                ):
                    self._stale_event_count += 1
                    generation_stale = True
                else:
                    self._active_sessions[request.speech_id] = session
                    self._state = WorkerLifecycleState.BUSY
                    self._gate.begin_session(request.speech_id)
            if generation_stale:
                # Do not use the generation-guarded facade method here: the
                # raw session is precisely the object that must be stopped.
                try:
                    cancel_method = getattr(raw_session, "cancel", None)
                    if callable(cancel_method):
                        await _invoke_async(cancel_method, "worker_generation_changed")
                except Exception:
                    pass
                raise WorkerLifecycleError(
                    "VOICE-TTS-WORKER-GENERATION-STALE",
                    "worker changed while session was opening",
                )
            return session
        except WorkerLifecycleError as exc:
            self._record_error(exc.code, exc)
            raise
        except Exception as exc:
            self._record_error("VOICE-TTS-WORKER-OPEN-FAILED", exc)
            raise WorkerLifecycleError(
                "VOICE-TTS-WORKER-OPEN-FAILED", str(exc)[:400]
            ) from exc
        finally:
            with self._lock:
                self._open_in_progress = max(0, self._open_in_progress - 1)
                self._gate.end_open()

    def health(self) -> Mapping[str, Any]:
        with self._lock:
            self._refresh_liveness_locked()
            worker = self._worker
            state = self._state
            generation = self._generation
            last_error = self._last_error_code
            detail = self._last_error_detail
        try:
            provider_id = self.describe_capabilities().provider_id
        except Exception:
            provider_id = self._provider_id or "unknown"
        alive_signal = _read_alive(worker)
        idle = self.strict_idle_snapshot()
        result: Dict[str, Any] = {
            "provider_id": provider_id,
            "worker_id": self.worker_id,
            "worker_generation": generation,
            "state": state.value,
            "ready": state in (WorkerLifecycleState.READY, WorkerLifecycleState.BUSY),
            # A provider proxy without an explicit liveness method is usable,
            # but its process state is unknown; do not report that as a false
            # crash.  The gate uses its own lifecycle evidence separately.
            "alive": (
                None
                if alive_signal is None and worker is not None
                else bool(alive_signal)
            ),
            "liveness_known": alive_signal is not None,
            "strict_idle": idle.strict_idle,
            "reusable_idle": idle.reusable_idle,
        }
        if last_error:
            result["last_error_code"] = last_error
            result["last_error_detail"] = detail
        provider_health = self._safe_provider_mapping(worker, "health")
        if provider_health:
            result["provider"] = provider_health
        return result

    def metrics(self) -> Mapping[str, Any]:
        with self._lock:
            self._refresh_liveness_locked()
            worker = self._worker
            state = self._state
            generation = self._generation
            active = tuple(self._active_sessions)
            finished = tuple(self._finished_sessions)
            counters = {
                "recycle_count": self._recycle_count,
                "stale_event_count": self._stale_event_count,
            }
        idle = self.strict_idle_snapshot()
        try:
            provider_id = self.describe_capabilities().provider_id
        except Exception:
            provider_id = self._provider_id or "unknown"
        result: Dict[str, Any] = {
            "provider_id": provider_id,
            "worker_id": self.worker_id,
            "worker_generation": generation,
            "state": state.value,
            "active_sessions": list(active),
            "finished_sessions": list(finished),
            "idle": idle.to_dict(),
            **counters,
        }
        provider_metrics = self._safe_provider_mapping(worker, "metrics")
        if provider_metrics:
            result["provider"] = provider_metrics
        return result

    # ------------------------------------------------------------------
    # Lifecycle and idle controls
    # ------------------------------------------------------------------
    def start(self) -> None:
        """Start the worker once; normal ``open`` calls start lazily."""
        self._ensure_started()

    def strict_idle_snapshot(self) -> WorkerIdleSnapshot:
        snapshot = self._gate.snapshot()
        # A worker that is failed/stopping is never a valid reuse target even
        # when the physical process happens to still report alive.  The gate
        # can still expose strict-idle evidence for explicit recovery.
        with self._lock:
            state = self._state
        if state not in (WorkerLifecycleState.READY, WorkerLifecycleState.BUSY):
            return replace(snapshot, reusable_idle=False)
        return snapshot

    def set_playback_state(
        self,
        *,
        active: bool,
        queue_depth: int = 0,
        queue_duration_ms: int = 0,
    ) -> None:
        self._gate.set_playback(
            active=active,
            queue_depth=queue_depth,
            queue_duration_ms=queue_duration_ms,
        )

    def begin_turn(self, turn_id: str) -> None:
        self._gate.begin_turn(turn_id)

    def end_turn(self, turn_id: str) -> None:
        self._gate.end_turn(turn_id)

    async def wait_idle_stopped(self, timeout_s: Optional[float] = None) -> bool:
        """Collect stop evidence for completed sessions before a switch.

        A persistent worker may finish a request while remaining alive for the
        next turn.  The request slot is reusable at that point, but replacing
        the worker still requires each completed session's stop observer.  This
        method is the explicit bridge between those two states.
        """
        timeout = self.stop_timeout_s if timeout_s is None else max(float(timeout_s), 0.0)
        deadline = time.monotonic() + timeout
        while True:
            with self._lock:
                finished = tuple(self._finished_sessions.values())
                active = bool(self._active_sessions)
            if active:
                return False
            if not finished:
                return self._gate.is_strict_idle()
            for session in finished:
                remaining = max(0.0, deadline - time.monotonic())
                if not await session.wait_stopped(remaining):
                    return False
            with self._lock:
                if not self._finished_sessions:
                    return self._gate.is_strict_idle()
            if time.monotonic() >= deadline:
                return False

    def pending_stop_sessions(self) -> Tuple[str, ...]:
        """Return completed speech ids still lacking stop evidence."""
        with self._lock:
            return tuple(self._finished_sessions)

    def assert_strict_idle(self) -> None:
        """Raise when a caller attempts provider switching before stop proof."""
        snapshot = self._gate.snapshot()
        if not snapshot.strict_idle:
            raise WorkerLifecycleError(
                "VOICE-TTS-WORKER-NOT-IDLE",
                ";".join(snapshot.reasons) or "provider is not strictly idle",
            )

    def advance_epoch(self, provider_epoch: int) -> None:
        """Raise the accepted epoch at an externally verified idle boundary."""
        epoch = int(provider_epoch)
        if epoch < 0:
            raise ValueError("provider_epoch must not be negative")
        snapshot = self._gate.snapshot()
        blocking_reasons = tuple(reason for reason in snapshot.reasons if reason != "worker_not_alive")
        if blocking_reasons and epoch > self._epoch_floor:
            raise WorkerLifecycleError(
                "VOICE-TTS-WORKER-NOT-IDLE",
                ";".join(blocking_reasons) or "provider is not strictly idle",
            )
        with self._lock:
            self._epoch_floor = max(self._epoch_floor, epoch)

    def recycle(self, reason: str = "idle_recycle", *, timeout_s: Optional[float] = None) -> None:
        """Stop and rebuild the persistent worker at a strict idle boundary."""
        timeout = self.stop_timeout_s if timeout_s is None else float(timeout_s)
        if timeout <= 0:
            raise ValueError("timeout_s must be positive")
        self._reserve_lifecycle(force=False)
        try:
            self._stop_current_worker(reason, timeout, force=False)
            self._ensure_started(allow_pending_lifecycle=True)
            with self._lock:
                self._recycle_count += 1
                self._last_recycled_at = time.time()
        finally:
            self._release_lifecycle()

    def shutdown(self, reason: str = "shutdown", *, timeout_s: Optional[float] = None) -> None:
        """Release the worker; callers must cancel active sessions first."""
        timeout = self.stop_timeout_s if timeout_s is None else float(timeout_s)
        if timeout <= 0:
            raise ValueError("timeout_s must be positive")
        self._reserve_lifecycle(force=False)
        try:
            self._stop_current_worker(reason, timeout, force=False)
        finally:
            self._release_lifecycle()

    def force_recycle(self, reason: str = "worker_fault", *, timeout_s: Optional[float] = None) -> None:
        """Terminate a failed worker after activity is idle, overriding stop proof."""
        timeout = self.stop_timeout_s if timeout_s is None else float(timeout_s)
        self._reserve_lifecycle(force=True)
        try:
            self._stop_current_worker(reason, timeout, force=True)
            self._ensure_started(allow_pending_lifecycle=True)
            with self._lock:
                self._recycle_count += 1
                self._last_recycled_at = time.time()
        finally:
            self._release_lifecycle()

    def _reserve_lifecycle(self, *, force: bool) -> None:
        """Reserve an exclusive lifecycle transition before checking idle state."""
        with self._lock:
            self._refresh_liveness_locked()
            if self._lifecycle_in_progress:
                raise WorkerLifecycleError(
                    "VOICE-TTS-WORKER-BUSY",
                    "another worker lifecycle transition is in progress",
                )
            if self._open_in_progress:
                raise WorkerLifecycleError(
                    "VOICE-TTS-WORKER-NOT-IDLE",
                    "pending_open",
                )
            snapshot = self._gate.snapshot()
            if force:
                recoverable_reasons = {"provider_stop_unconfirmed", "worker_not_alive"}
                if any(item not in recoverable_reasons for item in snapshot.reasons):
                    raise WorkerLifecycleError(
                        "VOICE-TTS-WORKER-NOT-IDLE",
                        ";".join(snapshot.reasons) or "provider is not strictly idle",
                    )
            elif not snapshot.strict_idle:
                raise WorkerLifecycleError(
                    "VOICE-TTS-WORKER-NOT-IDLE",
                    ";".join(snapshot.reasons) or "provider is not strictly idle",
                )
            self._lifecycle_in_progress = True
            self._gate.begin_lifecycle()

    def _release_lifecycle(self) -> None:
        with self._lock:
            self._lifecycle_in_progress = False
            self._gate.end_lifecycle()

    def _ensure_started(
        self,
        *,
        allow_pending_open: bool = False,
        allow_pending_lifecycle: bool = False,
    ) -> None:
        with self._start_lock:
            with self._lock:
                self._refresh_liveness_locked()
                if self._worker is not None and self._state in (
                    WorkerLifecycleState.READY,
                    WorkerLifecycleState.BUSY,
                ):
                    return
                if self._worker is not None and self._state is not WorkerLifecycleState.STOPPED:
                    # A failed graceful stop may have left a live process
                    # behind.  Never create a second model instance until the
                    # caller explicitly performs force_recycle().
                    alive = _read_alive(self._worker)
                    if alive is not False:
                        raise WorkerLifecycleError(
                            "VOICE-TTS-WORKER-RECOVERY-REQUIRED",
                            self._state.value,
                        )
                if self._active_sessions:
                    raise WorkerLifecycleError(
                        "VOICE-TTS-WORKER-CRASHED",
                        "cannot rebuild while a session is still owned",
                    )
                # A failed stop/rebuild must not silently cross the strict
                # idle boundary when a caller retries ``open``.
                idle = self.strict_idle_snapshot()
                ignored_reasons = {"worker_not_alive"}
                if allow_pending_open:
                    ignored_reasons.add("pending_open")
                if allow_pending_lifecycle:
                    ignored_reasons.add("pending_lifecycle")
                restart_boundary = (
                    self._state is WorkerLifecycleState.STOPPED
                    and not self._active_sessions
                    and not any(reason not in ignored_reasons for reason in idle.reasons)
                )
                if any(reason not in ignored_reasons for reason in idle.reasons) and not restart_boundary:
                    raise WorkerLifecycleError(
                        "VOICE-TTS-WORKER-NOT-IDLE",
                        ";".join(idle.reasons) or "provider is not strictly idle",
                    )
                self._state = WorkerLifecycleState.STARTING
            worker = None
            try:
                worker = self._factory()
                if inspect.isawaitable(worker):
                    close = getattr(worker, "close", None)
                    if callable(close):
                        close()
                    raise WorkerLifecycleError(
                        "VOICE-TTS-WORKER-ASYNC-FACTORY",
                        "worker factory must return synchronously",
                    )
                if not is_tts_provider_port(worker):
                    raise WorkerLifecycleError(
                        "VOICE-TTS-WORKER-PORT-INVALID",
                        "worker does not implement TTSProviderPort",
                    )
                start = getattr(worker, "start", None)
                if callable(start):
                    _call_lifecycle(start)
                alive = _read_alive(worker)
                if alive is False:
                    raise WorkerLifecycleError(
                        "VOICE-TTS-WORKER-START-FAILED", "worker is not alive after start"
                    )
                with self._lock:
                    self._worker = worker
                    self._generation += 1
                    self._state = WorkerLifecycleState.READY
                    self._started_at = time.time()
                    self._last_error_code = None
                    self._last_error_detail = ""
                    self._gate.set_worker_alive(True)
            except WorkerLifecycleError as exc:
                self._best_effort_close(worker)
                self._record_error(exc.code, exc)
                with self._lock:
                    self._worker = None
                    self._state = WorkerLifecycleState.FAILED
                    self._gate.set_worker_alive(False)
                raise
            except Exception as exc:
                self._best_effort_close(worker)
                self._record_error("VOICE-TTS-WORKER-START-FAILED", exc)
                with self._lock:
                    self._worker = None
                    self._state = WorkerLifecycleState.FAILED
                    self._gate.set_worker_alive(False)
                raise WorkerLifecycleError(
                    "VOICE-TTS-WORKER-START-FAILED", str(exc)[:400]
                ) from exc

    @staticmethod
    def _best_effort_close(worker: Any) -> None:
        """Release a partially started worker without masking the root error."""
        if worker is None:
            return
        for name in ("shutdown", "stop", "close"):
            method = getattr(worker, name, None)
            if callable(method):
                try:
                    _call_lifecycle(method, "startup_failed")
                except Exception:
                    pass
                return

    def _stop_current_worker(self, reason: str, timeout_s: float, *, force: bool) -> None:
        with self._lock:
            worker = self._worker
            if worker is None:
                self._state = WorkerLifecycleState.STOPPED
                self._active_sessions.clear()
                self._finished_sessions.clear()
                self._gate.set_worker_alive(False)
                return
            self._state = WorkerLifecycleState.STOPPING
        stop_method = None
        for name in (("shutdown", "stop", "close") if not force else ("shutdown", "stop", "close", "terminate")):
            candidate = getattr(worker, name, None)
            if callable(candidate):
                stop_method = candidate
                break
        try:
            if stop_method is not None:
                _call_lifecycle(stop_method, str(reason or "worker_stop")[:160])
            stopped = self._observe_worker_stop(worker, timeout_s)
            if not stopped and force:
                terminate = getattr(worker, "terminate", None)
                if callable(terminate) and terminate is not stop_method:
                    _call_lifecycle(terminate)
                    stopped = self._observe_worker_stop(worker, timeout_s)
            if not stopped:
                code = (
                    "VOICE-TTS-WORKER-STOP-TIMEOUT"
                    if _read_alive(worker) is not False
                    else "VOICE-TTS-WORKER-STOP-UNCONFIRMED"
                )
                raise WorkerLifecycleError(code, "worker did not provide stop evidence")
        except WorkerLifecycleError as exc:
            self._gate.mark_stop_unconfirmed()
            self._record_error(exc.code, exc)
            with self._lock:
                self._state = WorkerLifecycleState.FAILED
            raise
        except Exception as exc:
            self._gate.mark_stop_unconfirmed()
            self._record_error("VOICE-TTS-WORKER-STOP-FAILED", exc)
            with self._lock:
                self._state = WorkerLifecycleState.FAILED
            raise WorkerLifecycleError(
                "VOICE-TTS-WORKER-STOP-FAILED", str(exc)[:400]
            ) from exc
        with self._lock:
            self._worker = None
            self._state = WorkerLifecycleState.STOPPED
            self._active_sessions.clear()
            self._finished_sessions.clear()
            self._gate.set_worker_alive(False)

    @staticmethod
    def _observe_worker_stop(worker: Any, timeout_s: float) -> bool:
        observer = getattr(worker, "wait_stopped", None)
        if callable(observer):
            try:
                result = _call_lifecycle(observer, max(float(timeout_s), 0.0))
                return bool(result)
            except WorkerLifecycleError:
                raise
            except Exception:
                return False
        alive = _read_alive(worker)
        if alive is False:
            return True
        deadline = time.monotonic() + max(float(timeout_s), 0.0)
        while time.monotonic() < deadline:
            alive = _read_alive(worker)
            if alive is False:
                return True
            time.sleep(min(0.01, max(0.0, deadline - time.monotonic())))
        return _read_alive(worker) is False

    def _refresh_liveness_locked(self) -> None:
        if self._worker is None:
            self._gate.set_worker_alive(False)
            return
        alive = _read_alive(self._worker)
        if alive is False:
            abandoned = tuple(
                dict.fromkeys(
                    (*self._active_sessions.keys(), *self._finished_sessions.keys())
                )
            )
            if abandoned:
                self._record_error("VOICE-TTS-WORKER-CRASHED", RuntimeError("worker exited"))
                self._active_sessions.clear()
                self._finished_sessions.clear()
                for speech_id in abandoned:
                    self._gate.mark_session_abandoned(speech_id)
            self._state = WorkerLifecycleState.FAILED
            self._gate.set_worker_alive(False)
        else:
            self._gate.set_worker_alive(True)

    def _record_error(self, code: str, error: BaseException) -> None:
        with self._lock:
            self._last_error_code = str(code)[:160]
            self._last_error_detail = str(error)[:400]

    def _safe_provider_mapping(self, worker: Any, method_name: str) -> dict:
        if worker is None:
            return {}
        method = getattr(worker, method_name, None)
        if not callable(method):
            return {}
        try:
            value = _call_lifecycle(method)
        except Exception as exc:
            return {"state": "unavailable", "error_code": "VOICE-TTS-WORKER-METRICS-ERROR", "detail": str(exc)[:160]}
        if isinstance(value, Mapping):
            return {str(k): _safe_value(v, str(k)) for k, v in value.items()}
        return {"value": _safe_value(value)}

    # Session callbacks -------------------------------------------------
    def _session_current(self, session: "WorkerTTSSession") -> bool:
        with self._lock:
            current = self._active_sessions.get(session.request.speech_id)
            return current is session and session.generation == self._generation and self._worker is not None

    def _register_text(self) -> None:
        self._gate.begin_text()

    def _unregister_text(self) -> None:
        self._gate.end_text()

    def _session_done(self, session: "WorkerTTSSession") -> None:
        with self._lock:
            if self._active_sessions.get(session.request.speech_id) is not session:
                return
            # DONE closes the request slot so the persistent worker can serve
            # the next turn.  The gate still retains an unstopped marker until
            # wait_stopped (or worker exit) supplies switch/recycle evidence.
            self._active_sessions.pop(session.request.speech_id, None)
            self._finished_sessions[session.request.speech_id] = session
            self._state = WorkerLifecycleState.READY
        self._gate.mark_session_done(session.request.speech_id)

    def _session_stopped(self, session: "WorkerTTSSession") -> None:
        with self._lock:
            speech_id = session.request.speech_id
            active = self._active_sessions.get(speech_id)
            finished = self._finished_sessions.get(speech_id)
            # A late callback from an old generation must not clear a newer
            # session that happens to use the same speech id.
            if active is not session and finished is not session:
                self._stale_event_count += 1
                return
            if active is session:
                self._active_sessions.pop(speech_id, None)
            if finished is session:
                self._finished_sessions.pop(speech_id, None)
            if self._worker is not None and self._state is not WorkerLifecycleState.FAILED:
                self._state = WorkerLifecycleState.READY
        self._gate.mark_session_stopped(speech_id)

    def _session_finished_without_done(self, session: "WorkerTTSSession") -> None:
        with self._lock:
            speech_id = session.request.speech_id
            if self._active_sessions.get(speech_id) is not session:
                self._stale_event_count += 1
                return
            self._active_sessions.pop(speech_id, None)
            self._finished_sessions[speech_id] = session
            self._state = WorkerLifecycleState.READY
        # The stream ended without a valid DONE event.  The slot is reusable
        # only after the physical stop observer confirms this session ended.
        self._gate.mark_session_done(speech_id)

    def _session_error(self, session: "WorkerTTSSession", error: BaseException) -> None:
        self._record_error(_error_code(error, "VOICE-TTS-WORKER-SESSION-FAILED"), error)

    def _stale(self) -> None:
        with self._lock:
            self._stale_event_count += 1


class WorkerTTSSession:
    """Generation-bound proxy around the provider's request session."""

    def __init__(
        self,
        owner: PersistentTTSProvider,
        inner: Any,
        request: TTSRequest,
        generation: int,
    ) -> None:
        self.owner = owner
        self.inner = inner
        self.request = request
        self.generation = int(generation)
        self.session_id = request.session_id
        self._cancelled = False
        self._committed = False
        self._done = False
        self._stopped = False
        self._next_event_sequence = 0

    async def push_text(self, delta: str) -> Any:
        self._ensure_current()
        self.owner._register_text()
        try:
            method = getattr(self.inner, "push_text")
            return await _invoke_async(method, str(delta))
        except Exception as exc:
            self.owner._session_error(self, exc)
            raise
        finally:
            self.owner._unregister_text()

    async def commit_text(self) -> Any:
        self._ensure_current()
        self.owner._register_text()
        try:
            method = getattr(self.inner, "commit_text")
            result = await _invoke_async(method)
            self._committed = True
            return result
        except Exception as exc:
            self.owner._session_error(self, exc)
            raise
        finally:
            self.owner._unregister_text()

    async def audio_events(self) -> AsyncIterator[TTSProviderEvent]:
        self._ensure_current()
        try:
            method = getattr(self.inner, "audio_events")
            stream = await _invoke_async(method)
            if hasattr(stream, "__aiter__"):
                async for raw in stream:
                    event = self._coerce_or_drop(raw)
                    if event is None:
                        if not self.owner._session_current(self):
                            return
                        continue
                    self._observe_event(event)
                    yield event
            else:
                iterator = iter(stream)
                while True:
                    has_item, raw = await asyncio.to_thread(_next_sync, iterator)
                    if not has_item:
                        break
                    event = self._coerce_or_drop(raw)
                    if event is None:
                        if not self.owner._session_current(self):
                            return
                        continue
                    self._observe_event(event)
                    yield event
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.owner._session_error(self, exc)
            raise
        finally:
            if not self._done and not self._stopped:
                self.owner._session_finished_without_done(self)

    async def cancel(self, reason: str = "cancelled") -> Any:
        if self._stopped:
            return True
        self._cancelled = True
        method = getattr(self.inner, "cancel", None)
        if not callable(method):
            raise WorkerLifecycleError(
                "VOICE-TTS-WORKER-CANCEL-UNSUPPORTED", "session has no cancel method"
            )
        try:
            return await _invoke_async(method, str(reason or "cancelled")[:160])
        except Exception as exc:
            self.owner._session_error(self, exc)
            raise

    async def wait_stopped(self, timeout_s: float) -> bool:
        if self._stopped:
            return True
        timeout = max(float(timeout_s), 0.0)
        method = getattr(self.inner, "wait_stopped", None)
        try:
            if callable(method):
                result = await _invoke_async(method, timeout)
            else:
                # A dead worker is physical stop evidence even if the session
                # proxy itself has no observer.
                alive = _read_alive(self.owner._worker)
                result = alive is False
            if result:
                self._stopped = True
                self.owner._session_stopped(self)
                return True
            return False
        except Exception as exc:
            self.owner._session_error(self, exc)
            return False

    def health(self) -> Mapping[str, Any]:
        return self._mapping("health")

    def metrics(self) -> Mapping[str, Any]:
        result = self._mapping("metrics")
        result.update(
            {
                "speech_id": self.request.speech_id,
                "provider_epoch": self.request.provider_epoch,
                "worker_generation": self.generation,
                "committed": self._committed,
                "cancelled": self._cancelled,
            }
        )
        return result

    def _mapping(self, name: str) -> dict:
        method = getattr(self.inner, name, None)
        if not callable(method):
            return {"state": "unavailable", "error_code": "VOICE-TTS-SESSION-METRICS-UNSUPPORTED"}
        try:
            value = method()
            if inspect.isawaitable(value):
                return {"state": "unavailable", "error_code": "VOICE-TTS-SESSION-ASYNC-METRICS"}
            if isinstance(value, Mapping):
                return {str(k): _safe_value(v, str(k)) for k, v in value.items()}
            return {"value": _safe_value(value)}
        except Exception as exc:
            return {"state": "failed", "error_code": "VOICE-TTS-SESSION-METRICS-ERROR", "detail": str(exc)[:160]}

    def _ensure_current(self) -> None:
        if not self.owner._session_current(self):
            self.owner._stale()
            raise WorkerLifecycleError(
                "VOICE-TTS-WORKER-SESSION-STALE",
                "session belongs to an old worker generation",
            )

    def _coerce_or_drop(self, raw: Any) -> Optional[TTSProviderEvent]:
        try:
            event = coerce_provider_event(
                raw,
                request=self.request,
                default_sequence=self._next_event_sequence,
            )
        except Exception as exc:
            self.owner._session_error(self, exc)
            raise
        if (
            event.speech_id != self.request.speech_id
            or event.provider_epoch != self.request.provider_epoch
        ):
            self.owner._stale()
            return None
        if not self.owner._session_current(self):
            # ``wait_stopped`` may observe the inner session before its final
            # STOPPED event has reached the consumer.  Deliver that one
            # identity-matched terminal event, but never allow late PCM/DONE
            # from a detached generation to cross the boundary.
            if self._stopped and event.kind == TTSEventKind.STOPPED.value:
                return event
            self.owner._stale()
            return None
        if event.kind == TTSEventKind.PCM_CHUNK.value:
            self._next_event_sequence = max(
                self._next_event_sequence,
                event.sequence + 1,
                event.chunk.sequence + 1 if event.chunk is not None else 0,
            )
        return event

    def _observe_event(self, event: TTSProviderEvent) -> None:
        if event.kind == TTSEventKind.DONE.value:
            if not self._committed:
                raise WorkerLifecycleError(
                    "VOICE-TTS-DONE-BEFORE-COMMIT",
                    "worker emitted DONE before commit_text completed",
                )
            self._done = True
            self.owner._session_done(self)
        elif event.kind == TTSEventKind.STOPPED.value:
            self._stopped = True
            self.owner._session_stopped(self)
        elif event.kind == TTSEventKind.ERROR.value:
            self.owner._session_error(
                self,
                WorkerLifecycleError(event.code or "VOICE-TTS-WORKER-SESSION-ERROR", event.detail),
            )


def _next_sync(iterator: Any) -> Tuple[bool, Any]:
    """Advance a synchronous provider iterator without leaking StopIteration."""
    try:
        return True, next(iterator)
    except StopIteration:
        return False, None


__all__ = [
    "PersistentTTSProvider",
    "StrictIdleGate",
    "WorkerIdleSnapshot",
    "WorkerLifecycleError",
    "WorkerLifecycleState",
    "WorkerProviderFactory",
    "WorkerTTSSession",
]
