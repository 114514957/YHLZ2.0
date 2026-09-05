"""Bounded physical playback port for the target voice chain.

The port accepts only the target chain's 24 kHz mono ``pcm_s16le`` audio.  It
uses one persistent sounddevice output callback and never reads or writes the
legacy audio buffer, a sound cache, business data, or memory.
"""

from __future__ import annotations

import asyncio
import queue
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Deque, Dict, Mapping, Optional

import numpy as np

from backend.tts_provider_port import TTSProviderPortError


class PlaybackError(TTSProviderPortError):
    """Stable fail-closed error emitted by the target playback port."""


class PlaybackState(str, Enum):
    STOPPED = "stopped"
    READY = "ready"
    PLAYING = "playing"
    FAILED = "failed"


class PlaybackEventKind(str, Enum):
    READY = "PLAYBACK_READY"
    STARTED = "PLAYBACK_STARTED"
    DONE = "PLAYBACK_DONE"
    STOPPED = "PLAYBACK_STOPPED"
    ERROR = "PLAYBACK_ERROR"
    UNDERRUN = "PLAYBACK_UNDERRUN"


@dataclass(frozen=True, slots=True)
class PlaybackConfig:
    """Explicit selected-output settings for one persistent stream."""

    device: int | str
    sample_rate: int = 24_000
    channels: int = 2
    block_duration_ms: int = 20
    initial_buffer_ms: int = 300
    max_queue_blocks: int = 32
    max_queue_duration_ms: int = 5_000
    enqueue_timeout_s: float = 5.0
    stop_timeout_s: float = 3.0
    volume: float = 1.0

    def __post_init__(self) -> None:
        if self.sample_rate <= 0 or self.channels <= 0:
            raise ValueError("sample_rate and channels must be positive")
        if self.block_duration_ms <= 0 or self.initial_buffer_ms < 0:
            raise ValueError("playback durations are invalid")
        if self.max_queue_blocks <= 0 or self.max_queue_duration_ms <= 0:
            raise ValueError("queue limits must be positive")
        if self.enqueue_timeout_s <= 0 or self.stop_timeout_s <= 0:
            raise ValueError("timeouts must be positive")
        if not 0 < float(self.volume) <= 1.0:
            raise ValueError("volume must be in (0, 1]")
        block_frames = self.block_frames
        if block_frames <= 0:
            raise ValueError("block_duration_ms does not produce a positive frame count")

    @property
    def block_frames(self) -> int:
        return max(1, int(round(self.sample_rate * self.block_duration_ms / 1000)))

    def to_dict(self) -> dict:
        return {
            "device": self.device,
            "sample_rate": self.sample_rate,
            "channels": self.channels,
            "block_duration_ms": self.block_duration_ms,
            "initial_buffer_ms": self.initial_buffer_ms,
            "max_queue_blocks": self.max_queue_blocks,
            "max_queue_duration_ms": self.max_queue_duration_ms,
            "enqueue_timeout_s": self.enqueue_timeout_s,
            "stop_timeout_s": self.stop_timeout_s,
            "volume": self.volume,
        }


@dataclass(frozen=True, slots=True)
class PlaybackEvent:
    """Operational event that intentionally excludes raw PCM and text."""

    kind: str
    code: Optional[str]
    event_seq: int
    generation: int
    sequence: int = 0
    payload: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


@dataclass(slots=True)
class _TurnSlot:
    generation: int
    turn_id: str
    done_event: threading.Event = field(default_factory=threading.Event)
    stopped_event: threading.Event = field(default_factory=threading.Event)
    finish_requested: bool = False
    cancelled: bool = False
    normal_completed: bool = False
    started_at: Optional[float] = None


