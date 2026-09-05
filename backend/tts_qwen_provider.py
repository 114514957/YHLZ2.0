"""Isolated Qwen3-TTS adapter for the target ``TTSProviderPort``.

The legacy TTS engines expose whole-audio and fallback behaviour directly to
the application.  This module deliberately has a smaller responsibility: it
turns one ``faster-qwen3-tts`` pull generator into provider-neutral events and
keeps generation in a bounded, cancellable worker session.  It does not import
the production entry point, open an audio device, access ``memory`` or write
business data.

The Qwen generator accepts complete text before it starts producing audio.
Consequently this adapter accepts ``push_text`` deltas for the common control
surface but declares ``text_stream=False`` until a provider with genuine
incremental text-to-audio semantics is verified.
"""

from __future__ import annotations

import inspect
import logging
import queue
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Iterator, Mapping, Optional, Tuple

from backend.tts_provider_port import (
    PCMChunk,
    PCM_FORMAT,
    PCM_SAMPLE_RATE,
    TTSEventKind,
    TTSProviderCapabilities,
    TTSProviderEvent,
    TTSProviderPortError,
    TTSRequest,
)
from backend.tts_provider_worker import PersistentTTSProvider


logger = logging.getLogger(__name__)

QWEN_PROVIDER_ID = "qwen3-faster-customvoice"
_QUEUE_SENTINEL = object()
_TORCH_CACHE: Any = None
_TORCH_IMPORT_ATTEMPTED = False
_TORCH_CACHE_LOCK = threading.Lock()


class QwenTTSAdapterError(TTSProviderPortError):
    """Stable adapter error carrying a target-chain error code."""


@dataclass(frozen=True, slots=True)
class QwenTTSConfig:
    """Runtime-only configuration for one Qwen CustomVoice worker.

    ``model_dir`` is explicit on purpose.  The adapter never falls back to
    the old ``D:\\HF_Models`` path and never downloads missing files.
    """

    model_dir: Path | str
    speaker: str = "Vivian"
    language: str = "chinese"
    device: str = "cuda"
    dtype: str = "bfloat16"
    attn_implementation: str = "sdpa"
    chunk_size: int = 8
    max_new_tokens: int = 2048
    min_new_tokens: int = 16
    temperature: float = 0.7
    top_k: int = 50
    top_p: float = 1.0
    repetition_penalty: float = 1.05
    queue_maxsize: int = 32
    stop_timeout_s: float = 3.0
    warmup_text: Optional[str] = None
    tail_verify: bool = True
    tail_verify_retry: bool = False
    tail_anchor_chars: int = 2
    tail_verify_timeout_s: float = 8.0

    def __post_init__(self) -> None:
        path = Path(self.model_dir)
        if not str(path).strip():
            raise ValueError("model_dir must not be empty")
        object.__setattr__(self, "model_dir", path)
        for name in ("speaker", "language", "device", "dtype", "attn_implementation"):
            if not str(getattr(self, name)).strip():
                raise ValueError(name + " must not be empty")
        for name in ("chunk_size", "max_new_tokens", "min_new_tokens", "top_k", "queue_maxsize"):
            if int(getattr(self, name)) <= 0:
                raise ValueError(name + " must be positive")
        if float(self.stop_timeout_s) <= 0:
            raise ValueError("stop_timeout_s must be positive")
        if self.warmup_text is not None and not str(self.warmup_text).strip():
            raise ValueError("warmup_text must be non-empty when provided")
        if not 0 < float(self.temperature):
            raise ValueError("temperature must be positive")
        if not 0 < float(self.top_p) <= 1:
            raise ValueError("top_p must be in (0, 1]")
        if not 0 < float(self.repetition_penalty):
            raise ValueError("repetition_penalty must be positive")
        if int(self.tail_anchor_chars) <= 0:
            raise ValueError("tail_anchor_chars must be positive")
        if float(self.tail_verify_timeout_s) <= 0:
            raise ValueError("tail_verify_timeout_s must be positive")

    def to_dict(self) -> dict:
        """Return non-sensitive configuration metadata for diagnostics."""
        return {
            "model_dir": str(self.model_dir),
            "speaker": self.speaker,
            "language": self.language,
            "device": self.device,
            "dtype": self.dtype,
            "attn_implementation": self.attn_implementation,
            "chunk_size": self.chunk_size,
            "max_new_tokens": self.max_new_tokens,
            "min_new_tokens": self.min_new_tokens,
            "temperature": self.temperature,
            "top_k": self.top_k,
            "top_p": self.top_p,
            "repetition_penalty": self.repetition_penalty,
            "queue_maxsize": self.queue_maxsize,
            "stop_timeout_s": self.stop_timeout_s,
            "warmup_enabled": self.warmup_text is not None,
            "tail_verify": self.tail_verify,
            "tail_verify_retry": self.tail_verify_retry,
            "tail_anchor_chars": self.tail_anchor_chars,
            "tail_verify_timeout_s": self.tail_verify_timeout_s,
        }


