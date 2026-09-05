"""Cancellable, provider-neutral ASR bridge for the target voice chain."""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Mapping, Optional, Protocol

from backend.speech_segment import SpeechSegment, SpeechSegmentAssembler
from backend.target_chain import CancellationSignal, PipelineSubmission, TargetVoiceChain


logger = logging.getLogger(__name__)


class ASRError(RuntimeError):
    """Raised when an ASR adapter violates the bridge contract."""


class ASREventKind(str, Enum):
    STARTED = "ASR_STARTED"
    PARTIAL = "ASR_PARTIAL"
    COMPLETED = "ASR_COMPLETED"
    EMPTY = "ASR_EMPTY"
    STALE = "ASR_STALE"
    CANCELLED = "ASR_CANCELLED"
    ERROR = "ASR_ERROR"


@dataclass(frozen=True, slots=True)
class TranscriptResult:
    segment_id: str
    generation: int
    text: str
    status: str
    submission: Optional[PipelineSubmission] = None
    error_code: Optional[str] = None


@dataclass(frozen=True, slots=True)
class ASREvent:
    kind: str
    event_seq: int
    segment_id: str
    generation: int
    payload: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    # ASR starts before a turn exists, so these remain empty for STARTED,
    # EMPTY, and failure events.  A completed submission carries the exact
    # Kernel lease that accepted the transcript.
    turn_id: Optional[str] = None
    trace_id: str = ""


class ASRPort(Protocol):
    """ASR adapter contract; concrete adapters may be local or remote."""

    def transcribe(self, segment: SpeechSegment, signal: CancellationSignal) -> Any: ...


class ASRStopObserver(Protocol):
    """Optional physical-stop evidence for serial ASR provider adapters."""

    def wait_stopped(self, timeout_s: float) -> Any: ...


