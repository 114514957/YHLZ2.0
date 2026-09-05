"""Incremental ASR bridge for the isolated target voice chain.

The bridge begins an ASR session at a VAD speech edge, sends bounded PCM as it
arrives, and emits redacted partial events. Partial text is deliberately not
allowed to enter the wake gate, SessionKernel, reasoner, memory, or telemetry.
Only the final result at a VAD segment boundary can enter ``TargetVoiceChain``.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional

from backend.asr_bridge import ASRError, ASREvent, ASREventKind, TranscriptResult
from backend.asr_provider_port import (
    ASRProviderError,
    ASRStreamUpdate,
    ASRStreamUpdateKind,
    StreamingASRProviderPort,
    is_streaming_asr_provider_port,
)
from backend.media_adapter import ProcessedAudioFrame
from backend.speech_segment import SpeechSegment, SpeechSegmentAssembler
from backend.target_chain import CancellationSignal, PipelineSubmission, TargetVoiceChain


logger = logging.getLogger(__name__)
_SENSITIVE_HEALTH_KEYS = frozenset(
    {"audio", "audio_ref", "content", "input", "raw_audio", "text", "transcript"}
)
_STOP = object()


@dataclass(slots=True)
class _ActiveStream:
    stream_id: str
    generation: int
    signal: CancellationSignal
    opened_at: float
    first_sequence: int
    last_sequence: int
    pushed_frames: int = 0


def _frame_duration_ms(frame: ProcessedAudioFrame) -> int:
    explicit = getattr(frame.frame, "duration_ms", 0)
    try:
        if int(explicit) > 0:
            return int(explicit)
    except (TypeError, ValueError):
        pass
    try:
        samples = frame.samples
        shape = getattr(samples, "shape", None)
        count = int(shape[0]) if shape else len(samples)
        return max(0, int(round(count * 1000 / frame.frame.sample_rate)))
    except Exception:
        return 0


class StreamingASRBridge:
    """Own bounded PCM-to-ASR streaming sessions without retaining transcripts."""

    def __init__(
        self,
        *,
        asr: StreamingASRProviderPort,
        chain: TargetVoiceChain,
        assembler: Optional[SpeechSegmentAssembler] = None,
        queue_capacity: int = 20,
        max_queue_duration_ms: int = 2_000,
        cancel_timeout_s: float = 1.0,
        on_event: Optional[Any] = None,
    ) -> None:
        if not is_streaming_asr_provider_port(asr):
            raise ASRError("ASR streaming provider contract is incomplete")
        if queue_capacity <= 0 or max_queue_duration_ms <= 0 or cancel_timeout_s <= 0:
            raise ValueError("streaming ASR bounds must be positive")
        self.asr = asr
        self.chain = chain
        self.assembler = assembler or SpeechSegmentAssembler()
        self.queue_capacity = int(queue_capacity)
        self.max_queue_duration_ms = int(max_queue_duration_ms)
        self.cancel_timeout_s = float(cancel_timeout_s)
        self.on_event = on_event
        self._lock = threading.RLock()
        self._queue: Optional[asyncio.Queue[Any]] = None
        self._worker_task: Optional[asyncio.Task] = None
        self._active: Optional[_ActiveStream] = None
        self._closed = False
        self._started = False
        self._event_sequence = 0
        self._next_stream = 0
        self._queue_duration_ms = 0
        self._completed = 0
        self._failed = 0
        self._stale = 0
        self._cancelled = 0
        self._partial_updates = 0
        self._backpressure = 0
        self._cancel_stop_confirmed = 0
        self._cancel_stop_timeouts = 0
        self._cancel_stop_failures = 0
        self._last_cancel_stop_status: Optional[str] = None
        self._last_result: Optional[TranscriptResult] = None

    def start(self) -> None:
        """Load the selected provider before capture is opened; never downloads."""
        with self._lock:
            if self._closed:
                raise ASRError("ASR bridge is closed")
            if self._started:
                return
        self.asr.start()
        with self._lock:
            self._started = True

    async def accept_frame(self, frame: ProcessedAudioFrame) -> None:
        """Enqueue one VAD-labelled frame without doing ASR on the media path."""
        with self._lock:
            if self._closed:
                return
            if not self._started:
                raise ASRError("ASR streaming bridge is not started")
        queue = self._ensure_worker()
        duration_ms = _frame_duration_ms(frame)
        overflow = False
        with self._lock:
            if (
                queue.full()
                or self._queue_duration_ms + duration_ms > self.max_queue_duration_ms
            ):
                self._backpressure += 1
                overflow = True
            else:
                queue.put_nowait(frame)
                self._queue_duration_ms += duration_ms
        if not overflow:
            return
        self._emit(
            ASREventKind.ERROR,
            segment_id=self._active.stream_id if self._active else "",
            generation=frame.frame.generation,
            payload={
                "code": "ASR-STREAM-BACKPRESSURE",
                "queue_capacity": self.queue_capacity,
                "queue_duration_capacity_ms": self.max_queue_duration_ms,
            },
        )
        await self._discard_queued_frames()
        await self._abort_active("backpressure")

    async def wait_idle(self) -> None:
        """Wait for accepted work and an active stream to reach a terminal path."""
        queue = self._queue
        if queue is not None:
            await queue.join()
        while True:
            with self._lock:
                active = self._active
                closed = self._closed
            if active is None or closed:
                return
            await asyncio.sleep(0.005)

    async def close(self, reason: str = "shutdown") -> None:
        """Cancel live ASR, drain bridge work, then release the model handle."""
        with self._lock:
            already_closed = self._closed
            self._closed = True
            queue = self._queue
            worker = self._worker_task
        if already_closed:
            return
        await self._discard_queued_frames()
        await self._abort_active(reason)
        if queue is not None:
            queue.put_nowait(_STOP)
        if worker is not None:
            try:
                await worker
            except asyncio.CancelledError:
                pass
        await self._invoke_provider("stop", str(reason or "shutdown")[:160])
        self.assembler.flush(reason)

    def reopen(self) -> None:
        """Reset only temporary stream state after a fully closed runtime."""
        task = self._worker_task
        if not self._closed:
            raise ASRError("ASR bridge must be closed before reopen")
        if task is not None and not task.done():
            raise ASRError("cannot reopen while ASR worker is active")
        with self._lock:
            self._closed = False
            self._started = False
            self._queue = None
            self._worker_task = None
            self._active = None
            self._queue_duration_ms = 0
            self._last_cancel_stop_status = None
        self.assembler.reset(None)

    def snapshot(self) -> dict:
        with self._lock:
            active = self._active
            worker = self._worker_task
            queue = self._queue
            return {
                "closed": self._closed,
                "started": self._started,
                "active_segment_id": active.stream_id if active else None,
                "active_task": bool(worker is not None and not worker.done()),
                "active_stream": active is not None,
                "completed": self._completed,
                "failed": self._failed,
                "stale": self._stale,
                "cancelled": self._cancelled,
                "partial_updates": self._partial_updates,
                "backpressure": self._backpressure,
                "queue_depth": queue.qsize() if queue is not None else 0,
                "queue_capacity": self.queue_capacity,
                "queue_duration_ms": self._queue_duration_ms,
                "queue_duration_capacity_ms": self.max_queue_duration_ms,
                "cancel_stop_confirmed": self._cancel_stop_confirmed,
                "cancel_stop_timeouts": self._cancel_stop_timeouts,
                "cancel_stop_failures": self._cancel_stop_failures,
                "last_cancel_stop_status": self._last_cancel_stop_status,
                "ports": {
                    "asr_cancel_supported": True,
                    "asr_stop_observable": True,
                    "asr_streaming": True,
                },
                "provider": self._provider_health(),
                "last_status": self._last_result.status if self._last_result else None,
                "assembler": self.assembler.snapshot(),
            }

    def _ensure_worker(self) -> asyncio.Queue[Any]:
        with self._lock:
            queue = self._queue
            task = self._worker_task
            if queue is None:
                queue = asyncio.Queue(maxsize=self.queue_capacity)
                self._queue = queue
            if task is None or task.done():
                self._worker_task = asyncio.create_task(self._worker(queue))
            return queue

    async def _worker(self, queue: asyncio.Queue[Any]) -> None:
        while True:
            item = await queue.get()
            try:
                if item is _STOP:
                    return
                if isinstance(item, ProcessedAudioFrame):
                    with self._lock:
                        self._queue_duration_ms = max(
                            0,
                            self._queue_duration_ms - _frame_duration_ms(item),
                        )
                    await self._process_frame(item)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._failed += 1
                generation = item.frame.generation if isinstance(item, ProcessedAudioFrame) else 0
                self._emit(
                    ASREventKind.ERROR,
                    segment_id=self._active.stream_id if self._active else "",
                    generation=generation,
                    payload={"code": _provider_error_code(exc), "detail": type(exc).__name__},
                )
                await self._abort_active("worker_error")
            finally:
                queue.task_done()

    async def _process_frame(self, frame: ProcessedAudioFrame) -> None:
        metadata = frame.frame
        active = self._active
        if active is not None and active.generation != metadata.generation:
            self._stale += 1
            await self._abort_active("generation_replaced")
        was_active = self.assembler.active
        segment = self.assembler.push(frame)
        is_active = self.assembler.active
        if not was_active and is_active:
            frames = self.assembler.active_frames
            await self._open_active_stream(frames)
            return
        if not was_active:
            return
        # A stream that was already open receives every following frame,
        # including the silence frame that closes VAD segmentation.
        await self._push_active_frame(frame)
        if is_active:
            return
        if segment is None:
            await self._abort_active("segment_dropped")
            return
        await self._finish_active_stream(segment)

    async def _open_active_stream(self, frames: tuple[ProcessedAudioFrame, ...]) -> None:
        if not frames:
            return
        first = frames[0].frame
        self._next_stream += 1
        stream_id = "asr_stream_{0}_{1}".format(first.generation, self._next_stream)
        signal = CancellationSignal()

        # ``CancellationSignal`` invokes synchronous callbacks before it
        # returns. That makes the subsequent ``wait_stopped`` observation a
        # real stop check instead of a race with a scheduled coroutine.
        signal.add_cancel_callback(lambda: self.asr.interrupt("stream_cancel"))
        active = _ActiveStream(
            stream_id=stream_id,
            generation=first.generation,
            signal=signal,
            opened_at=time.monotonic(),
            first_sequence=first.sequence,
            last_sequence=first.sequence,
        )
        # Register intent before crossing the thread boundary. ``close`` can
        # then cancel an opening stream rather than racing a provider-owned
        # session which has not reached the bridge yet.
        with self._lock:
            if self._closed:
                return
            self._active = active
        try:
            await self._invoke_provider(
                "open_stream",
                stream_id,
                first.generation,
                first.sample_rate,
                first.channels,
                signal,
            )
        except Exception as exc:
            self._failed += 1
            with self._lock:
                if self._active is active:
                    self._active = None
            self.assembler.reset(first.generation)
            self._emit(
                ASREventKind.ERROR,
                segment_id=stream_id,
                generation=first.generation,
                payload={"code": _provider_error_code(exc), "detail": type(exc).__name__},
            )
            return
        # A synchronous cancellation can happen while ``open_stream`` runs
        # in its worker thread. The first interrupt may have happened before
        # the native stream existed, so perform a final stop after opening
        # and do not allow an unowned native session to continue.
        if self._closed or active.signal.is_cancelled() or self._active is not active:
            try:
                await self._invoke_provider("interrupt", "stream_open_cancelled")
                await self._wait_provider_stopped(self.cancel_timeout_s)
            except Exception:
                logger.exception("failed to stop ASR stream opened during close")
            return
        self._emit(
            ASREventKind.STARTED,
            segment_id=stream_id,
            generation=first.generation,
            payload={
                "first_sequence": first.sequence,
                "preroll_and_initial_frames": len(frames),
            },
        )
        for item in frames:
            if self._active is not active:
                return
            await self._push_active_frame(item)

    async def _push_active_frame(self, frame: ProcessedAudioFrame) -> None:
        active = self._active
        if active is None:
            return
        if frame.frame.generation != active.generation:
            self._stale += 1
            await self._abort_active("generation_mismatch")
            return
        active.last_sequence = frame.frame.sequence
        try:
            raw_updates = await self._invoke_provider(
                "push_audio",
                active.stream_id,
                frame.samples,
                frame.frame.sample_rate,
                active.signal,
            )
        except Exception as exc:
            self._failed += 1
            self._emit(
                ASREventKind.ERROR,
                segment_id=active.stream_id,
                generation=active.generation,
                payload={"code": _provider_error_code(exc), "detail": type(exc).__name__},
            )
            await self._abort_active("provider_push_error")
            return
        active.pushed_frames += 1
        for update in tuple(raw_updates or ()):
            if not isinstance(update, ASRStreamUpdate):
                self._failed += 1
                self._emit(
                    ASREventKind.ERROR,
                    segment_id=active.stream_id,
                    generation=active.generation,
                    payload={"code": "ASR-STREAM-UPDATE-INVALID"},
                )
                await self._abort_active("invalid_update")
                return
            if update.stream_id != active.stream_id or update.generation != active.generation:
                self._stale += 1
                continue
            if update.kind is ASRStreamUpdateKind.PARTIAL:
                self._partial_updates += 1
                self._emit(
                    ASREventKind.PARTIAL,
                    segment_id=active.stream_id,
                    generation=active.generation,
                    payload={"text_length": len(update.text), "elapsed_ms": update.elapsed_ms},
                )
                continue
            if update.kind is ASRStreamUpdateKind.CANCELLED:
                await self._abort_active("provider_cancelled")
                return
            self._failed += 1
            self._emit(
                ASREventKind.ERROR,
                segment_id=active.stream_id,
                generation=active.generation,
                payload={"code": "ASR-STREAM-UPDATE-UNEXPECTED"},
            )
            await self._abort_active("unexpected_update")
            return

    async def _finish_active_stream(self, segment: SpeechSegment) -> None:
        active = self._active
        if active is None:
            return
        try:
            update = await self._invoke_provider("finish_stream", active.stream_id, active.signal)
        except Exception as exc:
            self._failed += 1
            self._emit(
                ASREventKind.ERROR,
                segment_id=segment.segment_id,
                generation=segment.generation,
                payload={"code": _provider_error_code(exc), "detail": type(exc).__name__},
            )
            await self._abort_active("provider_finish_error")
            return
        self._active = None
        active.signal.mark_done()
        if not isinstance(update, ASRStreamUpdate):
            self._failed += 1
            self._emit(
                ASREventKind.ERROR,
                segment_id=segment.segment_id,
                generation=segment.generation,
                payload={"code": "ASR-STREAM-FINAL-INVALID"},
            )
            return
        if update.stream_id != active.stream_id or update.generation != active.generation:
            self._stale += 1
            self._emit(ASREventKind.STALE, segment.segment_id, segment.generation)
            return
        if update.kind is ASRStreamUpdateKind.CANCELLED:
            self._cancelled += 1
            self._emit(ASREventKind.CANCELLED, segment.segment_id, segment.generation)
            return
        if update.kind is ASRStreamUpdateKind.EMPTY or not update.text.strip():
            result = TranscriptResult(segment.segment_id, segment.generation, "", "empty")
            self._last_result = result
            self._emit(ASREventKind.EMPTY, segment.segment_id, segment.generation)
            return
        if update.kind is not ASRStreamUpdateKind.FINAL:
            self._failed += 1
            self._emit(
                ASREventKind.ERROR,
                segment_id=segment.segment_id,
                generation=segment.generation,
                payload={"code": "ASR-STREAM-FINAL-UNEXPECTED"},
            )
            return
        if self._closed or active.signal.is_cancelled():
            self._stale += 1
            self._emit(ASREventKind.STALE, segment.segment_id, segment.generation)
            return
        submission = await self.chain.submit_transcript(update.text, source="microphone")
        result = TranscriptResult(
            segment.segment_id,
            segment.generation,
            update.text,
            "completed",
            submission=submission,
        )
        self._completed += 1
        self._last_result = result
        self._emit(
            ASREventKind.COMPLETED,
            segment_id=segment.segment_id,
            generation=segment.generation,
            payload={
                "text_length": len(update.text),
                "elapsed_ms": update.elapsed_ms,
                "gate_event": submission.decision.event.value,
            },
            turn_id=submission.lease.turn_id if submission.lease else None,
            trace_id=submission.lease.trace_id if submission.lease else "",
        )

    async def _abort_active(self, reason: str) -> bool:
        active = self._active
        if active is None:
            return True
        self._active = None
        active.signal.cancel(reason)
        try:
            confirmed = await self._wait_provider_stopped(self.cancel_timeout_s)
        except Exception as exc:
            self._cancel_stop_failures += 1
            self._last_cancel_stop_status = "failed"
            self._failed += 1
            self._emit(
                ASREventKind.ERROR,
                segment_id=active.stream_id,
                generation=active.generation,
                payload={"code": "ASR-CANCEL-FAILED", "detail": type(exc).__name__},
            )
            active.signal.mark_done()
            return False
        active.signal.mark_done()
        if confirmed:
            self._cancel_stop_confirmed += 1
            self._last_cancel_stop_status = "confirmed"
            self._cancelled += 1
            self._emit(ASREventKind.CANCELLED, active.stream_id, active.generation)
            return True
        self._cancel_stop_timeouts += 1
        self._last_cancel_stop_status = "timeout"
        self._failed += 1
        self._emit(
            ASREventKind.ERROR,
            segment_id=active.stream_id,
            generation=active.generation,
            payload={"code": "ASR-CANCEL-TIMEOUT"},
        )
        return False

    async def _wait_provider_stopped(self, timeout_s: float) -> bool:
        method = getattr(self.asr, "wait_stopped", None)
        if not callable(method):
            raise ASRError("ASR provider has no wait_stopped")
        value = await asyncio.to_thread(method, timeout_s)
        if inspect.isawaitable(value):
            value = await value
        return bool(value)

    async def _invoke_provider(self, name: str, *args: Any) -> Any:
        method = getattr(self.asr, name, None)
        if not callable(method):
            raise ASRError("ASR provider is missing " + name)
        value = await asyncio.to_thread(method, *args)
        if inspect.isawaitable(value):
            return await value
        return value

    async def _discard_queued_frames(self) -> None:
        queue = self._queue
        if queue is None:
            return
        while True:
            try:
                item = queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            else:
                if isinstance(item, ProcessedAudioFrame):
                    with self._lock:
                        self._queue_duration_ms = max(
                            0,
                            self._queue_duration_ms - _frame_duration_ms(item),
                        )
                queue.task_done()

    def _provider_health(self) -> dict:
        try:
            value = self.asr.health()
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

    def _emit(
        self,
        kind: ASREventKind,
        segment_id: str,
        generation: int,
        payload: Optional[Dict[str, Any]] = None,
        turn_id: Optional[str] = None,
        trace_id: str = "",
    ) -> None:
        self._event_sequence += 1
        event = ASREvent(
            kind=kind.value,
            event_seq=self._event_sequence,
            segment_id=str(segment_id)[:160],
            generation=int(generation),
            payload=dict(payload or {}),
            turn_id=turn_id,
            trace_id=str(trace_id)[:160],
        )
        handler = self.on_event
        if handler is not None:
            try:
                handler(event)
            except Exception:
                logger.exception("ASR event handler failed for %s", kind.value)


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
        if code and all(item.isupper() or item.isdigit() or item in "_-" for item in code):
            return code
    if isinstance(exc, ASRProviderError):
        return exc.code
    return "ASR-STREAM-ERROR"


__all__ = ["StreamingASRBridge"]
