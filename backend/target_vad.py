"""Auditable local Silero VAD provider for the isolated target voice chain.

The provider is intentionally narrower than the legacy VAD engine.  It owns
only local ONNX asset verification, bounded stream state, speech hysteresis,
and stop evidence.  It never opens a microphone, downloads an asset, persists
audio, or imports the legacy application graph.
"""

from __future__ import annotations

import hashlib
import json
import math
import threading
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Protocol, Sequence
from urllib.parse import urlsplit

import numpy as np


_PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_VAD_ASSET_DIR = _PROJECT_ROOT / "models" / "voice" / "vad"
DEFAULT_VAD_MANIFEST_PATH = (
    _PROJECT_ROOT / "assets" / "voice" / "vad" / "silero-vad-v6.2.1.manifest.json"
)
_REQUIRED_INPUTS = frozenset({"input", "state", "sr"})


class VADProviderError(RuntimeError):
    """Stable, fail-closed error from the target VAD provider."""

    def __init__(self, code: str, detail: str = "") -> None:
        self.code = str(code)[:160]
        self.detail = str(detail)[:400]
        super().__init__(self.code + (": " + self.detail if self.detail else ""))


class VADProviderState(str, Enum):
    NEW = "new"
    STARTING = "starting"
    READY = "ready"
    STOPPED = "stopped"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class VADAssetSpec:
    filename: str
    version: str
    source: str
    license: str
    sha256: str
    input_contract: str
    output_contract: str

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "VADAssetSpec":
        fields = tuple(cls.__dataclass_fields__)
        missing = [name for name in fields if name not in raw]
        if missing:
            raise VADProviderError("VAD-ASSET-MANIFEST-INVALID", "missing:" + ",".join(missing))
        spec = cls(**{name: str(raw[name]) for name in fields})
        if not spec.filename or Path(spec.filename).name != spec.filename:
            raise VADProviderError("VAD-ASSET-MANIFEST-INVALID", "unsafe_filename")
        if len(spec.sha256) != 64 or any(char not in "0123456789abcdefABCDEF" for char in spec.sha256):
            raise VADProviderError("VAD-ASSET-MANIFEST-INVALID", "invalid_sha256")
        if urlsplit(spec.source).scheme.lower() != "https":
            raise VADProviderError("VAD-ASSET-MANIFEST-INVALID", "source_must_use_https")
        if not spec.license.strip() or not spec.version.strip():
            raise VADProviderError("VAD-ASSET-MANIFEST-INVALID", "missing_license_or_version")
        return spec


