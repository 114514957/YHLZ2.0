"""N.E.K.O.-style audio processor: RNNoise -> AGC -> Limiter -> 48k->16k.

Parameters and chain order are borrowed verbatim from N.E.K.O.
``utils/audio_processor.py`` (ledger 0132).  The adapter consumes 48 kHz
mono float32 chunks and yields 16 kHz mono float32, calling ``reset()`` at
the end of each speech window (RNNoise GRU state drifts on background
noise).
"""

from __future__ import annotations

import ctypes
import importlib.util
import platform
import threading
from typing import Any, Optional

import numpy as np

from backend.target_noise_suppression import is_denoiser  # noqa: F401  (re-export)

RNNOISE_SAMPLE_RATE = 48_000
RNNOISE_FRAME_SIZE = 480

RNNOISE_SPEECH_PROBABILITY_THRESHOLD = 0.2
RNNOISE_EMA_ALPHA = 0.35
RNNOISE_RESET_IDLE_S = 5.0

AGC_TARGET_LEVEL = 0.25
AGC_MAX_GAIN = 20.0
AGC_MIN_GAIN = 0.25
AGC_NOISE_FLOOR = 0.015
AGC_ATTACK_TIME = 0.01
AGC_RELEASE_TIME = 0.4

LIMITER_THRESHOLD = 0.95
LIMITER_KNEE = 0.05

TARGET_SR = 16_000


class _RNNoiseLib:
    def __init__(self, lib: Any, frame_size: int) -> None:
        self._lib = lib
        self.FRAME_SIZE = frame_size

    def create(self) -> int:
        return int(self._lib.rnnoise_create(None))

    def process_frame(self, state: int, frame: np.ndarray) -> tuple[np.ndarray, float]:
        if frame.dtype == np.int16:
            frame = frame.astype(np.float32)
        else:
            frame = (frame * 32767.0).astype(np.float32)
        n = len(frame)
        if n < self.FRAME_SIZE:
            frame = np.pad(frame, (0, self.FRAME_SIZE - n))
        ptr = frame.ctypes.data_as(ctypes.POINTER(ctypes.c_float))
        prob = float(self._lib.rnnoise_process_frame(state, ptr, ptr))
        out = np.clip(np.round(frame), -32768, 32767).astype(np.int16)[:n]
        return out, prob

    def destroy(self, state: int) -> None:
        self._lib.rnnoise_destroy(state)


def _load_rnnoise() -> Optional[_RNNoiseLib]:
    name = {"Windows": "rnnoise.dll", "Darwin": "librnnoise.dylib", "Linux": "librnnoise.so"}
    lib_name = name.get(platform.system())
    spec = importlib.util.find_spec("pyrnnoise")
    candidate_spec = list(spec.submodule_search_locations or []) if spec else []
    paths = [f"{p}/{lib_name}" for p in candidate_spec]
    for path in paths:
        try:
            lib = ctypes.CDLL(path)
            lib.rnnoise_create.argtypes = [ctypes.c_void_p]
            lib.rnnoise_create.restype = ctypes.c_void_p
            lib.rnnoise_destroy.argtypes = [ctypes.c_void_p]
            lib.rnnoise_destroy.restype = None
            lib.rnnoise_get_frame_size.argtypes = []
            lib.rnnoise_get_frame_size.restype = ctypes.c_int
            lib.rnnoise_process_frame.argtypes = [
                ctypes.c_void_p,
                ctypes.POINTER(ctypes.c_float),
                ctypes.POINTER(ctypes.c_float),
            ]
            lib.rnnoise_process_frame.restype = ctypes.c_float
            return _RNNoiseLib(lib, int(lib.rnnoise_get_frame_size()))
        except Exception:
            continue
    return None


