"""Bounded 48 kHz capture to 16 kHz processing adapter for the target chain."""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass
from typing import Any

import numpy as np


class InputResamplerError(RuntimeError):
    """Stable error emitted when native capture cannot enter the VAD domain."""

    def __init__(self, code: str, detail: str = "") -> None:
        self.code = str(code)[:160]
        self.detail = str(detail)[:400]
        super().__init__(self.code + (": " + self.detail if self.detail else ""))


@dataclass(frozen=True, slots=True)
class InputResamplerConfig:
    source_rate: int = 48_000
    target_rate: int = 16_000
    filter_order: int = 8
    passband_ratio: float = 0.90
    max_input_samples: int = 9_600

    def __post_init__(self) -> None:
        if self.source_rate <= 0 or self.target_rate <= 0:
            raise ValueError("source_rate and target_rate must be positive")
        if self.source_rate % self.target_rate != 0:
            raise ValueError("source_rate must be an integer multiple of target_rate")
        if self.source_rate // self.target_rate < 2:
            raise ValueError("this adapter is only for downsampling")
        if self.filter_order <= 0 or self.filter_order % 2:
            raise ValueError("filter_order must be a positive even integer")
        if not 0.0 < self.passband_ratio < 1.0:
            raise ValueError("passband_ratio must be within (0, 1)")
        if self.max_input_samples < self.downsample_factor:
            raise ValueError("max_input_samples is too small")

    @property
    def downsample_factor(self) -> int:
        return self.source_rate // self.target_rate

    def to_dict(self) -> dict:
        return {
            "source_rate": self.source_rate,
            "target_rate": self.target_rate,
            "downsample_factor": self.downsample_factor,
            "filter_order": self.filter_order,
            "passband_ratio": self.passband_ratio,
            "max_input_samples": self.max_input_samples,
        }


class TargetInputResampler:
    """Streaming anti-aliased mono downsampler with bounded in-memory state."""

    def __init__(self, config: InputResamplerConfig | None = None) -> None:
        self.config = config or InputResamplerConfig()
        try:
            from scipy import signal
        except ImportError as exc:
            raise InputResamplerError("RESAMPLER-SCIPY-MISSING") from exc
        cutoff = (self.config.target_rate / self.config.source_rate) * self.config.passband_ratio
        self._signal = signal
        self._sos = signal.butter(
            self.config.filter_order,
            cutoff,
            btype="lowpass",
            output="sos",
        )
        self._lock = threading.RLock()
        self._zi: np.ndarray | None = None
        self._source_samples = 0
        self._output_samples = 0
        self._calls = 0
        self._failures = 0
        self._last_error_code: str | None = None

    def reset(self) -> None:
        with self._lock:
            self._zi = None
            self._source_samples = 0
            self._output_samples = 0
            self._calls = 0
            self._failures = 0
            self._last_error_code = None

    def process(self, audio: Any, source_rate: int, target_rate: int) -> np.ndarray:
        """Return a float32 ``[frames, 1]`` array in the requested 16 kHz domain."""
        if int(source_rate) != self.config.source_rate or int(target_rate) != self.config.target_rate:
            self._record_failure("RESAMPLER-RATE-MISMATCH")
            raise InputResamplerError(
                "RESAMPLER-RATE-MISMATCH",
                f"{source_rate}->{target_rate}",
            )
        samples = self._normalize(audio)
        with self._lock:
            try:
                if self._zi is None:
                    initial = float(samples[0]) if samples.size else 0.0
                    self._zi = self._signal.sosfilt_zi(self._sos) * initial
                filtered, self._zi = self._signal.sosfilt(self._sos, samples, zi=self._zi)
                start = (-self._source_samples) % self.config.downsample_factor
                output = np.ascontiguousarray(
                    filtered[start :: self.config.downsample_factor],
                    dtype=np.float32,
                ).reshape(-1, 1)
            except InputResamplerError:
                raise
            except Exception as exc:
                self._record_failure("RESAMPLER-PROCESS-FAILED")
                raise InputResamplerError("RESAMPLER-PROCESS-FAILED", type(exc).__name__) from exc
            self._source_samples += int(samples.size)
            self._output_samples += int(output.shape[0])
            self._calls += 1
            return output

    def health(self) -> dict:
        with self._lock:
            return {
                "state": "ready",
                "config": self.config.to_dict(),
                "metrics": {
                    "calls": self._calls,
                    "source_samples": self._source_samples,
                    "output_samples": self._output_samples,
                    "failures": self._failures,
                },
                "last_error_code": self._last_error_code,
                "filter_initialized": self._zi is not None,
            }

    def _normalize(self, audio: Any) -> np.ndarray:
        if isinstance(audio, (bytes, bytearray, memoryview)):
            self._record_failure("RESAMPLER-FORMAT-DTYPE")
            raise InputResamplerError("RESAMPLER-FORMAT-DTYPE", "expected_float32")
        try:
            values = np.asarray(audio)
        except Exception as exc:
            self._record_failure("RESAMPLER-FORMAT-INVALID")
            raise InputResamplerError("RESAMPLER-FORMAT-INVALID", type(exc).__name__) from exc
        if values.ndim == 2:
            if values.shape[1] != 1:
                self._record_failure("RESAMPLER-FORMAT-CHANNELS")
                raise InputResamplerError("RESAMPLER-FORMAT-CHANNELS", str(values.shape[1]))
            values = values[:, 0]
        if values.ndim != 1 or values.dtype.kind != "f":
            self._record_failure("RESAMPLER-FORMAT-INVALID")
            raise InputResamplerError("RESAMPLER-FORMAT-INVALID")
        if values.size == 0 or values.size > self.config.max_input_samples:
            self._record_failure("RESAMPLER-FRAME-INVALID")
            raise InputResamplerError("RESAMPLER-FRAME-INVALID", str(values.size))
        normalized = np.ascontiguousarray(values, dtype=np.float32)
        if not np.isfinite(normalized).all() or float(np.max(np.abs(normalized))) > 1.001:
            self._record_failure("RESAMPLER-FORMAT-RANGE")
            raise InputResamplerError("RESAMPLER-FORMAT-RANGE")
        return normalized

    def _record_failure(self, code: str) -> None:
        with self._lock:
            self._failures += 1
            self._last_error_code = code


__all__ = [
    "InputResamplerConfig",
    "InputResamplerError",
    "TargetInputResampler",
]
