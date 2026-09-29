"""AEC adapter wrapping the existing AdaptiveEchoCanceller for MediaAdapter.

Implements the AECPort protocol (mic_audio, reference_audio, sample_rate) ->
(echo_cancelled_audio, echo_return_loss).  Uses the NLMS implementation from
backend.echo_cancellation.

Also provides a consuming PlaybackReferenceBuffer for already aligned reference.
No production wiring or acoustic clock alignment is implied by this module.
"""
from __future__ import annotations

import threading
from collections import deque
from typing import Any, Deque, Optional

import numpy as np

from backend.echo_cancellation import AdaptiveEchoCanceller


class NLMSAECAdapter:
    """AECPort adapter wrapping AdaptiveEchoCanceller (NLMS)."""

    def __init__(self, filter_length: int = 4096, step_size: float = 0.5,
                 leakage: float = 0.99) -> None:
        self._aec = AdaptiveEchoCanceller(
            filter_length=filter_length,
            step_size=step_size,
            leakage=leakage,
        )

    def process(self, mic_audio: Any, reference_audio: Any,
                sample_rate: int) -> tuple:
        if sample_rate <= 0:
            raise ValueError("sample_rate must be positive")
        mic = _mono(mic_audio)
        ref = _mono(reference_audio)
        if not len(mic):
            return mic, 0.0
        # Reference starvation must not delete the user's audio. Keep one
        # output sample for every mic sample; pad absent reference with silence.
        aligned = np.zeros(len(mic), dtype=np.float32)
        count = min(len(mic), len(ref))
        aligned[:count] = ref[:count]
        return self._aec.process(mic, aligned)

    def reset(self) -> None:
        self._aec.reset()

    def enable(self) -> None:
        self._aec.enable()

    def disable(self) -> None:
        self._aec.disable()


def _mono(samples: Any) -> np.ndarray:
    data = np.asarray(samples, dtype=np.float32)
    if data.ndim == 2 and data.shape[1] > 0:
        data = data.mean(axis=1, dtype=np.float32)
    if data.ndim != 1:
        raise ValueError("audio must be mono or frames-by-channels")
    if not np.isfinite(data).all():
        raise ValueError("audio must contain finite samples")
    return np.ascontiguousarray(data)


class PlaybackReferenceBuffer:
    """Bounded, consuming FIFO for same-rate, already aligned mono reference.

    This is NOT a clock/delay synchronizer or a resampler. The production
    integration must align actual DAC frames to ADC frames before consumption.
    Underflow is padded with silence, never by shortening microphone audio.
    """

    def __init__(self, max_duration_s: float = 2.0, sample_rate: int = 24000) -> None:
        if max_duration_s <= 0 or sample_rate <= 0:
            raise ValueError("duration and sample_rate must be positive")
        self._lock = threading.Lock()
        self._frames: Deque[np.ndarray] = deque()
        self._total_samples = 0
        self._max_samples = max(1, int(max_duration_s * sample_rate))
        self._generation = 0
        self._underflow_samples = 0
        self._dropped_samples = 0
        self._stale_frames = 0

    def add_frame(self, samples: np.ndarray, generation: int = 0) -> None:
        # Callback buffers can be reused as soon as this method returns.
        data = _mono(samples).copy()
        generation = int(generation)
        with self._lock:
            if generation < self._generation:
                self._stale_frames += 1
                return
            if generation > self._generation:
                self._frames.clear()
                self._total_samples = 0
                self._generation = generation
            if not len(data):
                return
            self._frames.append(data)
            self._total_samples += len(data)
            overflow = max(0, self._total_samples - self._max_samples)
            self._dropped_samples += overflow
            while overflow:
                first = self._frames.popleft()
                drop = min(len(first), overflow)
                if drop < len(first):
                    self._frames.appendleft(first[drop:].copy())
                self._total_samples -= drop
                overflow -= drop

    def take_reference(self, n_samples: int) -> np.ndarray:
        if not isinstance(n_samples, (int, np.integer)) or n_samples < 0:
            raise ValueError("n_samples must be a nonnegative integer")
        out = np.zeros(n_samples, dtype=np.float32)
        with self._lock:
            copied = 0
            while self._frames and copied < n_samples:
                first = self._frames.popleft()
                count = min(len(first), n_samples - copied)
                out[copied:copied + count] = first[:count]
                copied += count
                self._total_samples -= count
                if count < len(first):
                    self._frames.appendleft(first[count:])
            self._underflow_samples += n_samples - copied
        return out

    def clear(self, generation: int = 0) -> None:
        with self._lock:
            if generation and generation < self._generation:
                return
            self._frames.clear()
            self._total_samples = 0
            self._generation = max(self._generation, int(generation))

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "frames": len(self._frames),
                "total_samples": self._total_samples,
                "max_samples": self._max_samples,
                "generation": self._generation,
                "underflow_samples": self._underflow_samples,
                "dropped_samples": self._dropped_samples,
                "stale_frames": self._stale_frames,
            }


class PlaybackReferenceAligner:
    """Aligns playback reference frames with microphone input frames.

    Maintains a ring buffer of recent reference frames (at device rate) and
    provides the matching reference slice when the media adapter ingests a
    mic frame.  Tracks queue delay for diagnostics.

    Clock source: both playback tap and media ingest use time.monotonic().
    """

    def __init__(self, buffer_ms: int = 500, sample_rate: int = 24000) -> None:
        import time as _time
        self._lock = threading.Lock()
        self._frames: Deque[tuple[float, int, np.ndarray]] = deque()  # (ts, gen, samples)
        self._buffer_samples = int(buffer_ms * sample_rate / 1000)
        self._sample_rate = sample_rate
        self._last_delay_ms: Optional[float] = None

    def add_playback_frame(self, samples: np.ndarray, generation: int = 0,
                           timestamp: float | None = None) -> None:
        """Called from the playback reference tap."""
        import time as _time
        ts = timestamp if timestamp is not None else _time.monotonic()
        with self._lock:
            self._frames.append((ts, generation, samples))
            total = sum(len(f[2]) for f in self._frames)
            while total > self._buffer_samples and self._frames:
                old = self._frames.popleft()
                total -= len(old[2])

    def get_reference_for(self, mic_samples: int,
                          timestamp: float | None = None) -> np.ndarray:
        """Return the reference audio slice matching the mic input."""
        import time as _time
        ts = timestamp if timestamp is not None else _time.monotonic()
        with self._lock:
            out = np.zeros(0, dtype=np.float32)
            for f_ts, f_gen, f_samples in self._frames:
                out = np.concatenate([out, f_samples])
                if len(out) >= mic_samples:
                    break
            self._last_delay_ms = (ts - self._frames[-1][0]) * 1000 if self._frames else None
            return out[:mic_samples]

    @property
    def last_delay_ms(self) -> Optional[float]:
        return self._last_delay_ms

    def clear(self) -> None:
        with self._lock:
            self._frames.clear()
            self._last_delay_ms = None

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "frames": len(self._frames),
                "buffer_samples": self._buffer_samples,
                "last_delay_ms": self._last_delay_ms,
            }


def make_speaker_mic_aec(filter_length: int = 4096) -> NLMSAECAdapter:
    """Factory for a speaker_mic route AEC adapter."""
    return NLMSAECAdapter(filter_length=filter_length)
