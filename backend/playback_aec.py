"""AEC adapter wrapping the existing AdaptiveEchoCanceller for MediaAdapter.

Implements the AECPort protocol (mic_audio, reference_audio, sample_rate) ->
(echo_cancelled_audio, echo_return_loss).  Uses the NLMS implementation from
backend.echo_cancellation.

Also provides PlaybackReferenceBuffer that accumulates reference frames from
the playback tap and provides them to the media adapter at the right time.
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
        mic = np.ascontiguousarray(mic_audio, dtype=np.float32)
        ref = np.ascontiguousarray(reference_audio, dtype=np.float32)
        min_len = min(len(mic), len(ref))
        if min_len == 0:
            return mic, 0.0
        return self._aec.process(mic[:min_len], ref[:min_len])

    def reset(self) -> None:
        self._aec.reset()

    def enable(self) -> None:
        self._aec.enable()

    def disable(self) -> None:
        self._aec.disable()


class PlaybackReferenceBuffer:
    """Accumulates playback reference frames and provides them for AEC.

    Thread-safe; the playback tap calls add_frame() and the media adapter
    calls take_reference() to get the current reference for AEC processing.
    """

    def __init__(self, max_duration_s: float = 2.0, sample_rate: int = 24000) -> None:
        self._lock = threading.Lock()
        self._frames: Deque[np.ndarray] = deque()
        self._total_samples = 0
        self._max_samples = int(max_duration_s * sample_rate)
        self._generation = 0
        self._seq = 0

    def add_frame(self, samples: np.ndarray, generation: int = 0) -> None:
        with self._lock:
            self._frames.append(samples)
            self._total_samples += len(samples)
            while self._total_samples > self._max_samples and self._frames:
                old = self._frames.popleft()
                self._total_samples -= len(old)

    def take_reference(self, n_samples: int) -> np.ndarray:
        with self._lock:
            out = np.zeros(0, dtype=np.float32)
            for frame in self._frames:
                out = np.concatenate([out, frame])
                if len(out) >= n_samples:
                    break
            return out[:n_samples]

    def clear(self, generation: int = 0) -> None:
        with self._lock:
            self._frames.clear()
            self._total_samples = 0

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "frames": len(self._frames),
                "total_samples": self._total_samples,
                "max_samples": self._max_samples,
            }


def make_speaker_mic_aec(filter_length: int = 4096) -> NLMSAECAdapter:
    """Factory for a speaker_mic route AEC adapter."""
    return NLMSAECAdapter(filter_length=filter_length)
