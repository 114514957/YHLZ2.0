"""Verified local Sherpa-ONNX online ASR provider for the target chain.

The provider owns one bounded, CPU-only online recognizer. It never opens a
microphone, downloads weights, stores PCM, logs transcripts, or imports the
legacy ASR graph. Callers feed already-normalized 16 kHz mono float32 PCM and
receive only in-memory partial/final updates.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence
from urllib.parse import urlsplit

import numpy as np

from backend.asr_provider_port import (
    ASRProviderError,
    ASRProviderState,
    ASRStreamUpdate,
    ASRStreamUpdateKind,
)
from backend.target_chain import CancellationSignal


_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_ASR_DIRECTORY = "sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20"
DEFAULT_ASR_ASSET_DIR = _PROJECT_ROOT / "models" / "voice" / "asr" / _DEFAULT_ASR_DIRECTORY
DEFAULT_ASR_MANIFEST_PATH = (
    _PROJECT_ROOT
    / "assets"
    / "voice"
    / "asr"
    / (_DEFAULT_ASR_DIRECTORY + ".manifest.json")
)


@dataclass(frozen=True, slots=True)
class ASRRuntimeFile:
    """One local runtime file declared by the tracked asset manifest."""

    filename: str
    bytes: int
    sha256: str

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "ASRRuntimeFile":
        try:
            filename = str(raw["filename"])
            byte_count = int(raw["bytes"])
            sha256 = str(raw["sha256"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ASRProviderError("ASR-ASSET-MANIFEST-INVALID", "runtime_file") from exc
        if not filename or Path(filename).name != filename:
            raise ASRProviderError("ASR-ASSET-MANIFEST-INVALID", "unsafe_runtime_filename")
        if byte_count <= 0:
            raise ASRProviderError("ASR-ASSET-MANIFEST-INVALID", "runtime_file_size")
        if len(sha256) != 64 or any(item not in "0123456789abcdefABCDEF" for item in sha256):
            raise ASRProviderError("ASR-ASSET-MANIFEST-INVALID", "runtime_file_sha256")
        return cls(filename=filename, bytes=byte_count, sha256=sha256.lower())


@dataclass(frozen=True, slots=True)
class SherpaASRAssetSpec:
    """Verified, local-only model description used by the online provider."""

    directory: str
    version: str
    source: str
    model_origin: str
    license: str
    archive_filename: str
    archive_bytes: int
    archive_sha256: str
    runtime_files: tuple[ASRRuntimeFile, ...]


def _require_https(value: str, field_name: str) -> str:
    if urlsplit(value).scheme.lower() != "https":
        raise ASRProviderError("ASR-ASSET-MANIFEST-INVALID", field_name + "_must_use_https")
    return value


def load_sherpa_asr_asset_spec(manifest_path: Path | str) -> SherpaASRAssetSpec:
    """Read one asset manifest without accessing the network or runtime model."""
    path = Path(manifest_path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ASRProviderError("ASR-ASSET-MANIFEST-UNREADABLE", type(exc).__name__) from exc
    if not isinstance(raw, Mapping) or raw.get("schema_version") != 1:
        raise ASRProviderError("ASR-ASSET-MANIFEST-INVALID", "schema_version")
    provider = raw.get("provider")
    if not isinstance(provider, Mapping) or provider.get("id") != "sherpa-onnx-online-transducer":
        raise ASRProviderError("ASR-ASSET-MANIFEST-INVALID", "provider")
    assets = raw.get("assets")
    if not isinstance(assets, list) or len(assets) != 1 or not isinstance(assets[0], Mapping):
        raise ASRProviderError("ASR-ASSET-MANIFEST-INVALID", "expected_one_asset")
    asset = assets[0]
    try:
        directory = str(asset["directory"])
        version = str(asset["version"])
        source = _require_https(str(asset["source"]), "source")
        model_origin = _require_https(str(asset["model_origin"]), "model_origin")
        license_name = str(asset["license"])
        archive = asset["archive"]
        runtime_files_raw = asset["runtime_files"]
    except (KeyError, TypeError, ValueError) as exc:
        raise ASRProviderError("ASR-ASSET-MANIFEST-INVALID", "asset_fields") from exc
    if not directory or Path(directory).name != directory:
        raise ASRProviderError("ASR-ASSET-MANIFEST-INVALID", "unsafe_directory")
    if not version or not license_name:
        raise ASRProviderError("ASR-ASSET-MANIFEST-INVALID", "version_or_license")
    if not isinstance(archive, Mapping):
        raise ASRProviderError("ASR-ASSET-MANIFEST-INVALID", "archive")
    try:
        archive_filename = str(archive["filename"])
        archive_bytes = int(archive["bytes"])
        archive_sha256 = str(archive["sha256"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ASRProviderError("ASR-ASSET-MANIFEST-INVALID", "archive_fields") from exc
    if not archive_filename or Path(archive_filename).name != archive_filename or archive_bytes <= 0:
        raise ASRProviderError("ASR-ASSET-MANIFEST-INVALID", "archive_filename_or_size")
    if len(archive_sha256) != 64 or any(item not in "0123456789abcdefABCDEF" for item in archive_sha256):
        raise ASRProviderError("ASR-ASSET-MANIFEST-INVALID", "archive_sha256")
    if not isinstance(runtime_files_raw, list) or not runtime_files_raw:
        raise ASRProviderError("ASR-ASSET-MANIFEST-INVALID", "runtime_files")
    runtime_files = tuple(ASRRuntimeFile.from_mapping(item) for item in runtime_files_raw if isinstance(item, Mapping))
    if len(runtime_files) != len(runtime_files_raw):
        raise ASRProviderError("ASR-ASSET-MANIFEST-INVALID", "runtime_file_shape")
    names = {item.filename for item in runtime_files}
    required = {
        "encoder-epoch-99-avg-1.int8.onnx",
        "decoder-epoch-99-avg-1.int8.onnx",
        "joiner-epoch-99-avg-1.int8.onnx",
        "tokens.txt",
    }
    if names != required:
        raise ASRProviderError("ASR-ASSET-MANIFEST-INVALID", "runtime_file_set")
    return SherpaASRAssetSpec(
        directory=directory,
        version=version,
        source=source,
        model_origin=model_origin,
        license=license_name,
        archive_filename=archive_filename,
        archive_bytes=archive_bytes,
        archive_sha256=archive_sha256.lower(),
        runtime_files=runtime_files,
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise ASRProviderError("ASR-ASSET-UNREADABLE", type(exc).__name__) from exc
    return digest.hexdigest()


def verify_sherpa_asr_asset(
    asset_dir: Path | str,
    manifest_path: Path | str,
) -> tuple[SherpaASRAssetSpec, Path]:
    """Verify every execution file before the native runtime can load it."""
    spec = load_sherpa_asr_asset_spec(manifest_path)
    directory = Path(asset_dir)
    if directory.name != spec.directory:
        raise ASRProviderError("ASR-ASSET-DIRECTORY-MISMATCH", directory.name)
    if not directory.is_dir():
        raise ASRProviderError("ASR-ASSET-MISSING", spec.directory)
    for item in spec.runtime_files:
        path = directory / item.filename
        if not path.is_file():
            raise ASRProviderError("ASR-ASSET-MISSING", item.filename)
        if path.stat().st_size != item.bytes:
            raise ASRProviderError("ASR-ASSET-SIZE-MISMATCH", item.filename)
        if _sha256_file(path).lower() != item.sha256:
            raise ASRProviderError("ASR-ASSET-SHA256-MISMATCH", item.filename)
    return spec, directory


def _default_available_memory_bytes() -> int:
    """Return currently available physical memory without adding a dependency."""
    if os.name == "nt":
        try:
            import ctypes

            class _MemoryStatusEx(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            status = _MemoryStatusEx()
            status.dwLength = ctypes.sizeof(status)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return int(status.ullAvailPhys)
        except Exception:
            return 0
    try:
        return int(os.sysconf("SC_AVPHYS_PAGES")) * int(os.sysconf("SC_PAGE_SIZE"))
    except (AttributeError, OSError, ValueError):
        return 0


@dataclass(frozen=True, slots=True)
class SherpaOnlineASRConfig:
    """Non-persistent settings for one local online recognizer."""

    asset_dir: Path = field(default_factory=lambda: DEFAULT_ASR_ASSET_DIR)
    manifest_path: Path = field(default_factory=lambda: DEFAULT_ASR_MANIFEST_PATH)
    sample_rate: int = 16_000
    channels: int = 1
    num_threads: int = 2
    max_chunk_samples: int = 3_200
    max_decode_steps: int = 64
    partial_interval_ms: int = 200
    min_available_memory_bytes: int = 2 * 1024 * 1024 * 1024

    def __post_init__(self) -> None:
        object.__setattr__(self, "asset_dir", Path(self.asset_dir))
        object.__setattr__(self, "manifest_path", Path(self.manifest_path))
        if self.sample_rate != 16_000 or self.channels != 1:
            raise ValueError("Sherpa online ASR requires 16000 Hz mono input")
        if self.num_threads <= 0 or self.max_chunk_samples <= 0 or self.max_decode_steps <= 0:
            raise ValueError("thread and bounded decode settings must be positive")
        if self.partial_interval_ms < 0 or self.min_available_memory_bytes < 0:
            raise ValueError("resource and partial settings must not be negative")

    def to_dict(self) -> dict:
        return {
            "provider": "sherpa-onnx-online-transducer",
            "sample_rate": self.sample_rate,
            "channels": self.channels,
            "num_threads": self.num_threads,
            "max_chunk_samples": self.max_chunk_samples,
            "max_decode_steps": self.max_decode_steps,
            "partial_interval_ms": self.partial_interval_ms,
            "min_available_memory_bytes": self.min_available_memory_bytes,
        }


@dataclass(slots=True)
class _StreamState:
    stream: Any
    generation: int
    created_at: float
    received_samples: int = 0
    decode_calls: int = 0
    last_text: str = ""
    last_partial_at: float = 0.0
    first_audio_at: Optional[float] = None


RecognizerFactory = Callable[[SherpaOnlineASRConfig, Path], Any]
MemoryReader = Callable[[], int]


def _default_recognizer_factory(config: SherpaOnlineASRConfig, asset_dir: Path) -> Any:
    try:
        import sherpa_onnx
    except ImportError as exc:
        raise ASRProviderError("ASR-SHERPA-RUNTIME-MISSING") from exc
    return sherpa_onnx.OnlineRecognizer.from_transducer(
        tokens=str(asset_dir / "tokens.txt"),
        encoder=str(asset_dir / "encoder-epoch-99-avg-1.int8.onnx"),
        decoder=str(asset_dir / "decoder-epoch-99-avg-1.int8.onnx"),
        joiner=str(asset_dir / "joiner-epoch-99-avg-1.int8.onnx"),
        num_threads=config.num_threads,
        provider="cpu",
        sample_rate=config.sample_rate,
        feature_dim=80,
        decoding_method="greedy_search",
    )


class SherpaOnlineASRProvider:
    """One verified CPU streaming recognizer with observable cancellation."""

    provider_id = "sherpa-onnx-online-transducer"

    def __init__(
        self,
        config: Optional[SherpaOnlineASRConfig] = None,
        *,
        recognizer_factory: Optional[RecognizerFactory] = None,
        available_memory_reader: Optional[MemoryReader] = None,
    ) -> None:
        self.config = config or SherpaOnlineASRConfig()
        self._recognizer_factory = recognizer_factory or _default_recognizer_factory
        self._available_memory_reader = available_memory_reader or _default_available_memory_bytes
        self._lock = threading.RLock()
        self._state = ASRProviderState.STOPPED
        self._stopped = threading.Event()
        self._stopped.set()
        self._recognizer: Any = None
        self._asset_spec: Optional[SherpaASRAssetSpec] = None
        self._asset_dir: Optional[Path] = None
        self._streams: dict[str, _StreamState] = {}
        self._last_error_code: Optional[str] = None
        self._last_available_memory_bytes: Optional[int] = None
        self._load_ms: Optional[float] = None
        self._started_at: Optional[float] = None
        self._stream_opens = 0
        self._stream_finishes = 0
        self._push_calls = 0
        self._input_samples = 0
        self._decode_calls = 0
        self._partial_updates = 0
        self._final_updates = 0
        self._empty_updates = 0
        self._interrupts = 0
        self._cancelled_streams = 0
        self._format_failures = 0
        self._runtime_failures = 0

    @property
    def state(self) -> ASRProviderState:
        with self._lock:
            return self._state

    def start(self) -> None:
        """Verify local assets and create the native recognizer exactly once."""
        with self._lock:
            if self._state is ASRProviderState.READY:
                return
            if self._state is ASRProviderState.STARTING:
                raise ASRProviderError("ASR-START-IN-PROGRESS")
            self._state = ASRProviderState.STARTING
            self._last_error_code = None
            self._stopped.set()
        started = time.perf_counter()
        try:
            available = int(self._available_memory_reader())
            if available < 0:
                raise ASRProviderError("ASR-RESOURCE-BUDGET", "available_memory_invalid")
            if (
                self.config.min_available_memory_bytes > 0
                and available < self.config.min_available_memory_bytes
            ):
                raise ASRProviderError("ASR-RESOURCE-BUDGET", "available_memory_below_minimum")
            spec, asset_dir = verify_sherpa_asr_asset(
                self.config.asset_dir,
                self.config.manifest_path,
            )
            recognizer = self._recognizer_factory(self.config, asset_dir)
            if not callable(getattr(recognizer, "create_stream", None)):
                raise ASRProviderError("ASR-SHERPA-CONTRACT-INVALID", "create_stream")
        except ASRProviderError as exc:
            self._fail(exc.code)
            raise
        except Exception as exc:
            error = ASRProviderError("ASR-SHERPA-START-FAILED", type(exc).__name__)
            self._fail(error.code)
            raise error from exc
        with self._lock:
            self._recognizer = recognizer
            self._asset_spec = spec
            self._asset_dir = asset_dir
            self._last_available_memory_bytes = available
            self._load_ms = round((time.perf_counter() - started) * 1000, 3)
            self._started_at = time.monotonic()
            self._state = ASRProviderState.READY
            self._stopped.set()

    def open_stream(
        self,
        stream_id: str,
        generation: int,
        sample_rate: int,
        channels: int,
        signal: CancellationSignal,
    ) -> None:
        """Open one in-memory online stream; overlap is deliberately refused."""
        normalized_id = self._validate_stream_id(stream_id)
        if not isinstance(signal, CancellationSignal):
            raise TypeError("signal must be CancellationSignal")
        if int(generation) < 0:
            raise ASRProviderError("ASR-STREAM-GENERATION")
        if int(sample_rate) != self.config.sample_rate or int(channels) != self.config.channels:
            self._record_format_failure("ASR-STREAM-FORMAT")
            raise ASRProviderError("ASR-STREAM-FORMAT")
        if signal.is_cancelled():
            raise ASRProviderError("ASR-CANCELLED")
        with self._lock:
            self._require_ready_locked()
            if self._streams:
                raise ASRProviderError("ASR-STREAM-OVERLAP")
            try:
                stream = self._recognizer.create_stream()
            except Exception as exc:
                self._runtime_failures += 1
                self._last_error_code = "ASR-SHERPA-STREAM-CREATE-FAILED"
                raise ASRProviderError("ASR-SHERPA-STREAM-CREATE-FAILED", type(exc).__name__) from exc
            self._streams[normalized_id] = _StreamState(
                stream=stream,
                generation=int(generation),
                created_at=time.monotonic(),
            )
            self._stream_opens += 1
            self._stopped.clear()

    def push_audio(
        self,
        stream_id: str,
        samples: Any,
        sample_rate: int,
        signal: CancellationSignal,
    ) -> Sequence[ASRStreamUpdate]:
        """Push one bounded PCM block and return changed partial text only."""
        normalized_id = self._validate_stream_id(stream_id)
        if not isinstance(signal, CancellationSignal):
            raise TypeError("signal must be CancellationSignal")
        audio = self._normalize_audio(samples, sample_rate)
        with self._lock:
            state = self._require_stream_locked(normalized_id)
            if signal.is_cancelled():
                self._discard_stream_locked(normalized_id, cancelled=True)
                return (self._cancelled_update(normalized_id, state),)
            try:
                state.stream.accept_waveform(self.config.sample_rate, audio)
                if state.first_audio_at is None:
                    state.first_audio_at = time.monotonic()
                self._push_calls += 1
                state.received_samples += int(audio.size)
                self._input_samples += int(audio.size)
                steps = 0
                while self._recognizer.is_ready(state.stream):
                    if steps >= self.config.max_decode_steps:
                        raise ASRProviderError("ASR-SHERPA-DECODE-UNBOUNDED")
                    self._recognizer.decode_stream(state.stream)
                    steps += 1
                    state.decode_calls += 1
                    self._decode_calls += 1
                result = self._read_result_locked(state)
            except ASRProviderError:
                self._discard_stream_locked(normalized_id, cancelled=False)
                raise
            except Exception as exc:
                self._runtime_failures += 1
                self._last_error_code = "ASR-SHERPA-PUSH-FAILED"
                self._discard_stream_locked(normalized_id, cancelled=False)
                raise ASRProviderError("ASR-SHERPA-PUSH-FAILED", type(exc).__name__) from exc
            if not result or result == state.last_text:
                return ()
            now = time.monotonic()
            if (now - state.last_partial_at) * 1000 < self.config.partial_interval_ms:
                return ()
            state.last_text = result
            state.last_partial_at = now
            self._partial_updates += 1
            return (
                ASRStreamUpdate(
                    stream_id=normalized_id,
                    generation=state.generation,
                    kind=ASRStreamUpdateKind.PARTIAL,
                    text=result,
                    elapsed_ms=round((now - state.created_at) * 1000, 3),
                ),
            )

    def finish_stream(
        self,
        stream_id: str,
        signal: CancellationSignal,
    ) -> ASRStreamUpdate:
        """Flush one stream and return one final or empty result."""
        normalized_id = self._validate_stream_id(stream_id)
        if not isinstance(signal, CancellationSignal):
            raise TypeError("signal must be CancellationSignal")
        with self._lock:
            state = self._require_stream_locked(normalized_id)
            if signal.is_cancelled():
                self._discard_stream_locked(normalized_id, cancelled=True)
                return self._cancelled_update(normalized_id, state)
            try:
                state.stream.input_finished()
                steps = 0
                while self._recognizer.is_ready(state.stream):
                    if steps >= self.config.max_decode_steps:
                        raise ASRProviderError("ASR-SHERPA-DECODE-UNBOUNDED")
                    self._recognizer.decode_stream(state.stream)
                    steps += 1
                    state.decode_calls += 1
                    self._decode_calls += 1
                text = self._read_result_locked(state)
            except ASRProviderError:
                self._discard_stream_locked(normalized_id, cancelled=False)
                raise
            except Exception as exc:
                self._runtime_failures += 1
                self._last_error_code = "ASR-SHERPA-FINISH-FAILED"
                self._discard_stream_locked(normalized_id, cancelled=False)
                raise ASRProviderError("ASR-SHERPA-FINISH-FAILED", type(exc).__name__) from exc
            elapsed = round((time.monotonic() - state.created_at) * 1000, 3)
            self._discard_stream_locked(normalized_id, cancelled=False)
            if text:
                self._final_updates += 1
                return ASRStreamUpdate(
                    stream_id=normalized_id,
                    generation=state.generation,
                    kind=ASRStreamUpdateKind.FINAL,
                    text=text,
                    elapsed_ms=elapsed,
                )
            self._empty_updates += 1
            return ASRStreamUpdate(
                stream_id=normalized_id,
                generation=state.generation,
                kind=ASRStreamUpdateKind.EMPTY,
                elapsed_ms=elapsed,
            )

    def interrupt(self, reason: str = "interrupt") -> None:
        """Release active stream state; model assets and persistent data stay untouched."""
        del reason
        with self._lock:
            self._interrupts += 1
            if self._streams:
                self._cancelled_streams += len(self._streams)
            self._streams.clear()
            self._stopped.set()

    def wait_stopped(self, timeout_s: float) -> bool:
        if float(timeout_s) < 0:
            raise ValueError("timeout_s must not be negative")
        return self._stopped.wait(float(timeout_s))

    def stop(self, reason: str = "shutdown") -> None:
        """Release only the in-process recognizer and ephemeral stream state."""
        del reason
        with self._lock:
            self._streams.clear()
            self._recognizer = None
            self._state = ASRProviderState.STOPPED
            self._stopped.set()

    close = stop

    def health(self) -> dict:
        """Return safe metrics and verification state without audio or text."""
        with self._lock:
            spec = self._asset_spec
            available_memory = self._last_available_memory_bytes
            if available_memory is None:
                try:
                    available_memory = int(self._available_memory_reader())
                except Exception:
                    available_memory = None
            return {
                "provider_id": self.provider_id,
                "state": self._state.value,
                "available": self._state is ASRProviderState.READY,
                "local_only": True,
                "streaming": True,
                "model_loaded": self._recognizer is not None,
                "stopped": self._stopped.is_set(),
                "last_error_code": self._last_error_code,
                "asset": {
                    "directory": spec.directory if spec else None,
                    "version": spec.version if spec else None,
                    "license": spec.license if spec else None,
                    "verified": self._asset_dir is not None and self._state is not ASRProviderState.FAILED,
                },
                "resource": {
                    "available_memory_bytes": available_memory,
                    "minimum_available_memory_bytes": self.config.min_available_memory_bytes,
                    "load_ms": self._load_ms,
                },
                "metrics": {
                    "active_streams": len(self._streams),
                    "stream_opens": self._stream_opens,
                    "stream_finishes": self._stream_finishes,
                    "push_calls": self._push_calls,
                    "input_samples": self._input_samples,
                    "decode_calls": self._decode_calls,
                    "partial_updates": self._partial_updates,
                    "final_updates": self._final_updates,
                    "empty_updates": self._empty_updates,
                    "interrupts": self._interrupts,
                    "cancelled_streams": self._cancelled_streams,
                    "format_failures": self._format_failures,
                    "runtime_failures": self._runtime_failures,
                },
            }

    def _require_ready_locked(self) -> None:
        if self._state is not ASRProviderState.READY or self._recognizer is None:
            raise ASRProviderError("ASR-NOT-READY", self._state.value)

    def _require_stream_locked(self, stream_id: str) -> _StreamState:
        self._require_ready_locked()
        state = self._streams.get(stream_id)
        if state is None:
            raise ASRProviderError("ASR-STREAM-NOT-FOUND")
        return state

    def _discard_stream_locked(self, stream_id: str, *, cancelled: bool) -> None:
        state = self._streams.pop(stream_id, None)
        if state is None:
            return
        if cancelled:
            self._cancelled_streams += 1
        else:
            self._stream_finishes += 1
        if not self._streams:
            self._stopped.set()

    @staticmethod
    def _validate_stream_id(stream_id: str) -> str:
        value = str(stream_id).strip()
        if not value or len(value) > 160:
            raise ASRProviderError("ASR-STREAM-ID-INVALID")
        return value

    def _normalize_audio(self, samples: Any, sample_rate: int) -> np.ndarray:
        if int(sample_rate) != self.config.sample_rate:
            self._record_format_failure("ASR-STREAM-SAMPLE-RATE")
            raise ASRProviderError("ASR-STREAM-SAMPLE-RATE", str(sample_rate))
        if isinstance(samples, (bytes, bytearray, memoryview)):
            self._record_format_failure("ASR-STREAM-FORMAT-DTYPE")
            raise ASRProviderError("ASR-STREAM-FORMAT-DTYPE", "expected_float32")
        try:
            audio = np.asarray(samples)
        except Exception as exc:
            self._record_format_failure("ASR-STREAM-FORMAT-INVALID")
            raise ASRProviderError("ASR-STREAM-FORMAT-INVALID", type(exc).__name__) from exc
        if audio.ndim == 2:
            if audio.shape[1] != 1:
                self._record_format_failure("ASR-STREAM-FORMAT-CHANNELS")
                raise ASRProviderError("ASR-STREAM-FORMAT-CHANNELS", str(audio.shape[1]))
            audio = audio[:, 0]
        if audio.ndim != 1:
            self._record_format_failure("ASR-STREAM-FORMAT-SHAPE")
            raise ASRProviderError("ASR-STREAM-FORMAT-SHAPE", str(audio.ndim))
        if audio.dtype.kind != "f":
            self._record_format_failure("ASR-STREAM-FORMAT-DTYPE")
            raise ASRProviderError("ASR-STREAM-FORMAT-DTYPE", str(audio.dtype))
        if audio.size <= 0 or audio.size > self.config.max_chunk_samples:
            self._record_format_failure("ASR-STREAM-FRAME-SIZE")
            raise ASRProviderError("ASR-STREAM-FRAME-SIZE", str(audio.size))
        normalized = np.ascontiguousarray(audio, dtype=np.float32)
        if not np.isfinite(normalized).all():
            self._record_format_failure("ASR-STREAM-FORMAT-NONFINITE")
            raise ASRProviderError("ASR-STREAM-FORMAT-NONFINITE")
        if float(np.max(np.abs(normalized))) > 1.001:
            self._record_format_failure("ASR-STREAM-FORMAT-RANGE")
            raise ASRProviderError("ASR-STREAM-FORMAT-RANGE")
        return normalized

    def _read_result_locked(self, state: _StreamState) -> str:
        try:
            raw = self._recognizer.get_result(state.stream)
        except Exception as exc:
            raise ASRProviderError("ASR-SHERPA-RESULT-FAILED", type(exc).__name__) from exc
        if raw is None:
            return ""
        if isinstance(raw, str):
            return raw.strip()
        return str(getattr(raw, "text", raw) or "").strip()

    def _cancelled_update(self, stream_id: str, state: _StreamState) -> ASRStreamUpdate:
        return ASRStreamUpdate(
            stream_id=stream_id,
            generation=state.generation,
            kind=ASRStreamUpdateKind.CANCELLED,
            elapsed_ms=round((time.monotonic() - state.created_at) * 1000, 3),
        )

    def _record_format_failure(self, code: str) -> None:
        with self._lock:
            self._format_failures += 1
            self._last_error_code = code

    def _fail(self, code: str) -> None:
        with self._lock:
            self._recognizer = None
            self._streams.clear()
            self._state = ASRProviderState.FAILED
            self._last_error_code = code
            self._stopped.set()


__all__ = [
    "ASRRuntimeFile",
    "DEFAULT_ASR_ASSET_DIR",
    "DEFAULT_ASR_MANIFEST_PATH",
    "SherpaASRAssetSpec",
    "SherpaOnlineASRConfig",
    "SherpaOnlineASRProvider",
    "load_sherpa_asr_asset_spec",
    "verify_sherpa_asr_asset",
]