class NEKOAudioProcessor:
    """RNNoise -> AGC -> Limiter -> downsampling (48k in / 16k out)."""

    def __init__(
        self,
        *,
        noise_reduce_enabled: bool = True,
        agc_enabled: bool = True,
        limiter_enabled: bool = True,
    ) -> None:
        self.noise_reduce_enabled = bool(noise_reduce_enabled)
        self.agc_enabled = bool(agc_enabled)
        self.limiter_enabled = bool(limiter_enabled)
        self._lock = threading.RLock()
        self._rnnoise = _load_rnnoise() if noise_reduce_enabled else None
        self._state: Optional[int] = None
        self._needs_reset = False
        self._ema_state: float = 0.0
        self._agc_gain = 1.0
        self._atk = float(np.exp(-1.0 / (AGC_ATTACK_TIME * RNNOISE_SAMPLE_RATE)))
        self._rel = float(np.exp(-1.0 / (AGC_RELEASE_TIME * RNNOISE_SAMPLE_RATE)))
        self._soxr = None
        try:
            import soxr

            self._soxr = soxr
        except Exception:
            self._soxr = None
        if self._rnnoise is not None:
            self._state = self._rnnoise.create()

    @property
    def available(self) -> bool:
        return self._rnnoise is not None and self._state is not None

    def process_mono(self, samples: np.ndarray, sample_rate: int = RNNOISE_SAMPLE_RATE) -> tuple[np.ndarray, float]:
        """Process one 48 kHz chunk -> (16 kHz float32 mono, last prob)."""
        with self._lock:
            if samples is None or samples.size == 0:
                return samples, 0.0
            mono = np.asarray(samples, dtype="float32").reshape(-1)
            if self.available:
                ds = self._rnnoise.process_step(mono) if hasattr(self._rnnoise, "process_step") else self._process_rnnoise(mono)
            else:
                ds = mono
            if self.agc_enabled:
                ds = self._agc(ds)
            if self.limiter_enabled:
                ds = self._limiter(ds)
            down = self._downsample(ds)
            return down, self._last_prob

    def _process_rnnoise(self, mono: np.ndarray) -> np.ndarray:
        i16 = (np.clip(mono, -1.0, 1.0) * 32767.0).astype(np.int16)
        out = []
        self._probs = []
        for off in range(0, len(i16) - RNNOISE_FRAME_SIZE + 1, RNNOISE_FRAME_SIZE):
            den, prob = self._rnnoise.process_frame(self._state, i16[off : off + RNNOISE_FRAME_SIZE])
            out.append(den.astype("float32") / 32768.0)
            self._probs.append(prob)
        if not out:
            return mono.astype("float32")
        self._last_prob = float(np.mean(self._probs)) if self._probs else 0.0
        return np.concatenate(out).astype("float32")

    _last_prob = 0.0

    def _agc(self, mono: np.ndarray) -> np.ndarray:
        rms = float(np.sqrt(np.mean(np.square(mono))))
        if rms < AGC_NOISE_FLOOR:
            target_gain = AGC_MIN_GAIN
        else:
            target_gain = float(np.clip(AGC_TARGET_LEVEL / rms, AGC_MIN_GAIN, AGC_MAX_GAIN))
        coeff = self._atk if target_gain > self._agc_gain else self._rel
        self._agc_gain = coeff * self._agc_gain + (1.0 - coeff) * target_gain
        return np.clip(mono * self._agc_gain, -1.0, 1.0)

    def _limiter(self, mono: np.ndarray) -> np.ndarray:
        out = np.array(mono, dtype="float32")
        x = np.abs(out)
        over = x > LIMITER_THRESHOLD - LIMITER_KNEE
        if over.any():
            mult = np.clip((LIMITER_THRESHOLD - LIMITER_KNEE) / (LIMITER_THRESHOLD - LIMITER_KNEE + np.maximum(x - (LIMITER_THRESHOLD - LIMITER_KNEE), 1e-9)), 0, 1)
            out[over] = out[over] * mult[over]
        return np.clip(out, -1.0, 1.0)

    def _downsample(self, mono: np.ndarray) -> np.ndarray:
        step = RNNOISE_SAMPLE_RATE // TARGET_SR
        if self._soxr is not None:
            try:
                return self._soxr.resample(mono.astype("float32"), RNNOISE_SAMPLE_RATE, TARGET_SR)
            except Exception:
                pass
        return mono[::step].astype("float32")

    def reset(self) -> None:
        with self._lock:
            self._agc_gain = 1.0
            if self.available:
                try:
                    self._rnnoise.destroy(self._state)
                except Exception:
                    pass
                self._state = self._rnnoise.create()
            self._ema_state = 0.0

    def close(self) -> None:
        with self._lock:
            if self.available:
                try:
                    self._rnnoise.destroy(self._state)
                except Exception:
                    pass
                self._state = None

    def health(self) -> dict:
        return {
            "available": self.available,
            "engine": "neko-audio-processor",
            "noise_reduce": self.noise_reduce_enabled,
            "agc_enabled": self.agc_enabled,
            "limiter_enabled": self.limiter_enabled,
            "target_level": AGC_TARGET_LEVEL,
        }
