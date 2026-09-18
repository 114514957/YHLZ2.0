"""Shared voice DSP helpers (ledger 0422).

NEKO-derived AGC/Limiter (params from N.E.K.O ``utils/audio_processor.py``) and
a stateful soxr stream resampler (NEKO also resamples with soxr HQ).  Both the
demo (``tools/voice_dsp_demo.py``) and the live chain
(``tools/voice_dialog_probe.py``) import from here so there is a single place
to tune.  Touches no project data.
"""
from __future__ import annotations

import numpy as np

# --- NEKO params (utils/audio_processor.py) ---
AGC_TARGET_LEVEL = 0.25
AGC_MAX_GAIN = 20.0
AGC_MIN_GAIN = 0.25
AGC_NOISE_FLOOR = 0.015
AGC_ATTACK_TIME = 0.01
AGC_RELEASE_TIME = 0.4
AGC_SAMPLE_RATE = 48_000
LIMITER_THRESHOLD = 0.95
LIMITER_KNEE = 0.05


def agc_int16(x16: np.ndarray, *, chunk: int = 480,
              sample_rate: int = AGC_SAMPLE_RATE) -> np.ndarray:
    """NEKO ``_apply_agc`` at the 10 ms frame cadence its coefficients assume."""
    x16 = np.asarray(x16, dtype=np.int16)
    attack = float(np.exp(-1.0 / (AGC_ATTACK_TIME * sample_rate)))
    release = float(np.exp(-1.0 / (AGC_RELEASE_TIME * sample_rate)))
    gain = 1.0
    out = np.empty_like(x16)
    for i in range(0, len(x16), chunk):
        seg = x16[i:i + chunk].astype(np.float32) / 32768.0
        if seg.size == 0:
            continue
        rms = float(np.sqrt(np.mean(seg ** 2) + 1e-10))
        if rms > AGC_NOISE_FLOOR:
            desired = float(np.clip(AGC_TARGET_LEVEL / rms, AGC_MIN_GAIN, AGC_MAX_GAIN))
        else:
            desired = min(gain, 1.0)
        coeff = attack if desired < gain else release
        gain = coeff * gain + (1 - coeff) * desired
        out[i:i + chunk] = np.clip(seg * gain * 32768.0, -32768, 32767).astype(np.int16)
    return out


def limiter_int16(x16: np.ndarray) -> np.ndarray:
    """NEKO ``_apply_limiter``: soft knee + tanh saturation, never clips."""
    f = np.asarray(x16, dtype=np.float32) / 32768.0
    abs_f = np.abs(f)
    knee_start = LIMITER_THRESHOLD - LIMITER_KNEE / 2
    knee_end = LIMITER_THRESHOLD + LIMITER_KNEE / 2
    out = np.copy(f)
    in_knee = (abs_f > knee_start) & (abs_f <= knee_end)
    if np.any(in_knee):
        ratio = (abs_f[in_knee] - knee_start) / LIMITER_KNEE
        comp = 1 - 0.5 * ratio ** 2
        out[in_knee] = np.sign(f[in_knee]) * (
            knee_start + (abs_f[in_knee] - knee_start) * comp)
    above = abs_f > knee_end
    if np.any(above):
        excess = abs_f[above] - LIMITER_THRESHOLD
        limited = LIMITER_THRESHOLD + 0.5 * np.tanh(excess * 2) * (1 - LIMITER_THRESHOLD)
        out[above] = np.sign(f[above]) * limited
    return (np.clip(out, -1.0, 1.0) * 32768.0).clip(-32768, 32767).astype(np.int16)


def segment_dsp(x16: np.ndarray, mode: str = "agc+lim") -> np.ndarray:
    """Captured-segment conditioning: off | lim | agc+lim (ledger 0421 demo)."""
    m = str(mode or "off").lower()
    y = np.asarray(x16, dtype=np.int16)
    if m in ("off", "none", ""):
        return y
    if m in ("agc+lim", "agc", "both"):
        y = agc_int16(y)
    if m in ("agc+lim", "lim", "limiter", "both"):
        y = limiter_int16(y)
    return y


class StreamResampler:
    """Stateful soxr HQ stream resampler with a linear fallback.

    NEKO resamples with ``soxr.ResampleStream`` (no 10 ms-boundary artefacts);
    the fallback keeps the chain alive if soxr is ever missing.
    """

    def __init__(self, in_rate: int, out_rate: int = 16_000) -> None:
        self.in_rate = int(in_rate)
        self.out_rate = int(out_rate)
        self._ratio = self.out_rate / float(self.in_rate)
        self._stream = None
        if self.in_rate != self.out_rate:
            try:
                import soxr

                self._stream = soxr.ResampleStream(
                    self.in_rate, self.out_rate, 1, dtype="float32", quality="HQ")
            except Exception:
                self._stream = None

    def process(self, block: np.ndarray) -> np.ndarray:
        x = np.asarray(block, dtype="float32")
        if self.in_rate == self.out_rate or x.size == 0:
            return x
        if self._stream is not None:
            return np.asarray(self._stream.resample_chunk(x), dtype="float32")
        n_out = int(round(x.size * self._ratio))
        if n_out <= 0:
            return np.zeros(0, dtype="float32")
        grid = np.linspace(0.0, float(x.size - 1), n_out)
        return np.interp(grid, np.arange(x.size), x).astype("float32")

    def flush(self) -> np.ndarray:
        if self._stream is None or self.in_rate == self.out_rate:
            return np.zeros(0, dtype="float32")
        try:
            return np.asarray(
                self._stream.resample_chunk(np.zeros(0, dtype="float32"), last=True),
                dtype="float32")
        except Exception:
            return np.zeros(0, dtype="float32")


__all__ = [
    "AGC_TARGET_LEVEL", "AGC_SAMPLE_RATE", "LIMITER_THRESHOLD",
    "StreamResampler", "agc_int16", "limiter_int16", "segment_dsp",
]