def load_vad_asset_spec(manifest_path: Path | str) -> VADAssetSpec:
    """Load one declared VAD asset without opening the network."""
    path = Path(manifest_path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise VADProviderError("VAD-ASSET-MANIFEST-UNREADABLE", type(exc).__name__) from exc
    if not isinstance(raw, Mapping) or raw.get("schema_version") != 1:
        raise VADProviderError("VAD-ASSET-MANIFEST-INVALID", "schema_version")
    assets = raw.get("assets")
    if not isinstance(assets, list) or len(assets) != 1 or not isinstance(assets[0], Mapping):
        raise VADProviderError("VAD-ASSET-MANIFEST-INVALID", "expected_one_asset")
    return VADAssetSpec.from_mapping(assets[0])


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise VADProviderError("VAD-ASSET-UNREADABLE", type(exc).__name__) from exc
    return digest.hexdigest()


def verify_vad_asset(asset_dir: Path | str, manifest_path: Path | str) -> tuple[VADAssetSpec, Path]:
    """Verify the declared local model byte-for-byte before creating ONNX state."""
    spec = load_vad_asset_spec(manifest_path)
    directory = Path(asset_dir)
    path = directory / spec.filename
    if not path.is_file() or path.stat().st_size <= 0:
        raise VADProviderError("VAD-ASSET-MISSING", spec.filename)
    actual = _sha256_file(path)
    if actual.lower() != spec.sha256.lower():
        raise VADProviderError("VAD-ASSET-SHA256-MISMATCH", spec.filename)
    return spec, path


@dataclass(frozen=True, slots=True)
class SileroVADConfig:
    """Non-persistent input/VAD configuration for one target runtime."""

    asset_dir: Path = field(default_factory=lambda: DEFAULT_VAD_ASSET_DIR)
    manifest_path: Path = field(default_factory=lambda: DEFAULT_VAD_MANIFEST_PATH)
    sample_rate: int = 16_000
    window_samples: int = 512
    context_samples: int = 64
    state_shape: tuple[int, int, int] = (2, 1, 128)
    onset_threshold: float = 0.50
    offset_threshold: float = 0.35
    min_speech_windows: int = 2  # N.E.K.O. 对齐: >=200ms 最短语音 (100ms/window)
    min_silence_windows: int = 3
    max_input_samples: int = 3_200
    execution_providers: tuple[str, ...] = ("CPUExecutionProvider",)

    def __post_init__(self) -> None:
        object.__setattr__(self, "asset_dir", Path(self.asset_dir))
        object.__setattr__(self, "manifest_path", Path(self.manifest_path))
        if self.sample_rate != 16_000:
            raise ValueError("Silero VAD requires sample_rate=16000")
        if self.window_samples <= 0 or self.context_samples <= 0:
            raise ValueError("window and context sizes must be positive")
        if self.context_samples >= self.window_samples:
            raise ValueError("context_samples must be smaller than window_samples")
        if tuple(self.state_shape) != (2, 1, 128):
            raise ValueError("Silero VAD requires state_shape=(2, 1, 128)")
        if not 0.0 <= self.offset_threshold < self.onset_threshold <= 1.0:
            raise ValueError("thresholds must satisfy 0 <= offset < onset <= 1")
        if self.min_speech_windows <= 0 or self.min_silence_windows <= 0:
            raise ValueError("speech and silence window counts must be positive")
        if self.max_input_samples < self.window_samples:
            raise ValueError("max_input_samples must cover one VAD window")
        if not self.execution_providers or any(not str(value).strip() for value in self.execution_providers):
            raise ValueError("execution_providers must not be empty")

    def to_dict(self) -> dict:
        return {
            "asset_dir": str(self.asset_dir),
            "manifest_path": str(self.manifest_path),
            "sample_rate": self.sample_rate,
            "window_samples": self.window_samples,
            "context_samples": self.context_samples,
            "state_shape": list(self.state_shape),
            "onset_threshold": self.onset_threshold,
            "offset_threshold": self.offset_threshold,
            "min_speech_windows": self.min_speech_windows,
            "min_silence_windows": self.min_silence_windows,
            "max_input_samples": self.max_input_samples,
            "execution_providers": list(self.execution_providers),
        }


class _SessionFactory(Protocol):
    def __call__(self, model_path: Path, providers: Sequence[str]) -> Any: ...


def _default_session_factory(model_path: Path, providers: Sequence[str]) -> Any:
    try:
        import onnxruntime as ort
    except ImportError as exc:
        raise VADProviderError("VAD-ONNXRUNTIME-MISSING") from exc
    return ort.InferenceSession(str(model_path), providers=list(providers))


class TargetVADProvider:
    """Stateful local 16 kHz mono Silero VAD with observable stop semantics."""

    def __init__(
        self,
        config: Optional[SileroVADConfig] = None,
        *,
        session_factory: Optional[_SessionFactory] = None,
    ) -> None:
        self.config = config or SileroVADConfig()
        self._session_factory = session_factory or _default_session_factory
        self._lock = threading.RLock()
        self._stopped = threading.Event()
        self._stopped.set()
        self._state = VADProviderState.NEW
        self._session: Any = None
        self._spec: Optional[VADAssetSpec] = None
        self._asset_path: Optional[Path] = None
        self._last_error_code: Optional[str] = None
        self._last_error_detail = ""
        self._reset_stream_locked()
        self._detect_calls = 0
        self._windows = 0
        self._speech_starts = 0
        self._speech_ends = 0
        self._format_failures = 0
        self._inference_failures = 0
        self._last_probability: Optional[float] = None

    @property
    def state(self) -> VADProviderState:
        with self._lock:
            return self._state

    def start(self) -> None:
        """Verify the local asset and create one CPU ONNX session."""
        with self._lock:
            if self._state is VADProviderState.READY:
                return
            if self._state is VADProviderState.STARTING:
                raise VADProviderError("VAD-START-IN-PROGRESS")
            self._state = VADProviderState.STARTING
            self._stopped.clear()
            self._last_error_code = None
            self._last_error_detail = ""
        try:
            spec, path = verify_vad_asset(self.config.asset_dir, self.config.manifest_path)
            session = self._session_factory(path, self.config.execution_providers)
            self._validate_session(session)
        except VADProviderError as exc:
            self._fail(exc.code, exc.detail)
            raise
        except Exception as exc:
            error = VADProviderError("VAD-SESSION-START-FAILED", type(exc).__name__)
            self._fail(error.code, error.detail)
            raise error from exc
        with self._lock:
            self._session = session
            self._spec = spec
            self._asset_path = path
            self._reset_stream_locked()
            self._state = VADProviderState.READY
            self._stopped.clear()

    def stop(self, reason: str = "shutdown") -> None:
        """Discard only in-memory inference state and expose immediate stop proof."""
        del reason
        with self._lock:
            self._session = None
            self._reset_stream_locked()
            self._state = VADProviderState.STOPPED
            self._stopped.set()

    close = stop

    def wait_stopped(self, timeout_s: float) -> bool:
        if float(timeout_s) < 0:
            raise ValueError("timeout_s must not be negative")
        return self._stopped.wait(float(timeout_s))

    def reset_stream(self) -> None:
        """Reset temporary VAD context without touching assets or persistent data."""
        with self._lock:
            self._reset_stream_locked()

    def detect_speech(self, audio: Any, sample_rate: int) -> bool:
        """Return stateful speech activity for one bounded float32 mono frame."""
        samples = self._normalize_input(audio, sample_rate)
        with self._lock:
            if self._state is not VADProviderState.READY or self._session is None:
                raise VADProviderError("VAD-NOT-READY", self._state.value)
            self._detect_calls += 1
            self._pending = np.concatenate((self._pending, samples))
            while self._pending.size >= self.config.window_samples:
                window = self._pending[: self.config.window_samples]
                self._pending = self._pending[self.config.window_samples :]
                try:
                    outputs = self._session.run(
                        None,
                        {
                            "input": np.concatenate((self._context, window))[None].astype(np.float32),
                            "state": self._lstm_state,
                            "sr": self._sample_rate_tensor,
                        },
                    )
                    probability, state = self._parse_outputs(outputs)
                except VADProviderError as exc:
                    self._inference_failures += 1
                    self._fail_locked(exc.code, exc.detail)
                    raise
                except Exception as exc:
                    self._inference_failures += 1
                    self._fail_locked("VAD-INFERENCE-FAILED", type(exc).__name__)
                    raise VADProviderError("VAD-INFERENCE-FAILED", type(exc).__name__) from exc
                self._lstm_state = state
                self._context = window[-self.config.context_samples :].copy()
                self._last_probability = probability
                self._windows += 1
                self._apply_probability_locked(probability)
            return self._speech_active

    def health(self) -> dict:
        """Return redaction-safe operational facts; raw audio is never retained."""
        with self._lock:
            spec = self._spec
            return {
                "state": self._state.value,
                "ready": self._state is VADProviderState.READY,
                "stopped": self._stopped.is_set(),
                "asset": {
                    "filename": spec.filename if spec else None,
                    "version": spec.version if spec else None,
                    "license": spec.license if spec else None,
                    "verified": self._asset_path is not None and self._state is not VADProviderState.FAILED,
                },
                "speech_active": self._speech_active,
                "last_probability": self._last_probability,
                "last_error_code": self._last_error_code,
                "metrics": {
                    "detect_calls": self._detect_calls,
                    "windows": self._windows,
                    "speech_starts": self._speech_starts,
                    "speech_ends": self._speech_ends,
                    "format_failures": self._format_failures,
                    "inference_failures": self._inference_failures,
                    "pending_samples": int(self._pending.size),
                },
            }

    def _normalize_input(self, audio: Any, sample_rate: int) -> np.ndarray:
        if int(sample_rate) != self.config.sample_rate:
            self._record_format_failure("VAD-SAMPLE-RATE")
            raise VADProviderError("VAD-SAMPLE-RATE", str(sample_rate))
        if isinstance(audio, (bytes, bytearray, memoryview)):
            self._record_format_failure("VAD-FORMAT-DTYPE")
            raise VADProviderError("VAD-FORMAT-DTYPE", "expected_float32")
        try:
            value = np.asarray(audio)
        except Exception as exc:
            self._record_format_failure("VAD-FORMAT-INVALID")
            raise VADProviderError("VAD-FORMAT-INVALID", type(exc).__name__) from exc
        if value.ndim == 2:
            if value.shape[1] != 1:
                self._record_format_failure("VAD-FORMAT-CHANNELS")
                raise VADProviderError("VAD-FORMAT-CHANNELS", str(value.shape[1]))
            value = value[:, 0]
        if value.ndim != 1:
            self._record_format_failure("VAD-FORMAT-SHAPE")
            raise VADProviderError("VAD-FORMAT-SHAPE", str(value.ndim))
        if value.dtype.kind != "f":
            self._record_format_failure("VAD-FORMAT-DTYPE")
            raise VADProviderError("VAD-FORMAT-DTYPE", str(value.dtype))
        if value.size > self.config.max_input_samples:
            self._record_format_failure("VAD-FRAME-TOO-LARGE")
            raise VADProviderError("VAD-FRAME-TOO-LARGE", str(value.size))
        normalized = np.ascontiguousarray(value, dtype=np.float32)
        if not np.isfinite(normalized).all():
            self._record_format_failure("VAD-FORMAT-NONFINITE")
            raise VADProviderError("VAD-FORMAT-NONFINITE")
        if normalized.size and float(np.max(np.abs(normalized))) > 1.001:
            self._record_format_failure("VAD-FORMAT-RANGE")
            raise VADProviderError("VAD-FORMAT-RANGE")
        return normalized

    @staticmethod
    def _validate_session(session: Any) -> None:
        get_inputs = getattr(session, "get_inputs", None)
        if not callable(get_inputs):
            return
        try:
            names = {str(getattr(item, "name", "")) for item in get_inputs()}
        except Exception as exc:
            raise VADProviderError("VAD-SESSION-CONTRACT-INVALID", type(exc).__name__) from exc
        missing = sorted(_REQUIRED_INPUTS - names)
        if missing:
            raise VADProviderError("VAD-SESSION-CONTRACT-INVALID", "missing:" + ",".join(missing))

    def _parse_outputs(self, outputs: Any) -> tuple[float, np.ndarray]:
        if not isinstance(outputs, (list, tuple)) or len(outputs) < 2:
            raise VADProviderError("VAD-OUTPUT-INVALID", "missing_probability_or_state")
        try:
            probability = float(np.asarray(outputs[0]).reshape(-1)[0])
            state = np.asarray(outputs[1], dtype=np.float32)
        except Exception as exc:
            raise VADProviderError("VAD-OUTPUT-INVALID", type(exc).__name__) from exc
        if not math.isfinite(probability) or not 0.0 <= probability <= 1.0:
            raise VADProviderError("VAD-OUTPUT-INVALID", "probability")
        if tuple(state.shape) != self.config.state_shape:
            raise VADProviderError("VAD-OUTPUT-INVALID", "state_shape")
        return probability, state

    def _apply_probability_locked(self, probability: float) -> None:
        if probability >= self.config.onset_threshold:
            self._speech_windows += 1
            self._silence_windows = 0
            if not self._speech_active and self._speech_windows >= self.config.min_speech_windows:
                self._speech_active = True
                self._speech_starts += 1
            return
        if probability <= self.config.offset_threshold:
            self._speech_windows = 0
            if self._speech_active:
                self._silence_windows += 1
                if self._silence_windows >= self.config.min_silence_windows:
                    self._speech_active = False
                    self._speech_ends += 1
            return
        self._speech_windows = 0
        self._silence_windows = 0

    def _reset_stream_locked(self) -> None:
        self._lstm_state = np.zeros(self.config.state_shape, dtype=np.float32)
        self._context = np.zeros(self.config.context_samples, dtype=np.float32)
        self._pending = np.empty(0, dtype=np.float32)
        self._sample_rate_tensor = np.asarray(self.config.sample_rate, dtype=np.int64)
        self._speech_active = False
        self._speech_windows = 0
        self._silence_windows = 0

    def _record_format_failure(self, code: str) -> None:
        with self._lock:
            self._format_failures += 1
            self._last_error_code = code
            self._last_error_detail = ""

    def _fail(self, code: str, detail: str = "") -> None:
        with self._lock:
            self._fail_locked(code, detail)

    def _fail_locked(self, code: str, detail: str = "") -> None:
        self._session = None
        self._state = VADProviderState.FAILED
        self._last_error_code = code
        self._last_error_detail = detail
        self._reset_stream_locked()
        self._stopped.set()


__all__ = [
    "DEFAULT_VAD_ASSET_DIR",
    "DEFAULT_VAD_MANIFEST_PATH",
    "SileroVADConfig",
    "TargetVADProvider",
    "VADAssetSpec",
    "VADProviderError",
    "VADProviderState",
    "load_vad_asset_spec",
    "verify_vad_asset",
]