def qwen_capabilities(*, worker_isolated: bool = False) -> TTSProviderCapabilities:
    """Return the conservative declaration for this adapter.

    Qwen's audio generator is genuinely chunked, but its public API consumes
    the complete text in one call.  ``text_stream`` therefore remains false;
    changing that flag requires a separate measured provider implementation.
    """

    return TTSProviderCapabilities(
        provider_id=QWEN_PROVIDER_ID,
        true_audio_stream=True,
        text_stream=False,
        cancel_observable=True,
        offline=True,
        native_emotion=True,
        worker_isolated=bool(worker_isolated),
        worker_persistent=True,
        output_sample_rate=PCM_SAMPLE_RATE,
        output_channels=1,
        output_format=PCM_FORMAT,
    )


def _safe_metadata(value: Any, key: str = "") -> Any:
    """Keep timing metadata while excluding text/audio payloads."""
    if key.lower() in {"text", "content", "audio", "samples", "raw_audio", "transcript"}:
        return "[redacted]"
    if isinstance(value, Mapping):
        return {str(k): _safe_metadata(v, str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe_metadata(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)[:160]


def _to_pcm_s16le(audio: Any) -> bytes:
    """Convert a Qwen NumPy/tensor block to finite little-endian PCM."""
    if audio is None:
        return b""
    if hasattr(audio, "detach"):
        audio = audio.detach()
    if hasattr(audio, "cpu"):
        audio = audio.cpu()
    if hasattr(audio, "numpy"):
        audio = audio.numpy()
    if isinstance(audio, (bytes, bytearray, memoryview)):
        data = bytes(audio)
        if len(data) % 2:
            raise QwenTTSAdapterError("VOICE-TTS-QWEN-PCM-INVALID", "odd PCM byte length")
        return data
    try:
        import numpy as np
    except ImportError as exc:  # pragma: no cover - dependency is locked in .venv
        raise QwenTTSAdapterError(
            "VOICE-TTS-QWEN-DEPENDENCY-MISSING", "numpy is required for PCM conversion"
        ) from exc
    try:
        array = np.asarray(audio)
        if array.ndim > 1:
            array = array.reshape(-1)
        if array.size == 0:
            return b""
        if np.issubdtype(array.dtype, np.floating):
            if not np.isfinite(array).all():
                raise QwenTTSAdapterError(
                    "VOICE-TTS-QWEN-PCM-INVALID", "audio contains non-finite samples"
                )
            array = np.clip(array, -1.0, 1.0)
            array = (array * 32767.0).round().astype("<i2")
        else:
            array = array.astype("<i2", copy=False)
        return array.tobytes()
    except QwenTTSAdapterError:
        raise
    except Exception as exc:
        raise QwenTTSAdapterError(
            "VOICE-TTS-QWEN-PCM-INVALID", f"cannot normalize audio: {type(exc).__name__}"
        ) from exc


def _generation_item(item: Any) -> Tuple[Any, int, Mapping[str, Any]]:
    """Read the tuple or mapping shape emitted by faster-qwen3-tts."""
    if isinstance(item, Mapping):
        audio = item.get("audio", item.get("samples", item.get("data")))
        sample_rate = item.get("sample_rate", item.get("sr", PCM_SAMPLE_RATE))
        timing = item.get("timing", {})
    elif isinstance(item, (tuple, list)) and len(item) >= 2:
        audio = item[0]
        sample_rate = item[1]
        timing = item[2] if len(item) > 2 and isinstance(item[2], Mapping) else {}
    else:
        raise QwenTTSAdapterError(
            "VOICE-TTS-QWEN-OUTPUT-INVALID", "provider emitted an unknown streaming shape"
        )
    try:
        return audio, int(sample_rate), timing
    except (TypeError, ValueError) as exc:
        raise QwenTTSAdapterError(
            "VOICE-TTS-QWEN-OUTPUT-INVALID", "provider emitted an invalid sample rate"
        ) from exc


def _supported_kwargs(method: Callable[..., Any], values: Mapping[str, Any]) -> dict:
    """Pass only arguments supported by a real or injected model method."""
    try:
        signature = inspect.signature(method)
    except (TypeError, ValueError):
        return dict(values)
    if any(parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in signature.parameters.values()):
        return dict(values)
    return {key: value for key, value in values.items() if key in signature.parameters}


def _load_qwen_model(config: QwenTTSConfig) -> Any:
    """Load a local faster-qwen3-tts model without network fallback."""
    if not config.model_dir.is_dir():
        raise QwenTTSAdapterError(
            "VOICE-TTS-QWEN-MODEL-MISSING", str(config.model_dir)[:240]
        )
    try:
        import torch
        from faster_qwen3_tts import FasterQwen3TTS
    except ImportError as exc:
        raise QwenTTSAdapterError(
            "VOICE-TTS-QWEN-DEPENDENCY-MISSING", str(exc)[:240]
        ) from exc
    dtype = getattr(torch, config.dtype, config.dtype)
    try:
        return FasterQwen3TTS.from_pretrained(
            str(config.model_dir),
            device=config.device,
            dtype=dtype,
            attn_implementation=config.attn_implementation,
            local_files_only=True,
        )
    except Exception as exc:
        raise QwenTTSAdapterError(
            "VOICE-TTS-QWEN-MODEL-LOAD-FAILED", str(exc)[:400]
        ) from exc


# Strips punctuation, whitespace and markdown glyphs (e.g. "**", "_") so the
# anchor is the trailing meaningful characters (CJK/letters/digits).
_TAIL_ANCHOR_STRIP = re.compile(r"[^\w]+")


def _tail_anchor(text: str, n: int) -> str:
    """Return the last ``n`` meaningful characters of a text sentence."""
    normalized = _TAIL_ANCHOR_STRIP.sub("", str(text or "")).strip()
    return normalized[-int(n):] if normalized else ""


class TailVerifier:
    """De-identified tail-completeness check for one synthesized utterance.

    Uses the local Sherpa-onnx online recognizer (CPU) to re-transcribe the
    concatenated PCM and checks that the expected tail anchor chars appear.
    Results only flow into session metrics/health — never into the event
    stream as an ERROR (the chain must not treat a statistical tail miss as
    a turn failure).
    """

    def __init__(
        self,
        *,
        timeout_s: float = 8.0,
        asr_factory: Optional[Callable[[], Any]] = None,
    ) -> None:
        self.timeout_s = float(timeout_s)
        self._asr_factory = asr_factory
        self._asr: Any = None
        self._lock = threading.RLock()

    def _provider(self) -> Any:
        with self._lock:
            if self._asr is None:
                if self._asr_factory is not None:
                    self._asr = self._asr_factory()
                else:
                    from backend.target_sherpa_asr import SherpaOnlineASRProvider

                    self._asr = SherpaOnlineASRProvider()
                self._asr.start()
            return self._asr

    def verify(self, text: str, pcm_bytes: bytes, sample_rate: int) -> Dict[str, Any]:
        anchor = _tail_anchor(text, 2)
        if not anchor or not pcm_bytes:
            return {"checked": False, "ok": None, "anchor": anchor}
        started = time.perf_counter()
        try:
            import numpy as np
            from backend.target_chain import CancellationSignal

            samples = np.frombuffer(pcm_bytes, dtype="<i2").astype("float32") / 32768.0
            asr = self._provider()
            signal = CancellationSignal()
            stream_id = "verify"
            asr.open_stream(stream_id, 1, 16000, 1, signal)
            # Resample 24k -> 16k with linear interpolation (verify only).
            if sample_rate != 16_000:
                n_out = int(samples.size * 16_000 / sample_rate)
                x_old = np.linspace(0.0, 1.0, max(samples.size, 2))
                x_new = np.linspace(0.0, 1.0, n_out)
                samples = np.interp(x_new, x_old, samples).astype("float32")
            chunk = 1600
            for off in range(0, samples.size, chunk):
                block = samples[off:off + chunk]
                if block.size:
                    asr.push_audio(stream_id, block, 16000, signal)
            update = asr.finish_stream(stream_id, signal)
            transcript = str(getattr(update, "text", update) or "")
            ok = anchor in transcript
            result: Dict[str, Any] = {
                "checked": True,
                "ok": bool(ok),
                "anchor": anchor,
                "asr_ms": round((time.perf_counter() - started) * 1000, 1),
                "transcript_len": len(transcript),
                "sha256_prefix": hashlib.sha256(transcript.encode()).hexdigest()[:16],
            }
            return result
        except Exception as exc:
            return {
                "checked": True,
                "ok": None,
                "anchor": anchor,
                "error": type(exc).__name__,
                "asr_ms": round((time.perf_counter() - started) * 1000, 1),
            }


import hashlib  # noqa: E402


def _gpu_snapshot(*, reset_peak: bool = False) -> dict:
    """Read optional CUDA counters without making them a hard dependency."""
    global _TORCH_CACHE, _TORCH_IMPORT_ATTEMPTED
    try:
        if not _TORCH_IMPORT_ATTEMPTED:
            with _TORCH_CACHE_LOCK:
                if not _TORCH_IMPORT_ATTEMPTED:
                    try:
                        import torch as torch_module
                    except Exception:
                        torch_module = None
                    _TORCH_CACHE = torch_module
                    _TORCH_IMPORT_ATTEMPTED = True
        torch = _TORCH_CACHE
        if torch is None:
            return {"cuda_available": False, "snapshot_error": "torch_unavailable"}

        if not torch.cuda.is_available():
            return {"cuda_available": False}
        if reset_peak:
            torch.cuda.reset_peak_memory_stats()
        free, total = torch.cuda.mem_get_info()
        return {
            "cuda_available": True,
            "device": torch.cuda.get_device_name(0),
            "allocated_mb": round(torch.cuda.memory_allocated() / 1048576, 3),
            "reserved_mb": round(torch.cuda.memory_reserved() / 1048576, 3),
            "peak_allocated_mb": round(torch.cuda.max_memory_allocated() / 1048576, 3),
            "peak_reserved_mb": round(torch.cuda.max_memory_reserved() / 1048576, 3),
            "free_mb": round(free / 1048576, 3),
            "total_mb": round(total / 1048576, 3),
        }
    except Exception as exc:
        return {"cuda_available": False, "snapshot_error": type(exc).__name__}


def _invoke_factory(factory: Callable[..., Any], config: QwenTTSConfig) -> Any:
    try:
        signature = inspect.signature(factory)
        positional = [
            parameter
            for parameter in signature.parameters.values()
            if parameter.kind
            in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
        ]
        if not positional and not any(
            parameter.kind == inspect.Parameter.VAR_POSITIONAL
            for parameter in signature.parameters.values()
        ):
            return factory()
    except (TypeError, ValueError):
        pass
    return factory(config)


class QwenTTSWorker:
    """One persistent model holder with request-scoped generation sessions."""

    def __init__(
        self,
        config: QwenTTSConfig,
        *,
        model_factory: Optional[Callable[..., Any]] = None,
        worker_isolated: bool = False,
        worker_id: Optional[str] = None,
        verifier_factory: Optional[Callable[..., Any]] = None,
    ) -> None:
        if not isinstance(config, QwenTTSConfig):
            raise TypeError("config must be QwenTTSConfig")
        self.config = config
        self.worker_isolated = bool(worker_isolated)
        self.worker_id = str(worker_id or "qwen-worker")
        self._model_factory = model_factory or _load_qwen_model
        self.verifier = (
            verifier_factory()
            if callable(verifier_factory)
            else (TailVerifier(timeout_s=config.tail_verify_timeout_s) if config.tail_verify else None)
        )
        self._lock = threading.RLock()
        self._model: Any = None
        self._session: Optional[QwenTTSSession] = None
        self._alive = False
        self._stopping = False
        self._failed = False
        self._last_error_code: Optional[str] = None
        self._last_error_detail = ""
        self._generation = 0
        self._started_at: Optional[float] = None
        self._stopped_event = threading.Event()
        self._stopped_event.set()
        self._last_session_metrics: Dict[str, Any] = {}
        self._warmup_seconds: Optional[float] = None

    def describe_capabilities(self) -> TTSProviderCapabilities:
        return qwen_capabilities(worker_isolated=self.worker_isolated)

    def start(self) -> None:
        with self._lock:
            if self._alive:
                return
            self._stopping = False
            self._failed = False
            self._last_error_code = None
            self._last_error_detail = ""
            self._stopped_event.clear()
        try:
            model = _invoke_factory(self._model_factory, self.config)
            if model is None:
                raise QwenTTSAdapterError(
                    "VOICE-TTS-QWEN-MODEL-LOAD-FAILED", "model factory returned None"
                )
            if not callable(getattr(model, "generate_custom_voice_streaming", None)):
                raise QwenTTSAdapterError(
                    "VOICE-TTS-QWEN-API-UNSUPPORTED",
                    "generate_custom_voice_streaming is unavailable",
                )
            # Import and initialize the optional telemetry path before any
            # request can be cancelled; lazy CUDA initialization here would
            # otherwise inflate the first cancellation budget.
            _gpu_snapshot()
            if self.config.warmup_text is not None:
                warmup_started = time.perf_counter()
                method = getattr(model, "generate_custom_voice_streaming")
                values = {
                    "text": self.config.warmup_text,
                    "speaker": self.config.speaker,
                    "language": self.config.language,
                    "instruct": None,
                    "non_streaming_mode": False,
                    "max_new_tokens": min(self.config.max_new_tokens, 512),
                    "min_new_tokens": self.config.min_new_tokens,
                    "temperature": self.config.temperature,
                    "top_k": self.config.top_k,
                    "top_p": self.config.top_p,
                    "repetition_penalty": self.config.repetition_penalty,
                    "chunk_size": self.config.chunk_size,
                }
                warmup_stream = method(**_supported_kwargs(method, values))
                try:
                    for _ in warmup_stream:
                        pass
                finally:
                    close = getattr(warmup_stream, "close", None)
                    if callable(close):
                        close()
                self._warmup_seconds = time.perf_counter() - warmup_started
            with self._lock:
                self._model = model
                self._alive = True
                self._generation += 1
                self._started_at = time.time()
        except QwenTTSAdapterError as exc:
            self._record_error(exc)
            with self._lock:
                self._alive = False
                self._failed = True
                self._stopped_event.set()
            self._release_model(model if "model" in locals() else None)
            raise
        except Exception as exc:
            wrapped = QwenTTSAdapterError(
                "VOICE-TTS-QWEN-MODEL-LOAD-FAILED", str(exc)[:400]
            )
            self._record_error(wrapped)
            with self._lock:
                self._alive = False
                self._failed = True
                self._stopped_event.set()
            self._release_model(model if "model" in locals() else None)
            raise wrapped from exc

    def open(self, request: TTSRequest) -> "QwenTTSSession":
        if not isinstance(request, TTSRequest):
            raise TypeError("request must be TTSRequest")
        with self._lock:
            if not self._alive or self._model is None:
                raise QwenTTSAdapterError("VOICE-TTS-QWEN-WORKER-NOT-READY")
            if self._stopping:
                raise QwenTTSAdapterError("VOICE-TTS-QWEN-WORKER-STOPPING")
            if self._session is not None:
                if not self._session.is_drained:
                    raise QwenTTSAdapterError("VOICE-TTS-QWEN-SESSION-BUSY")
                self._session = None
            session = QwenTTSSession(self, self._model, request)
            self._session = session
            return session

    def stop(self, reason: str = "worker_stop") -> None:
        with self._lock:
            if not self._alive:
                self._stopped_event.set()
                return
            self._stopping = True
            session = self._session
        if session is not None and not session.is_finished:
            session.cancel(reason)
            if not session.wait_stopped(self.config.stop_timeout_s):
                error = QwenTTSAdapterError(
                    "VOICE-TTS-QWEN-STOP-TIMEOUT", "generation did not stop"
                )
                self._record_error(error)
                with self._lock:
                    self._failed = True
                raise error
        if session is not None and not session.is_drained:
            # Worker shutdown is an explicit discard boundary.  Do not leave
            # an unread queue attached to a model that is about to unload.
            session.force_drain()
        with self._lock:
            model = self._model
            self._model = None
            self._alive = False
            self._stopping = False
            self._session = None
            self._stopped_event.set()
        self._release_model(model)

    close = stop

    def wait_stopped(self, timeout_s: float) -> bool:
        return self._stopped_event.wait(max(float(timeout_s), 0.0))

    def is_alive(self) -> bool:
        with self._lock:
            return self._alive

    def health(self) -> Mapping[str, Any]:
        with self._lock:
            if self._failed:
                state = "failed"
            elif self._stopping:
                state = "stopping"
            elif self._alive:
                state = "busy" if self._session and not self._session.is_drained else "ready"
            else:
                state = "stopped"
            result: Dict[str, Any] = {
                "provider_id": QWEN_PROVIDER_ID,
                "worker_id": self.worker_id,
                "state": state,
                "alive": self._alive,
                "model_loaded": self._model is not None,
                "worker_generation": self._generation,
                "warmup_seconds": self._warmup_seconds,
                "gpu": _gpu_snapshot(),
            }
            if self._last_error_code:
                result.update(
                    {
                        "last_error_code": self._last_error_code,
                        "last_error_detail": self._last_error_detail,
                    }
                )
            return result

    def metrics(self) -> Mapping[str, Any]:
        with self._lock:
            return {
                "provider_id": QWEN_PROVIDER_ID,
                "worker_id": self.worker_id,
                "worker_generation": self._generation,
                "model_loaded": self._model is not None,
                "model_dir": str(self.config.model_dir),
                "last_session": dict(self._last_session_metrics),
                "warmup_seconds": self._warmup_seconds,
                "gpu": _gpu_snapshot(),
            }

    def _session_finished(self, session: "QwenTTSSession") -> None:
        with self._lock:
            if self._session is session:
                self._last_session_metrics = dict(session.metrics())
                if session.is_drained:
                    self._session = None

    def _session_drained(self, session: "QwenTTSSession") -> None:
        with self._lock:
            if self._session is session:
                # The generation thread records a terminal snapshot before the
                # consumer has necessarily removed DONE/sentinel.  Refresh at
                # the drain boundary so queue depth and final RTF are accurate.
                self._last_session_metrics = dict(session.metrics())
                if session.is_finished:
                    self._session = None

    def _record_error(self, error: BaseException) -> None:
        code = error.code if isinstance(error, TTSProviderPortError) else "VOICE-TTS-QWEN-WORKER-FAILED"
        with self._lock:
            self._last_error_code = str(code)[:160]
            self._last_error_detail = str(error)[:400]

    @staticmethod
    def _release_model(model: Any) -> None:
        if model is not None:
            for name in ("close", "unload", "release"):
                method = getattr(model, name, None)
                if callable(method):
                    try:
                        method()
                    except Exception:
                        logger.debug("Qwen model release failed", exc_info=True)
                    break
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass


class QwenTTSSession:
    """Request-scoped text buffer and bounded audio event stream."""

    def __init__(self, owner: QwenTTSWorker, model: Any, request: TTSRequest) -> None:
        self.owner = owner
        self.model = model
        self.request = request
        self._queue: queue.Queue[Any] = queue.Queue(maxsize=owner.config.queue_maxsize)
        self._lock = threading.RLock()
        self._text_parts: list[str] = []
        self._committed = False
        self._cancel_requested = threading.Event()
        self._finished_event = threading.Event()
        self._drained_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._done_emitted = False
        self._stopped_emitted = False
        self._error_code: Optional[str] = None
        self._error_detail = ""
        self._started_at: Optional[float] = None
        self._first_chunk_at: Optional[float] = None
        self._pcm_bytes = 0
        self._pcm_all = bytearray()
        self._chunk_count = 0
        self._empty_chunk_count = 0
        self._pcm_duration_ms = 0
        self._rtf: Optional[float] = None
        self._tail_verify: Optional[Dict[str, Any]] = None
        self._queue_event(
            TTSProviderEvent(
                kind=TTSEventKind.READY.value,
                speech_id=request.speech_id,
                provider_epoch=request.provider_epoch,
                payload={"provider_id": QWEN_PROVIDER_ID},
            )
        )

    @property
    def is_finished(self) -> bool:
        return self._finished_event.is_set()

    @property
    def is_drained(self) -> bool:
        # A sentinel can be consumed just before the generation thread runs
        # its final metrics/cleanup block.  Reuse is safe only after both the
        # producer and consumer have crossed their terminal boundaries.
        return self._finished_event.is_set() and self._drained_event.is_set()

    def push_text(self, delta: str) -> int:
        with self._lock:
            self._ensure_accepting_text()
            value = str(delta or "")
            if value:
                self._text_parts.append(value)
            return len("".join(self._text_parts))

    def commit_text(self) -> bool:
        with self._lock:
            self._ensure_accepting_text()
            self._committed = True
            text = "".join(self._text_parts)
            if not text.strip():
                error = QwenTTSAdapterError(
                    "VOICE-TTS-QWEN-EMPTY-TEXT", "commit_text received no text"
                )
                self._terminal_error(error)
                self._finish_without_thread()
                self._emit_stopped("error")
                raise error
            self._started_at = time.perf_counter()
            self._thread = threading.Thread(
                target=self._run_generation,
                args=(text,),
                name="qwen-tts-generation",
                daemon=True,
            )
            self._thread.start()
            return True

    def audio_events(self) -> Iterator[TTSProviderEvent]:
        while True:
            item = self._queue.get()
            if item is _QUEUE_SENTINEL:
                self._drained_event.set()
                self.owner._session_drained(self)
                return
            yield item

    def cancel(self, reason: str = "cancelled") -> bool:
        self._cancel_requested.set()
        with self._lock:
            thread = self._thread
            if thread is None and not self._finished_event.is_set():
                self._finish_without_thread()
                self._emit_stopped(reason)
        return True

    def wait_stopped(self, timeout_s: float) -> bool:
        return self._finished_event.wait(max(float(timeout_s), 0.0))

    def force_drain(self) -> None:
        """Discard queued events during explicit worker shutdown."""
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
        self._drained_event.set()
        self.owner._session_drained(self)

    def health(self) -> Mapping[str, Any]:
        with self._lock:
            if self._error_code:
                state = "failed"
            elif self._cancel_requested.is_set() and not self.is_finished:
                state = "stopping"
            elif self._committed and not self.is_finished:
                state = "streaming"
            elif self.is_finished:
                state = "stopped"
            else:
                state = "ready"
            return {
                "provider_id": QWEN_PROVIDER_ID,
                "speech_id": self.request.speech_id,
                "provider_epoch": self.request.provider_epoch,
                "state": state,
                "committed": self._committed,
                "queue_depth": self._queue.qsize(),
            }

    def metrics(self) -> Mapping[str, Any]:
        with self._lock:
            first_chunk_ms = None
            if self._started_at is not None and self._first_chunk_at is not None:
                first_chunk_ms = max(0, int(round((self._first_chunk_at - self._started_at) * 1000)))
            return {
                "provider_id": QWEN_PROVIDER_ID,
                "speech_id": self.request.speech_id,
                "provider_epoch": self.request.provider_epoch,
                "state": "stopped" if self.is_finished else ("streaming" if self._committed else "ready"),
                "committed": self._committed,
                "cancelled": self._cancel_requested.is_set(),
                "first_chunk_ms": first_chunk_ms,
                "pcm_bytes": self._pcm_bytes,
                "pcm_duration_ms": self._pcm_duration_ms,
                "chunk_count": self._chunk_count,
                "empty_chunk_count": self._empty_chunk_count,
                "queue_depth": self._queue.qsize(),
                "real_time_factor": self._rtf,
                "error_code": self._error_code,
                "tail_verify": self._tail_verify,
                "gpu": _gpu_snapshot(),
            }

    def _ensure_accepting_text(self) -> None:
        if self._committed:
            raise QwenTTSAdapterError(
                "VOICE-TTS-QWEN-TEXT-AFTER-COMMIT", "text is immutable after commit_text"
            )
        if self._cancel_requested.is_set() or self.is_finished:
            raise QwenTTSAdapterError("VOICE-TTS-QWEN-SESSION-STOPPED")

    def _run_generation(self, text: str) -> None:
        generator: Any = None
        try:
            values = {
                "text": text,
                "speaker": self.request.voice_id
                if self.request.voice_id != "default"
                else self.owner.config.speaker,
                "language": self.owner.config.language,
                "instruct": self.request.style.get("instruct")
                if isinstance(self.request.style.get("instruct"), str)
                else None,
                "non_streaming_mode": False,
                "max_new_tokens": self.owner.config.max_new_tokens,
                "min_new_tokens": self.owner.config.min_new_tokens,
                "temperature": self.owner.config.temperature,
                "top_k": self.owner.config.top_k,
                "top_p": self.owner.config.top_p,
                "repetition_penalty": self.owner.config.repetition_penalty,
                "chunk_size": self.owner.config.chunk_size,
            }
            method = getattr(self.model, "generate_custom_voice_streaming", None)
            if not callable(method):
                raise QwenTTSAdapterError(
                    "VOICE-TTS-QWEN-API-UNSUPPORTED", "streaming method is unavailable"
                )
            generator = method(**_supported_kwargs(method, values))
            _gpu_snapshot(reset_peak=True)
            for item in generator:
                if self._cancel_requested.is_set():
                    break
                audio, sample_rate, timing = _generation_item(item)
                if sample_rate != PCM_SAMPLE_RATE:
                    raise QwenTTSAdapterError(
                        "VOICE-TTS-QWEN-SAMPLE-RATE",
                        f"expected {PCM_SAMPLE_RATE}, received {sample_rate}",
                    )
                pcm = _to_pcm_s16le(audio)
                if not pcm:
                    with self._lock:
                        self._empty_chunk_count += 1
                    continue
                chunk = PCMChunk(pcm, self._chunk_count)
                with self._lock:
                    self._chunk_count += 1
                    self._pcm_bytes += len(pcm)
                    self._pcm_all.extend(pcm)
                    self._pcm_duration_ms += chunk.duration_ms
                    if self._first_chunk_at is None and chunk.is_effective:
                        self._first_chunk_at = time.perf_counter()
                self._queue_event(
                    TTSProviderEvent(
                        kind=TTSEventKind.PCM_CHUNK.value,
                        speech_id=self.request.speech_id,
                        provider_epoch=self.request.provider_epoch,
                        sequence=chunk.sequence,
                        chunk=chunk,
                        payload={"timing": _safe_metadata(timing)},
                    )
                )
            if self._cancel_requested.is_set():
                # STOPPED is emitted in finally, after the generation thread
                # has actually finished and its metrics have been finalized.
                pass
            else:
                verifier = self.owner.verifier
                if verifier is not None:
                    try:
                        verify = verifier.verify(
                            str(text), bytes(self._pcm_all), PCM_SAMPLE_RATE
                        )
                    except Exception as exc:
                        verify = {
                            "checked": True,
                            "ok": None,
                            "error": type(exc).__name__,
                        }
                    with self._lock:
                        self._tail_verify = verify
                with self._lock:
                    self._done_emitted = True
                self._queue_event(
                    TTSProviderEvent(
                        kind=TTSEventKind.DONE.value,
                        speech_id=self.request.speech_id,
                        provider_epoch=self.request.provider_epoch,
                        sequence=self._chunk_count,
                        payload={
                            "chunk_count": self._chunk_count,
                            "pcm_duration_ms": self._pcm_duration_ms,
                        },
                    )
                )
        except QwenTTSAdapterError as exc:
            self._terminal_error(exc)
        except Exception as exc:
            self._terminal_error(
                QwenTTSAdapterError("VOICE-TTS-QWEN-GENERATE-FAILED", str(exc)[:400])
            )
        finally:
            if generator is not None:
                close = getattr(generator, "close", None)
                if callable(close):
                    try:
                        close()
                    except Exception:
                        logger.debug("Qwen generator close failed", exc_info=True)
            with self._lock:
                if self._started_at is not None and self._pcm_duration_ms:
                    elapsed = max(0.0, time.perf_counter() - self._started_at)
                    self._rtf = elapsed / (self._pcm_duration_ms / 1000.0)
                self._finished_event.set()
            if self._cancel_requested.is_set() or self._error_code:
                self._emit_stopped("error" if self._error_code else "cancelled")
            else:
                # The sentinel follows the finished flag so a consumer that
                # drains immediately can safely release the session.
                self._queue_event(_QUEUE_SENTINEL)
            self.owner._session_finished(self)

    def _finish_without_thread(self) -> None:
        with self._lock:
            self._finished_event.set()
        self.owner._session_finished(self)

    def _terminal_error(self, error: QwenTTSAdapterError) -> None:
        with self._lock:
            if self._finished_event.is_set():
                return
            self._error_code = error.code
            self._error_detail = error.detail
        self.owner._record_error(error)
        self._force_queue(
            TTSProviderEvent(
                kind=TTSEventKind.ERROR.value,
                speech_id=self.request.speech_id,
                provider_epoch=self.request.provider_epoch,
                code=error.code,
                detail=error.detail,
            )
        )

    def _emit_stopped(self, reason: str) -> None:
        with self._lock:
            if self._stopped_emitted:
                return
            self._stopped_emitted = True
        self._force_queue(
            TTSProviderEvent(
                kind=TTSEventKind.STOPPED.value,
                speech_id=self.request.speech_id,
                provider_epoch=self.request.provider_epoch,
                payload={"reason": str(reason or "cancelled")[:160]},
            )
        )
        self._force_queue(_QUEUE_SENTINEL)

    def _queue_event(self, event: Any) -> None:
        while True:
            try:
                self._queue.put(event, timeout=0.1)
                return
            except queue.Full:
                if self._cancel_requested.is_set():
                    return

    def _force_queue(self, event: Any) -> None:
        while True:
            try:
                self._queue.put_nowait(event)
                return
            except queue.Full:
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    continue


def create_qwen_provider(
    config: QwenTTSConfig,
    *,
    model_factory: Optional[Callable[..., Any]] = None,
    worker_isolated: bool = False,
    worker_id: Optional[str] = None,
) -> PersistentTTSProvider:
    """Build a lazy persistent provider without touching the application root."""
    capabilities = qwen_capabilities(worker_isolated=worker_isolated)

    def factory() -> QwenTTSWorker:
        return QwenTTSWorker(
            config,
            model_factory=model_factory,
            worker_isolated=worker_isolated,
            worker_id=worker_id,
        )

    return PersistentTTSProvider(
        factory,
        capabilities=capabilities,
        provider_id=QWEN_PROVIDER_ID,
        worker_isolated=worker_isolated,
        worker_persistent=True,
        stop_timeout_s=config.stop_timeout_s,
        worker_id=worker_id,
    )


__all__ = [
    "QWEN_PROVIDER_ID",
    "QwenTTSAdapterError",
    "QwenTTSConfig",
    "QwenTTSWorker",
    "QwenTTSSession",
    "create_qwen_provider",
    "qwen_capabilities",
]
