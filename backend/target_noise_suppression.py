"""RNNoise speech-noise suppression for the target media chain (NEKO standard).

The capture surface stays at 16 kHz; this adapter resamples to RNNoise's
native 48 kHz domain, suppresses per 10 ms frame, and returns 16 kHz so the
contract downstream (VAD/ASR) never changes.  The GRU state is reset when a
speech window ends, mirroring N.E.K.O.'s ``AudioProcessor``.
"""

from __future__ import annotations

import threading
from typing import Any, Optional

import numpy as np

RNNOISE_SR = 48_000
RNNOISE_FRAME = 480

# AGC targets (NEKO chain order is noise->AGC; a too-quiet near-field mic
# needs the boost FIRST so RNNoise does not treat speech as noise).
AGC_TARGET_RMS = 0.06
AGC_MAX_GAIN = 24.0
AGC_ATTACK = 0.01
AGC_RELEASE = 0.12


class _FrameAGC:
    """Fast adaptive gain with a noise gate and limiter (16 kHz frame)."""

    def __init__(
        self,
        *,
        target_rms: float = AGC_TARGET_RMS,
        max_gain: float = AGC_MAX_GAIN,
        floor_samples: int = 40,
    ) -> None:
        self.target_rms = float(target_rms)
        self.max_gain = float(max_gain)
        self.floor_samples = int(floor_samples)
        self._gain = 1.0
        self._prev_rms: Optional[float] = None
        self._floor: float = 1e-6
        self._seen: list[float] = []

    def process(self, chunk: np.ndarray, sample_rate: int) -> np.ndarray:
        rms = float(np.sqrt(np.mean(np.square(chunk))))
        # Adaptive noise floor: track the quietest observed frames.
        if len(self._seen) < self.floor_samples:
            self._seen.append(rms)
            self._floor = float(np.median(self._seen)) if rms < self._floor else self._floor
            if len(self._seen) == self.floor_samples:
                self._floor = float(np.median(self._seen[-self.floor_samples:])) * 1.5
        if rms > self._floor * 4.0:
            target = self.target_rms / rms
            target = float(np.clip(target, 1.0, self.max_gain))
            alpha = len(chunk) / (sample_rate * AGC_ATTACK + len(chunk)) if rms > (self._prev_rms or rms) else len(
                chunk
            ) / (sample_rate * AGC_RELEASE + len(chunk))
            gain = (1.0 - alpha) * self._gain + alpha * target
        else:
            gain = 1.0
        self._gain = float(np.clip(gain, 1.0, self.max_gain))
        self._prev_rms = rms
        return np.clip(chunk * self._gain, -1.0, 1.0)

    def reset(self) -> None:
        self._gain = 1.0
        self._prev_rms = None
        self._seen = []
        self._floor = 1e-6


class RNNoiseDenoiser:
    """AGC-boosted, frame-based RNNoise wrapper with 16 kHz in/out interfaces."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._state: Any = None
        self._buf48: list[float] = []
        self._agc = _FrameAGC()
        try:
            from pyrnnoise.rnnoise import create, destroy, process_mono_frame

            self._create = create
            self._destroy = destroy
            self._process = process_mono_frame
            self._state = create()
        except Exception as exc:
            raise RuntimeError(
                "VOICE-NS-RNNOISE-UNAVAILABLE", type(exc).__name__
            ) from exc

    def process_mono(self, samples: np.ndarray) -> tuple[np.ndarray, float]:
        """AGC-boost then suppress one 16 kHz chunk -> (16 kHz, voice prob)."""
        with self._lock:
            if self._state is None:
                return samples, 0.0
            if samples is None or samples.size == 0:
                return samples, 0.0
            mono = np.asarray(samples, dtype="float32").reshape(-1)
            boosted = self._agc.process(mono, 16_000)
            up = self._resample(boosted, len(mono), int(len(mono) * RNNOISE_SR / 16_000))
            self._buf48.extend(up.tolist())
            out48: list[float] = []
            last_prob = 0.0
            while len(self._buf48) >= RNNOISE_FRAME:
                frame = np.array(self._buf48[:RNNOISE_FRAME], dtype="int16")
                del self._buf48[:RNNOISE_FRAME]
                den, prob = self._process(self._state, frame)
                out48.extend(np.asarray(den, dtype="int16").astype("float32").tolist())
                last_prob = float(prob)
            if len(self._buf48) > RNNOISE_FRAME:
                self._buf48 = self._buf48[-RNNOISE_FRAME:]
            if not out48:
                result = self._resample(boosted, len(mono), len(mono))
            else:
                n_out = int(len(out48) * 16_000 / RNNOISE_SR)
                result = self._resample(
                    np.asarray(out48, dtype="float32"), len(out48), n_out
                )
            return result.astype("float32"), last_prob

    def reset(self) -> None:
        """Reset the RNNoise GRU state + AGC state after an ended window."""
        with self._lock:
            self._agc.reset()
            if self._state is not None:
                try:
                    self._destroy(self._state)
                except Exception:
                    pass
                self._state = self._create()
            self._buf48.clear()

    def close(self) -> None:
        with self._lock:
            if self._state is not None:
                try:
                    self._destroy(self._state)
                except Exception:
                    pass
                self._state = None

    @staticmethod
    def _resample(x: np.ndarray, src_len: int, dst_len: int) -> np.ndarray:
        if dst_len <= 0 or src_len <= 0:
            return x.astype("float32") if dst_len <= 0 else np.zeros(dst_len, dtype="float32")
        if dst_len == src_len:
            return x.astype("float32")
        x_old = np.linspace(0.0, 1.0, max(int(src_len), 2))
        x_new = np.linspace(0.0, 1.0, int(dst_len))
        return np.interp(x_new, x_old, x.astype("float32")).astype("float32")

    def health(self) -> dict:
        return {"available": self._state is not None, "bitrate": 16_000, "engine": "rnnoise"}


def is_denoiser(value: Any) -> bool:
    return callable(getattr(value, "process_mono", None)) and callable(
        getattr(value, "reset", None)
    )