class SoundDevicePlaybackPort:
    """A cancellable, persistent 24 kHz playback adapter.

    The stream callback only consumes prepared float32 blocks and fills silence.
    It never performs model work, device discovery, disk IO, or business-state
    mutation.  ``start()`` is explicit to keep device access out of composition
    construction and unit tests.
    """

    def __init__(
        self,
        config: PlaybackConfig,
        *,
        sounddevice_module: Any = None,
        on_event: Optional[Callable[[PlaybackEvent], Any]] = None,
    ) -> None:
        if not isinstance(config, PlaybackConfig):
            raise TypeError("config must be PlaybackConfig")
        self.config = config
        self._sounddevice = sounddevice_module
        self.on_event = on_event
        self._lock = threading.RLock()
        self._not_full = threading.Condition(self._lock)
        self._state = PlaybackState.STOPPED
        self._stream: Any = None
        self._blocks: Deque[np.ndarray] = deque()
        self._current: Optional[np.ndarray] = None
        self._current_offset = 0
        self._queued_frames = 0
        self._slot: Optional[_TurnSlot] = None
        self._last_stop_slot: Optional[_TurnSlot] = None
        self._generation = 0
        self._event_sequence = 0
        self._played_frames = 0
        self._enqueued_frames = 0
        self._underrun_count = 0
        self._backpressure_count = 0
        self._dropped_stale_blocks = 0
        self._last_error_code: Optional[str] = None
        self._play_rms = 0.0
        self._last_error_detail = ""

    @property
    def state(self) -> PlaybackState:
        with self._lock:
            return self._state

    def start(self) -> None:
        """Open the selected output stream without starting user audio."""
        with self._lock:
            if self._state in (PlaybackState.READY, PlaybackState.PLAYING):
                return
        try:
            sounddevice = self._module()
            stream = sounddevice.OutputStream(
                device=self.config.device,
                samplerate=self.config.sample_rate,
                channels=self.config.channels,
                dtype="float32",
                blocksize=self.config.block_frames,
                latency="low",
                callback=self._callback,
            )
            stream.start()
        except Exception as exc:
            self._record_error("VOICE-PLAYBACK-START-FAILED", type(exc).__name__)
            raise PlaybackError("VOICE-PLAYBACK-START-FAILED", type(exc).__name__) from exc
        with self._lock:
            self._stream = stream
            self._state = PlaybackState.READY
        self._emit(PlaybackEventKind.READY.value)

    async def play(self, chunk: Any, lease: Any, signal: Any) -> bool:
        """Queue one normalized PCM frame without blocking the event loop."""
        return await asyncio.to_thread(self._enqueue, chunk, lease, signal)

    async def finish(self, lease: Any, signal: Any) -> bool:
        """Wait until the callback has physically drained one normal turn."""
        slot: Optional[_TurnSlot]
        events: list[tuple[str, Optional[str], dict]] = []
        with self._lock:
            slot = self._slot_for_lease_locked(lease)
            if slot is None:
                return bool(_is_cancelled(signal))
            if _is_cancelled(signal):
                return False
            slot.finish_requested = True
            if self._queued_frames == 0 and self._current is None:
                events.extend(self._complete_slot_locked(slot))
        self._emit_many(events)
        confirmed = await asyncio.to_thread(slot.done_event.wait, self.config.stop_timeout_s)
        return bool(confirmed and slot.normal_completed and not slot.cancelled)

    def interrupt(self, reason: str = "interrupted") -> bool:
        """Drop old audio and require one callback pass of silence as proof."""
        events: list[tuple[str, Optional[str], dict]] = []
        with self._lock:
            slot = self._slot
            if slot is None:
                return True
            slot.cancelled = True
            slot.finish_requested = False
            slot.done_event.set()
            slot.stopped_event.clear()
            self._last_stop_slot = slot
            self._clear_queue_locked()
            self._slot = None
            if self._stream is None or not bool(getattr(self._stream, "active", True)):
                slot.stopped_event.set()
                events.append(
                    (
                        PlaybackEventKind.STOPPED.value,
                        None,
                        {"reason": str(reason or "interrupted")[:160], "confirmed": True},
                    )
                )
            else:
                events.append(
                    (
                        PlaybackEventKind.STOPPED.value,
                        None,
                        {"reason": str(reason or "interrupted")[:160], "confirmed": False},
                    )
                )
            self._state = PlaybackState.READY
            self._not_full.notify_all()
        self._emit_many(events)
        return True

    cancel = interrupt

    async def wait_stopped(self, timeout_s: float) -> bool:
        """Observe physical silence after the most recent cancellation."""
        timeout = max(float(timeout_s), 0.0)
        with self._lock:
            slot = self._last_stop_slot
            stream = self._stream
            if slot is None:
                return self._state is PlaybackState.STOPPED or not self._is_playing_locked()
            event = slot.stopped_event
            already = event.is_set()
            stream_active = bool(stream is not None and getattr(stream, "active", True))
        if already:
            return True
        if not stream_active:
            event.set()
            return True
        return bool(await asyncio.to_thread(event.wait, timeout))

    def close(self, reason: str = "shutdown") -> None:
        """Release the sounddevice stream after clearing all transient audio."""
        self.interrupt(reason)
        with self._lock:
            stream, self._stream = self._stream, None
            self._clear_queue_locked()
            self._state = PlaybackState.STOPPED
            slot = self._last_stop_slot
            self._not_full.notify_all()
        if stream is not None:
            try:
                stream.stop()
            finally:
                stream.close()
        if slot is not None:
            slot.stopped_event.set()

    shutdown = close

    def health(self) -> Mapping[str, Any]:
        with self._lock:
            return {
                "state": self._state.value,
                "started": self._stream is not None,
                "stream_active": bool(
                    self._stream is not None and getattr(self._stream, "active", True)
                ),
                "device": self.config.device,
                "sample_rate": self.config.sample_rate,
                "channels": self.config.channels,
                "playing": self._is_playing_locked(),
                "queue_depth": len(self._blocks) + (1 if self._current is not None else 0),
                "queue_duration_ms": self._queue_duration_ms_locked(),
                "active_turn_id": self._slot.turn_id if self._slot is not None else None,
                "generation": self._generation,
                "last_error_code": self._last_error_code,
                "play_rms": round(self._play_rms, 6),
            }

    def playback_rms(self) -> float:
        """Latest output-block RMS; input voice gate reference (Demo borrow)."""
        return self._play_rms

    def metrics(self) -> Mapping[str, Any]:
        with self._lock:
            return {
                **dict(self.health()),
                "played_frames": self._played_frames,
                "enqueued_frames": self._enqueued_frames,
                "underrun_count": self._underrun_count,
                "backpressure_count": self._backpressure_count,
                "dropped_stale_blocks": self._dropped_stale_blocks,
                "last_error_detail": self._last_error_detail,
            }

    def _enqueue(self, chunk: Any, lease: Any, signal: Any) -> bool:
        if _is_cancelled(signal):
            return False
        block = self._normalize_chunk(chunk)
        turn_id = _turn_id(lease)
        deadline = time.monotonic() + self.config.enqueue_timeout_s
        events: list[tuple[str, Optional[str], dict]] = []
        with self._not_full:
            self._require_ready_locked()
            slot = self._slot
            if slot is None:
                self._generation += 1
                slot = _TurnSlot(self._generation, turn_id)
                self._slot = slot
                self._last_stop_slot = None
            elif slot.turn_id != turn_id:
                self._dropped_stale_blocks += 1
                raise PlaybackError("VOICE-PLAYBACK-TURN-CONFLICT", turn_id)
            if slot.finish_requested or slot.cancelled:
                self._dropped_stale_blocks += 1
                raise PlaybackError("VOICE-PLAYBACK-TURN-TERMINAL", turn_id)
            block_duration_ms = _frames_to_ms(len(block), self.config.sample_rate)
            if block_duration_ms > self.config.max_queue_duration_ms:
                raise PlaybackError("VOICE-PLAYBACK-CHUNK-TOO-LARGE")
            while (
                len(self._blocks) + (1 if self._current is not None else 0)
                >= self.config.max_queue_blocks
                or self._queue_duration_ms_locked() + block_duration_ms
                > self.config.max_queue_duration_ms
            ):
                if _is_cancelled(signal) or slot.cancelled:
                    return False
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._backpressure_count += 1
                    self._record_error_locked("VOICE-PLAYBACK-BACKPRESSURE", "queue wait timed out")
                    events.append(
                        (
                            PlaybackEventKind.ERROR.value,
                            "VOICE-PLAYBACK-BACKPRESSURE",
                            {"queue_depth": len(self._blocks), "queue_duration_ms": self._queue_duration_ms_locked()},
                        )
                    )
                    break
                self._not_full.wait(min(remaining, 0.05))
            else:
                self._blocks.append(block)
                self._queued_frames += len(block)
                self._enqueued_frames += len(block)
                return True
        self._emit_many(events)
        raise PlaybackError("VOICE-PLAYBACK-BACKPRESSURE", "queue wait timed out")

    def _normalize_chunk(self, chunk: Any) -> np.ndarray:
        sample_rate = int(getattr(chunk, "sample_rate", 0) or 0)
        channels = int(getattr(chunk, "channels", 0) or 0)
        fmt = str(getattr(chunk, "format", "") or "").lower()
        samples = getattr(chunk, "samples", None)
        if samples is None:
            raise PlaybackError("VOICE-PLAYBACK-CHUNK-INVALID")
        if sample_rate != self.config.sample_rate:
            raise PlaybackError(
                "VOICE-PLAYBACK-SAMPLE-RATE",
                "expected {0}, received {1}".format(self.config.sample_rate, sample_rate),
            )
        if channels != 1:
            raise PlaybackError("VOICE-PLAYBACK-CHANNELS", "expected mono input")
        if fmt not in {"pcm_s16le", "s16le"}:
            raise PlaybackError("VOICE-PLAYBACK-FORMAT", fmt[:80])
        if not isinstance(samples, (bytes, bytearray, memoryview)):
            raise PlaybackError("VOICE-PLAYBACK-PCM-INVALID", "PCM must be bytes")
        raw = bytes(samples)
        if not raw or len(raw) % 2:
            raise PlaybackError("VOICE-PLAYBACK-PCM-INVALID", "PCM byte length is invalid")
        mono = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
        mono *= float(self.config.volume)
        return np.repeat(mono.reshape(-1, 1), self.config.channels, axis=1)

    def _callback(self, outdata: Any, frames: int, time_info: Any, status: Any) -> None:
        """PortAudio callback: copy prepared blocks or fill silence only."""
        outdata.fill(0)
        events: list[tuple[str, Optional[str], dict]] = []
        with self._not_full:
            if status:
                self._record_error_locked("VOICE-PLAYBACK-STREAM-STATUS", str(status)[:160])
                events.append(
                    (
                        PlaybackEventKind.ERROR.value,
                        "VOICE-PLAYBACK-STREAM-STATUS",
                        {"status": str(status)[:160]},
                    )
                )
            slot = self._slot
            if slot is None:
                self._ack_stop_locked(events)
                self._not_full.notify_all()
            else:
                if not self._is_playing_locked() and self._should_start_locked(slot):
                    self._state = PlaybackState.PLAYING
                    slot.started_at = time.monotonic()
                    events.append(
                        (
                            PlaybackEventKind.STARTED.value,
                            None,
                            {"turn_id": slot.turn_id, "queue_duration_ms": self._queue_duration_ms_locked()},
                        )
                    )
                if self._is_playing_locked():
                    copied = self._copy_frames_locked(outdata, int(frames))
                    if copied:
                        self._played_frames += copied
                    elif slot.finish_requested:
                        events.extend(self._complete_slot_locked(slot))
                    else:
                        self._state = PlaybackState.READY
                        self._underrun_count += 1
                        self._record_error_locked("VOICE-PLAYBACK-UNDERRUN", "queue drained before finish")
                        events.append(
                            (
                                PlaybackEventKind.UNDERRUN.value,
                                "VOICE-PLAYBACK-UNDERRUN",
                                {"turn_id": slot.turn_id},
                            )
                        )
                self._not_full.notify_all()
        # Cheap playback energy reference for the input side's voice gate
        # (borrowed from 对话DEMO, ledger 0130). A stale/zero RMS means the
        # speaker is silent — gate remains permissive.
        try:
            import numpy as _np

            self._play_rms = float(_np.sqrt(float(_np.mean(_np.square(outdata)))))
        except Exception:
            self._play_rms = 0.0
        self._emit_many(events)

    def _copy_frames_locked(self, outdata: np.ndarray, frames: int) -> int:
        copied = 0
        while copied < frames:
            if self._current is None:
                if not self._blocks:
                    break
                self._current = self._blocks.popleft()
                self._current_offset = 0
            remaining = len(self._current) - self._current_offset
            if remaining <= 0:
                self._current = None
                self._current_offset = 0
                continue
            count = min(frames - copied, remaining)
            outdata[copied : copied + count, :] = self._current[
                self._current_offset : self._current_offset + count, :
            ]
            copied += count
            self._current_offset += count
            self._queued_frames = max(0, self._queued_frames - count)
            if self._current_offset >= len(self._current):
                self._current = None
                self._current_offset = 0
        return copied

    def _should_start_locked(self, slot: _TurnSlot) -> bool:
        if self._queued_frames <= 0:
            return False
        return (
            self._queue_duration_ms_locked() >= self.config.initial_buffer_ms
            or slot.finish_requested
        )

    def _complete_slot_locked(self, slot: _TurnSlot) -> list[tuple[str, Optional[str], dict]]:
        if slot.cancelled or slot.normal_completed:
            return []
        slot.normal_completed = True
        slot.done_event.set()
        self._slot = None
        self._state = PlaybackState.READY
        self._not_full.notify_all()
        return [
            (
                PlaybackEventKind.DONE.value,
                None,
                {"turn_id": slot.turn_id, "played_frames": self._played_frames},
            )
        ]

    def _ack_stop_locked(self, events: list[tuple[str, Optional[str], dict]]) -> None:
        slot = self._last_stop_slot
        if slot is not None and not slot.stopped_event.is_set():
            slot.stopped_event.set()
            events.append(
                (
                    PlaybackEventKind.STOPPED.value,
                    None,
                    {"turn_id": slot.turn_id, "confirmed": True},
                )
            )

    def _slot_for_lease_locked(self, lease: Any) -> Optional[_TurnSlot]:
        slot = self._slot
        if slot is None:
            return None
        if slot.turn_id != _turn_id(lease):
            raise PlaybackError("VOICE-PLAYBACK-TURN-CONFLICT", _turn_id(lease))
        return slot

    def _require_ready_locked(self) -> None:
        if self._state is PlaybackState.FAILED:
            raise PlaybackError("VOICE-PLAYBACK-FAILED", self._last_error_code or "failed")
        if self._stream is None or self._state is PlaybackState.STOPPED:
            raise PlaybackError("VOICE-PLAYBACK-NOT-READY")

    def _is_playing_locked(self) -> bool:
        return self._state is PlaybackState.PLAYING

    def _queue_duration_ms_locked(self) -> int:
        return _frames_to_ms(self._queued_frames, self.config.sample_rate)

    def _clear_queue_locked(self) -> None:
        self._blocks.clear()
        self._current = None
        self._current_offset = 0
        self._queued_frames = 0

    def _record_error(self, code: str, detail: str) -> None:
        with self._lock:
            self._record_error_locked(code, detail)
        self._emit(PlaybackEventKind.ERROR.value, code, {"detail": detail[:160]})

    def _record_error_locked(self, code: str, detail: str) -> None:
        self._last_error_code = str(code)[:160]
        self._last_error_detail = str(detail)[:160]

    def _module(self) -> Any:
        if self._sounddevice is None:
            try:
                import sounddevice as sounddevice_module  # type: ignore
            except ImportError as exc:
                raise PlaybackError("VOICE-PLAYBACK-DEPENDENCY-MISSING") from exc
            self._sounddevice = sounddevice_module
        return self._sounddevice

    def _emit_many(self, values: list[tuple[str, Optional[str], dict]]) -> None:
        for kind, code, payload in values:
            self._emit(kind, code, payload)

    def _emit(self, kind: str, code: Optional[str] = None, payload: Optional[dict] = None) -> None:
        with self._lock:
            self._event_sequence += 1
            event = PlaybackEvent(
                kind=str(kind),
                code=code,
                event_seq=self._event_sequence,
                generation=self._generation,
                payload=dict(payload or {}),
            )
            sink = self.on_event
        if sink is not None:
            try:
                sink(event)
            except Exception:
                pass


def _is_cancelled(signal: Any) -> bool:
    method = getattr(signal, "is_cancelled", None)
    try:
        return bool(method()) if callable(method) else False
    except Exception:
        return True


def _turn_id(lease: Any) -> str:
    value = str(getattr(lease, "turn_id", "") or "")
    if not value:
        raise PlaybackError("VOICE-PLAYBACK-TURN-ID-MISSING")
    return value[:160]


def _frames_to_ms(frames: int, sample_rate: int) -> int:
    return max(0, int(round(int(frames) * 1000 / int(sample_rate))))


__all__ = [
    "PlaybackConfig",
    "PlaybackError",
    "PlaybackEvent",
    "PlaybackEventKind",
    "PlaybackState",
    "SoundDevicePlaybackPort",
]