class ASRBridge:
    """Turn one VAD segment into one guarded TargetVoiceChain submission."""

    def __init__(
        self,
        *,
        asr: ASRPort,
        chain: TargetVoiceChain,
        assembler: Optional[SpeechSegmentAssembler] = None,
        timeout_s: float = 30.0,
        cancel_timeout_s: float = 1.0,
        on_event: Optional[Any] = None,
    ) -> None:
        if timeout_s <= 0 or cancel_timeout_s <= 0:
            raise ValueError("ASR timeouts must be positive")
        self.asr = asr
        self.chain = chain
        self.assembler = assembler or SpeechSegmentAssembler()
        self.timeout_s = float(timeout_s)
        self.cancel_timeout_s = float(cancel_timeout_s)
        self.on_event = on_event
        self._lock = asyncio.Lock()
        self._active_task: Optional[asyncio.Task] = None
        self._active_signal: Optional[CancellationSignal] = None
        self._active_segment_id: Optional[str] = None
        self._active_segment: Optional[SpeechSegment] = None
        self._event_sequence = 0
        self._closed = False
        self._completed = 0
        self._failed = 0
        self._stale = 0
        self._cancelled = 0
        self._timeouts = 0
        self._cancel_stop_confirmed = 0
        self._cancel_stop_timeouts = 0
        self._cancel_stop_failures = 0
        self._last_cancel_stop_status: Optional[str] = None
        self._cancel_stop_statuses: Dict[int, str] = {}
        self._last_result: Optional[TranscriptResult] = None

    async def accept_frame(self, frame: Any) -> Optional[asyncio.Task]:
        """Feed one ``ProcessedAudioFrame`` and schedule ASR on segment close."""
        if self._closed:
            return None
        segment = self.assembler.push(frame)
        if segment is None:
            return None
        return await self.submit_segment(segment)

    async def submit_segment(self, segment: SpeechSegment) -> asyncio.Task:
        """Supersede an unfinished ASR request and schedule this segment."""
        async with self._lock:
            if self._closed:
                raise ASRError("ASR bridge is closed")
            old_task = self._active_task
            old_signal = self._active_signal
            if old_task is not None and not old_task.done():
                if not await self._cancel_active_locked(old_task, old_signal):
                    raise ASRError("previous ASR request did not confirm physical stop")

            signal = self._new_signal()
            task = asyncio.create_task(self._run_segment(segment, signal))
            signal.bind_task(task)
            self._active_task = task
            self._active_signal = signal
            self._active_segment_id = segment.segment_id
            self._active_segment = segment
            return task

    async def close(self, reason: str = "shutdown") -> None:
        async with self._lock:
            self._closed = True
            task = self._active_task
            signal = self._active_signal
            if task is not None and not task.done():
                await self._cancel_active_locked(task, signal)
            self._active_task = None
            self._active_signal = None
            self._active_segment_id = None
            self._active_segment = None
        self.assembler.flush(reason)

    def reopen(self) -> None:
        """Re-arm the bridge after ``close`` without touching stored data."""
        task = self._active_task
        if not self._closed:
            raise ASRError("ASR bridge must be closed before reopen")
        if task is not None and not task.done():
            raise ASRError("cannot reopen while an ASR task is still active")
        self._active_task = None
        self._active_signal = None
        self._active_segment_id = None
        self._active_segment = None
        self._cancel_stop_statuses.clear()
        self._closed = False
        self.assembler.reset(None)

    async def wait_idle(self) -> None:
        """Wait for the currently owned ASR task, if any, to finish."""
        task = self._active_task
        if task is None:
            return
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            # Cancellation is a terminal disposition for the request.
            return

    def snapshot(self) -> dict:
        task = self._active_task
        return {
            "closed": self._closed,
            "active_segment_id": self._active_segment_id,
            "active_task": bool(task is not None and not task.done()),
            "completed": self._completed,
            "failed": self._failed,
            "stale": self._stale,
            "cancelled": self._cancelled,
            "timeouts": self._timeouts,
            "cancel_stop_confirmed": self._cancel_stop_confirmed,
            "cancel_stop_timeouts": self._cancel_stop_timeouts,
            "cancel_stop_failures": self._cancel_stop_failures,
            "last_cancel_stop_status": self._last_cancel_stop_status,
            "ports": {
                "asr_cancel_supported": self._asr_cancel_callback() is not None,
                "asr_stop_observable": self._asr_stop_waiter() is not None,
            },
            "provider": self._provider_health(),
            "last_status": self._last_result.status if self._last_result else None,
            "assembler": self.assembler.snapshot(),
        }

    async def _run_segment(
        self,
        segment: SpeechSegment,
        signal: CancellationSignal,
    ) -> TranscriptResult:
        self._emit(ASREventKind.STARTED, segment, payload={"frame_count": segment.frame_count})
        try:
            raw = await asyncio.wait_for(
                self._call_asr(segment, signal),
                timeout=self.timeout_s,
            )
            if signal.is_cancelled() or not self._is_current_task(segment.segment_id, segment.generation):
                self._stale += 1
                result = TranscriptResult(segment.segment_id, segment.generation, "", "stale")
                self._emit(ASREventKind.STALE, segment)
                return result
            text = self._extract_text(raw)
            if not text:
                self._emit(ASREventKind.EMPTY, segment)
                result = TranscriptResult(segment.segment_id, segment.generation, "", "empty")
                self._last_result = result
                return result
            submission = await self.chain.submit_transcript(text, source="microphone")
            result = TranscriptResult(
                segment.segment_id,
                segment.generation,
                text,
                "completed",
                submission=submission,
            )
            self._completed += 1
            self._last_result = result
            self._emit(
                ASREventKind.COMPLETED,
                segment,
                payload={"text_length": len(text), "gate_event": submission.decision.event.value},
                turn_id=submission.lease.turn_id if submission.lease else None,
                trace_id=submission.lease.trace_id if submission.lease else "",
            )
            return result
        except asyncio.TimeoutError:
            signal.cancel()
            self._failed += 1
            self._timeouts += 1
            result = TranscriptResult(
                segment.segment_id,
                segment.generation,
                "",
                "failed",
                error_code="ASR-TIMEOUT",
            )
            self._last_result = result
            self._emit(ASREventKind.ERROR, segment, payload={"code": "ASR-TIMEOUT"})
            return result
        except asyncio.CancelledError:
            self._stale += 1
            self._cancelled += 1
            self._emit(ASREventKind.CANCELLED, segment)
            raise
        except Exception as exc:
            error_code = _provider_error_code(exc)
            self._failed += 1
            result = TranscriptResult(
                segment.segment_id,
                segment.generation,
                "",
                "failed",
                error_code=error_code,
            )
            self._last_result = result
            self._emit(
                ASREventKind.ERROR,
                segment,
                payload={"code": error_code, "detail": type(exc).__name__},
            )
            return result
        finally:
            signal.mark_done()
            await self._confirm_cancel_stop(segment, signal)
            if self._active_segment_id == segment.segment_id:
                self._active_task = None
                self._active_signal = None
                self._active_segment_id = None
                self._active_segment = None

    async def _call_asr(self, segment: SpeechSegment, signal: CancellationSignal) -> Any:
        method = getattr(self.asr, "transcribe", None)
        if method is None or not callable(method):
            raise ASRError("ASR adapter must provide transcribe(segment, signal)")
        if inspect.iscoroutinefunction(method):
            return await method(segment, signal)
        value = await asyncio.to_thread(method, segment, signal)
        if inspect.isawaitable(value):
            return await value
        return value

    def _new_signal(self) -> CancellationSignal:
        signal = CancellationSignal()
        cancel_callback = self._asr_cancel_callback()
        if cancel_callback is not None:
            signal.add_cancel_callback(cancel_callback)
        stop_waiter = self._asr_stop_waiter()
        if stop_waiter is not None:
            signal.add_terminal_waiter(stop_waiter)
        return signal

    async def _cancel_active_locked(
        self,
        task: asyncio.Task,
        signal: Optional[CancellationSignal],
    ) -> bool:
        """Cancel one ASR request and refuse overlap after an unconfirmed stop."""
        if signal is not None:
            signal.cancel()
        elif not task.done():
            task.cancel()
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=self.cancel_timeout_s)
        except asyncio.CancelledError:
            # The worker has reached its cancellation terminal path. Its
            # finally block recorded optional physical-stop evidence first.
            pass
        except asyncio.TimeoutError:
            self._record_cancel_stop(signal, self._active_segment, "timeout")
            return False
        except Exception:
            # Provider failures are already emitted by _run_segment. A
            # physical-stop observer, if any, still decides overlap safety.
            pass
        if signal is None:
            return True
        status = self._cancel_stop_statuses.pop(id(signal), None)
        return status not in {"timeout", "failed"}

    async def _confirm_cancel_stop(
        self,
        segment: SpeechSegment,
        signal: CancellationSignal,
    ) -> None:
        """Record optional ASR physical-stop evidence after task termination."""
        if not signal.is_cancelled() or self._asr_stop_waiter() is None:
            return
        try:
            confirmed = await signal.wait_terminal(self.cancel_timeout_s)
        except Exception as exc:
            self._record_cancel_stop(signal, segment, "failed", type(exc).__name__)
            return
        self._record_cancel_stop(
            signal,
            segment,
            "confirmed" if confirmed else "timeout",
        )

    def _record_cancel_stop(
        self,
        signal: Optional[CancellationSignal],
        segment: Optional[SpeechSegment],
        status: str,
        detail: str = "",
    ) -> None:
        """Keep one terminal physical-stop disposition per cancellation."""
        key = id(signal) if signal is not None else 0
        if key and key in self._cancel_stop_statuses:
            return
        if key:
            self._cancel_stop_statuses[key] = status
        self._last_cancel_stop_status = status
        if status == "confirmed":
            self._cancel_stop_confirmed += 1
            return
        if status == "timeout":
            self._cancel_stop_timeouts += 1
            code = "ASR-CANCEL-TIMEOUT"
        else:
            self._cancel_stop_failures += 1
            code = "ASR-CANCEL-FAILED"
        if segment is not None:
            self._emit(
                ASREventKind.ERROR,
                segment,
                payload={"code": code, "detail": detail} if detail else {"code": code},
            )

    def _asr_cancel_callback(self) -> Optional[Any]:
        for name in ("interrupt", "stop", "cancel"):
            method = getattr(self.asr, name, None)
            if callable(method):
                return method
        return None

    def _asr_stop_waiter(self) -> Optional[Any]:
        method = getattr(self.asr, "wait_stopped", None)
        return method if callable(method) else None

    def _provider_health(self) -> dict:
        method = getattr(self.asr, "health", None)
        if not callable(method):
            return {"available": None, "state": "unknown"}
        try:
            value = method()
        except Exception as exc:
            return {
                "available": False,
                "state": "health_error",
                "last_error_code": "ASR-HEALTH-FAILED",
                "detail": type(exc).__name__,
            }
        if not isinstance(value, Mapping):
            return {
                "available": False,
                "state": "health_invalid",
                "last_error_code": "ASR-HEALTH-INVALID",
            }
        return _safe_health_value(dict(value))

    @staticmethod
    def _extract_text(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, Mapping):
            return str(value.get("text", "") or "").strip()
        return str(getattr(value, "text", value) or "").strip()

    def _is_current_task(self, segment_id: str, generation: int) -> bool:
        current_generation = self.assembler.generation
        return (
            self._active_segment_id == segment_id
            and self._active_task is asyncio.current_task()
            and not self._closed
            and current_generation == generation
        )

    def _emit(
        self,
        kind: ASREventKind,
        segment: SpeechSegment,
        *,
        payload: Optional[Dict[str, Any]] = None,
        turn_id: Optional[str] = None,
        trace_id: str = "",
    ) -> None:
        self._event_sequence += 1
        event = ASREvent(
            kind=kind.value,
            event_seq=self._event_sequence,
            segment_id=segment.segment_id,
            generation=segment.generation,
            payload=dict(payload or {}),
            turn_id=turn_id,
            trace_id=trace_id,
        )
        handler = self.on_event
        if handler is not None:
            try:
                handler(event)
            except Exception:
                logger.exception("ASR event handler failed for %s", kind.value)


_SENSITIVE_HEALTH_KEYS = frozenset(
    {"audio", "audio_ref", "content", "input", "raw_audio", "text", "transcript"}
)


def _safe_health_value(value: Any, key: str = "") -> Any:
    if key.lower() in _SENSITIVE_HEALTH_KEYS:
        return "[redacted]"
    if isinstance(value, Mapping):
        return {str(name): _safe_health_value(item, str(name)) for name, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe_health_value(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)[:160]


def _provider_error_code(exc: Exception) -> str:
    candidate = getattr(exc, "code", None)
    if isinstance(candidate, str):
        code = candidate.strip()[:160]
        if code and all(char.isupper() or char.isdigit() or char in "_-" for char in code):
            return code
    return "ASR-ERROR"


__all__ = [
    "ASRError",
    "ASREvent",
    "ASREventKind",
    "ASRBridge",
    "ASRPort",
    "ASRStopObserver",
    "TranscriptResult",
]
