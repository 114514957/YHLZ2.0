"""In-memory VAD frame assembly for the target voice chain.

This module deliberately stops at a bounded ``SpeechSegment``.  ASR, wake-word
decisions, and Session Kernel turns are downstream responsibilities.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Deque, Dict, Optional, Tuple

from backend.media_adapter import ProcessedAudioFrame


logger = logging.getLogger(__name__)


def _frame_duration_ms(item: ProcessedAudioFrame) -> int:
    """Use the capture clock first, with a conservative PCM fallback."""
    explicit = getattr(item.frame, "duration_ms", 0)
    try:
        if explicit and int(explicit) > 0:
            return int(explicit)
    except (TypeError, ValueError):
        pass
    try:
        samples = item.samples
        if isinstance(samples, (bytes, bytearray, memoryview)):
            sample_count = len(samples) // 2 // max(item.frame.channels, 1)
        else:
            shape = getattr(samples, "shape", None)
            sample_count = int(shape[0]) if shape else len(samples)
        return max(0, int(sample_count * 1000 / item.frame.sample_rate))
    except Exception:
        return 0


class SegmentEventKind(str, Enum):
    OPENED = "SEGMENT_OPENED"
    EMITTED = "SEGMENT_EMITTED"
    DROPPED = "SEGMENT_DROPPED"
    STALE = "SEGMENT_STALE_FRAME"
    RESET = "SEGMENT_GENERATION_RESET"
    ERROR = "SEGMENT_ERROR"


@dataclass(frozen=True, slots=True)
class SpeechSegment:
    """An immutable sequence of frames belonging to one VAD candidate."""

    segment_id: str
    generation: int
    first_sequence: int
    last_sequence: int
    sample_rate: int
    channels: int
    frames: Tuple[ProcessedAudioFrame, ...]
    reason: str
    created_at: float = field(default_factory=time.time)

    @property
    def frame_count(self) -> int:
        return len(self.frames)

    @property
    def duration_ms(self) -> int:
        return sum(_frame_duration_ms(item) for item in self.frames)

    @property
    def samples(self) -> Tuple[Any, ...]:
        """Return frame payloads without coercing provider-specific formats."""
        return tuple(item.samples for item in self.frames)


@dataclass(frozen=True, slots=True)
class SegmentEvent:
    kind: str
    event_seq: int
    generation: int
    first_sequence: int = 0
    last_sequence: int = 0
    payload: Dict[str, Any] = field(default_factory=dict)


EventHandler = Callable[[SegmentEvent], Any]


class SpeechSegmentAssembler:
    """Assemble VAD-labelled frames with pre-roll and explicit end policy."""

    def __init__(
        self,
        *,
        preroll_frames: int = 3,
        end_silence_frames: int = 1,
        max_frames: int = 100,
        min_frames: int = 1,
        max_duration_ms: int = 10_000,
        min_duration_ms: int = 0,
        on_event: Optional[EventHandler] = None,
    ) -> None:
        if preroll_frames < 0:
            raise ValueError("preroll_frames must not be negative")
        if end_silence_frames <= 0 or max_frames <= 0 or min_frames <= 0:
            raise ValueError("segment frame limits must be positive")
        if min_frames > max_frames:
            raise ValueError("min_frames must not exceed max_frames")
        if max_duration_ms <= 0 or min_duration_ms < 0:
            raise ValueError("segment duration limits are invalid")
        if min_duration_ms > max_duration_ms:
            raise ValueError("min_duration_ms must not exceed max_duration_ms")
        self.preroll_frames = preroll_frames
        self.end_silence_frames = end_silence_frames
        self.max_frames = max_frames
        self.min_frames = min_frames
        self.max_duration_ms = int(max_duration_ms)
        self.min_duration_ms = int(min_duration_ms)
        self.on_event = on_event
        self._lock = threading.RLock()
        self._generation: Optional[int] = None
        self._last_sequence = 0
        self._sample_rate: Optional[int] = None
        self._channels: Optional[int] = None
        self._preroll: Deque[ProcessedAudioFrame] = deque(maxlen=preroll_frames or 1)
        self._active: list[ProcessedAudioFrame] = []
        self._silence_frames = 0
        self._segment_number = 0
        self._event_sequence = 0

    @property
    def generation(self) -> Optional[int]:
        with self._lock:
            return self._generation

    @property
    def active(self) -> bool:
        with self._lock:
            return bool(self._active)

    @property
    def active_frames(self) -> Tuple[ProcessedAudioFrame, ...]:
        """Expose the bounded in-memory active span for a streaming consumer.

        This returns references only and never persists PCM. It is used when a
        VAD edge first opens a live ASR stream so that configured pre-roll is
        delivered before subsequent real-time frames.
        """
        with self._lock:
            return tuple(self._active)

    def push(self, frame: ProcessedAudioFrame) -> Optional[SpeechSegment]:
        """Accept one processed frame and return a segment only on close."""
        metadata = frame.frame
        with self._lock:
            if self._generation is None:
                self._generation = metadata.generation
            elif metadata.generation < self._generation:
                self._emit_locked(
                    SegmentEventKind.STALE,
                    metadata.generation,
                    metadata.sequence,
                    metadata.sequence,
                    {"reason": "older_generation"},
                )
                return None
            elif metadata.generation > self._generation:
                self._reset_locked(metadata.generation)
                self._emit_locked(
                    SegmentEventKind.RESET,
                    metadata.generation,
                    metadata.sequence,
                    metadata.sequence,
                    {"reason": "new_generation"},
                )
            if metadata.sequence <= self._last_sequence:
                self._emit_locked(
                    SegmentEventKind.STALE,
                    metadata.generation,
                    metadata.sequence,
                    metadata.sequence,
                    {"reason": "sequence_not_monotonic"},
                )
                return None
            self._last_sequence = metadata.sequence
            if frame.speech is None:
                self._emit_locked(
                    SegmentEventKind.ERROR,
                    metadata.generation,
                    metadata.sequence,
                    metadata.sequence,
                    {"code": "SEGMENT-VAD-UNAVAILABLE"},
                )
                return None
            if self._sample_rate is None:
                self._sample_rate = metadata.sample_rate
                self._channels = metadata.channels
            elif (
                metadata.sample_rate != self._sample_rate
                or metadata.channels != self._channels
            ):
                self._emit_locked(
                    SegmentEventKind.ERROR,
                    metadata.generation,
                    metadata.sequence,
                    metadata.sequence,
                    {"code": "SEGMENT-FORMAT-CHANGED"},
                )
                self._reset_locked(metadata.generation)
                return None

            if frame.speech:
                if not self._active:
                    self._active = list(self._preroll)
                    self._active.append(frame)
                    self._silence_frames = 0
                    self._emit_locked(
                        SegmentEventKind.OPENED,
                        metadata.generation,
                        self._active[0].frame.sequence,
                        metadata.sequence,
                        {"preroll_frames": max(0, len(self._active) - 1)},
                    )
                else:
                    self._active.append(frame)
                    self._silence_frames = 0
            elif self._active:
                self._active.append(frame)
                self._silence_frames += 1
            else:
                if self.preroll_frames:
                    self._preroll.append(frame)
                return None

            if not self._active:
                return None
            if self._active_duration_ms_locked() >= self.max_duration_ms:
                return self._close_locked("max_duration")
            if len(self._active) >= self.max_frames:
                return self._close_locked("max_frames")
            if self._silence_frames >= self.end_silence_frames:
                return self._close_locked("vad_end")
            return None

    def flush(self, reason: str = "flush") -> Optional[SpeechSegment]:
        with self._lock:
            if not self._active:
                return None
            return self._close_locked(reason)

    def reset(self, generation: Optional[int] = None) -> None:
        with self._lock:
            self._reset_locked(generation)

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "generation": self._generation,
                "active": bool(self._active),
                "active_frames": len(self._active),
                "active_duration_ms": self._active_duration_ms_locked(),
                "preroll_frames": len(self._preroll) if self.preroll_frames else 0,
                "max_duration_ms": self.max_duration_ms,
                "min_duration_ms": self.min_duration_ms,
                "sample_rate": self._sample_rate,
                "channels": self._channels,
                "last_sequence": self._last_sequence,
                "next_segment": self._segment_number + 1,
            }

    def _close_locked(self, reason: str) -> Optional[SpeechSegment]:
        frames = tuple(self._active)
        generation = self._generation if self._generation is not None else 0
        self._active = []
        self._silence_frames = 0
        self._preroll.clear()
        duration_ms = sum(_frame_duration_ms(item) for item in frames)
        if len(frames) < self.min_frames or duration_ms < self.min_duration_ms:
            self._emit_locked(
                SegmentEventKind.DROPPED,
                generation,
                frames[0].frame.sequence if frames else 0,
                frames[-1].frame.sequence if frames else 0,
                {
                    "reason": "too_short",
                    "frame_count": len(frames),
                    "duration_ms": duration_ms,
                },
            )
            return None
        self._segment_number += 1
        segment = SpeechSegment(
            segment_id="segment_" + str(self._segment_number),
            generation=generation,
            first_sequence=frames[0].frame.sequence,
            last_sequence=frames[-1].frame.sequence,
            sample_rate=frames[0].frame.sample_rate,
            channels=frames[0].frame.channels,
            frames=frames,
            reason=reason,
        )
        self._emit_locked(
            SegmentEventKind.EMITTED,
            generation,
            segment.first_sequence,
            segment.last_sequence,
            {
                "segment_id": segment.segment_id,
                "reason": reason,
                "frame_count": segment.frame_count,
                "duration_ms": segment.duration_ms,
            },
        )
        return segment

    def _active_duration_ms_locked(self) -> int:
        return sum(_frame_duration_ms(item) for item in self._active)

    def _reset_locked(self, generation: Optional[int]) -> None:
        self._generation = generation
        self._last_sequence = 0
        self._sample_rate = None
        self._channels = None
        self._preroll.clear()
        self._active = []
        self._silence_frames = 0

    def _emit_locked(
        self,
        kind: SegmentEventKind,
        generation: int,
        first_sequence: int,
        last_sequence: int,
        payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._event_sequence += 1
        event = SegmentEvent(
            kind=kind.value,
            event_seq=self._event_sequence,
            generation=generation,
            first_sequence=first_sequence,
            last_sequence=last_sequence,
            payload=dict(payload or {}),
        )
        handler = self.on_event
        if handler is not None:
            try:
                handler(event)
            except Exception:
                logger.exception("segment event handler failed for %s", kind.value)


__all__ = [
    "SegmentEvent",
    "SegmentEventKind",
    "SpeechSegment",
    "SpeechSegmentAssembler",
]
