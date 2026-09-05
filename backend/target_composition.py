"""Single composition root for the isolated target voice chain.

This module deliberately does not import the legacy application root or its
global ASR/TTS/audio objects.  It owns exactly one SessionKernel, wake gate,
target chain, and selected Qwen Provider.  Device and business adapters stay
explicit so this root can be tested without loading a model or opening audio.
"""

from __future__ import annotations

import asyncio
import inspect
import threading
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional

from backend.asr_bridge import ASRBridge
from backend.asr_provider_port import is_asr_provider_port, is_streaming_asr_provider_port
from backend.media_adapter import MediaAdapter
from backend.target_voice_gate import auto_voice_gate
from backend.memory_guard import ReadOnlyMemoryFacade
from backend.session_kernel import CapabilityAssessment, ProviderCapabilities, SessionKernel
from backend.streaming_asr_bridge import StreamingASRBridge
from backend.target_acceptance import AcceptanceThresholds
from backend.target_chain import TargetVoiceChain
from backend.target_probe import EnvironmentProbeReport
from backend.target_runtime import TargetVoiceRuntime
from backend.tts_provider_port import is_tts_provider_port
from backend.tts_qwen_process import create_qwen_process_provider
from backend.tts_qwen_provider import QwenTTSConfig
from backend.voice_gate import WAKE_WORD, WakeWordGate


class TargetCompositionError(RuntimeError):
    """Fail-closed composition-root error with a stable operational code."""

    def __init__(self, code: str, detail: str = "") -> None:
        self.code = str(code)[:160]
        self.detail = str(detail)[:400]
        super().__init__(self.code + (": " + self.detail if self.detail else ""))


@dataclass(frozen=True, slots=True)
class TargetVoiceCompositionConfig:
    """Non-persistent configuration owned by one target-chain composition."""

    qwen: QwenTTSConfig
    worker_id: str = "target-qwen-process"
    startup_timeout_s: float = 90.0
    stop_timeout_s: float = 3.0
    media_queue_capacity: int = 32
    media_queue_duration_ms: int = 5_000
    asr_timeout_s: float = 30.0
    asr_cancel_timeout_s: float = 1.0
    asr_stream_queue_capacity: int = 20
    asr_stream_queue_duration_ms: int = 2_000
    noise_suppressor_enabled: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.qwen, QwenTTSConfig):
            raise TypeError("qwen must be QwenTTSConfig")
        if not str(self.worker_id).strip():
            raise ValueError("worker_id must not be empty")
        for name in (
            "startup_timeout_s",
            "stop_timeout_s",
            "asr_timeout_s",
            "asr_cancel_timeout_s",
        ):
            if float(getattr(self, name)) <= 0:
                raise ValueError(name + " must be positive")
        for name in (
            "media_queue_capacity",
            "media_queue_duration_ms",
            "asr_stream_queue_capacity",
            "asr_stream_queue_duration_ms",
        ):
            if int(getattr(self, name)) <= 0:
                raise ValueError(name + " must be positive")

    def to_dict(self) -> dict:
        return {
            "qwen": self.qwen.to_dict(),
            "worker_id": self.worker_id,
            "startup_timeout_s": float(self.startup_timeout_s),
            "stop_timeout_s": float(self.stop_timeout_s),
            "media_queue_capacity": int(self.media_queue_capacity),
            "media_queue_duration_ms": int(self.media_queue_duration_ms),
            "asr_timeout_s": float(self.asr_timeout_s),
            "asr_cancel_timeout_s": float(self.asr_cancel_timeout_s),
            "asr_stream_queue_capacity": int(self.asr_stream_queue_capacity),
            "asr_stream_queue_duration_ms": int(self.asr_stream_queue_duration_ms),
            "noise_suppressor_enabled": bool(self.noise_suppressor_enabled),
        }


ProviderFactory = Callable[[QwenTTSConfig], Any]
_SENSITIVE_KEYS = frozenset(
    {
        "audio",
        "audio_ref",
        "content",
        "input",
        "raw_audio",
        "text",
        "transcript",
    }
)


class TargetVoiceComposition:
    """Own one target runtime graph without importing legacy global state."""

    def __init__(
        self,
        config: TargetVoiceCompositionConfig,
        *,
        reasoner: Any,
        playback: Any = None,
        memory: Optional[ReadOnlyMemoryFacade] = None,
        provider_factory: Optional[ProviderFactory] = None,
    ) -> None:
        if not isinstance(config, TargetVoiceCompositionConfig):
            raise TypeError("config must be TargetVoiceCompositionConfig")
        if not callable(getattr(reasoner, "generate", None)):
            raise TargetCompositionError("VOICE-COMPOSITION-REASONER-MISSING")
        if memory is not None and not isinstance(memory, ReadOnlyMemoryFacade):
            raise TargetCompositionError("MEMORY-WRITE-BLOCKED", "memory must use ReadOnlyMemoryFacade")

        self.config = config
        self.memory = memory or ReadOnlyMemoryFacade()
        self.kernel = SessionKernel()
        self.gate = WakeWordGate(WAKE_WORD)
        self.playback = playback
        factory = provider_factory or self._create_process_provider
        provider = factory(config.qwen)
        if not is_tts_provider_port(provider):
            raise TargetCompositionError("VOICE-COMPOSITION-PROVIDER-INVALID")
        self.tts_provider = provider
        self.chain = TargetVoiceChain(
            kernel=self.kernel,
            gate=self.gate,
            reasoner=reasoner,
            tts_provider=provider,
            playback=playback,
            memory=self.memory,
            tts_voice_id=config.qwen.speaker,
        )
        self._runtime: Optional[TargetVoiceRuntime] = None
        self._bound_vad: Any = None
        self._closed = False
        self._lock = threading.RLock()

    @property
    def runtime(self) -> Optional[TargetVoiceRuntime]:
        with self._lock:
            return self._runtime

    @property
    def closed(self) -> bool:
        with self._lock:
            return self._closed

    def create_runtime(
        self,
        *,
        asr: Any,
        source: Any = None,
        vad: Any = None,
        aec: Any = None,
        resampler: Any = None,
        target_sample_rate: Optional[int] = None,
        environment_report: Optional[EnvironmentProbeReport] = None,
        acceptance_thresholds: Optional[AcceptanceThresholds] = None,
    ) -> TargetVoiceRuntime:
        """Create the only runtime that may own the composition's media path."""
        is_streaming = is_streaming_asr_provider_port(asr)
        if not is_streaming and not is_asr_provider_port(asr):
            raise TargetCompositionError("VOICE-COMPOSITION-ASR-PORT-INVALID")
        with self._lock:
            if self._closed:
                raise TargetCompositionError("VOICE-COMPOSITION-CLOSED")
            if self._runtime is not None:
                raise TargetCompositionError("VOICE-COMPOSITION-RUNTIME-ALREADY-BOUND")
            # The composition root owns every injected helper's lifecycle.
            # A caller-provided VAD must be started here; otherwise the
            # runtime hits VAD-NOT-READY on the first frame (ledger 0129).
            if vad is not None:
                vad_start = getattr(vad, "start", None)
                if callable(vad_start):
                    vad_start()
                    self._bound_vad = vad
            media = MediaAdapter(
                source=source,
                vad=vad,
                aec=aec,
                resampler=resampler,
                target_sample_rate=target_sample_rate,
                queue_capacity=self.config.media_queue_capacity,
                max_queue_duration_ms=self.config.media_queue_duration_ms,
                voice_gate=auto_voice_gate(self._playback_or_none()),
                denoiser=self._create_denoiser(),
            )
            if is_streaming:
                bridge = StreamingASRBridge(
                    asr=asr,
                    chain=self.chain,
                    queue_capacity=self.config.asr_stream_queue_capacity,
                    max_queue_duration_ms=self.config.asr_stream_queue_duration_ms,
                    cancel_timeout_s=self.config.asr_cancel_timeout_s,
                )
            else:
                bridge = ASRBridge(
                    asr=asr,
                    chain=self.chain,
                    timeout_s=self.config.asr_timeout_s,
                    cancel_timeout_s=self.config.asr_cancel_timeout_s,
                )
            self._runtime = TargetVoiceRuntime(
                media=media,
                asr=bridge,
                chain=self.chain,
                stop_timeout_s=self.config.stop_timeout_s,
                environment_report=environment_report,
                acceptance_thresholds=acceptance_thresholds,
            )
            return self._runtime

    def start(
        self,
        device: Any,
        capabilities: ProviderCapabilities,
    ) -> CapabilityAssessment:
        """Start only the runtime created by this composition root."""
        runtime = self._require_runtime()
        return runtime.start(device, capabilities)

    async def run(self) -> None:
        """Run the composition's sole media consumer."""
        await self._require_runtime().run()

    async def stop(self, reason: str = "shutdown") -> None:
        """Stop turns and media but retain provider shutdown for explicit close."""
        runtime = self.runtime
        if runtime is not None:
            await runtime.stop(reason)
            return
        await self.chain.shutdown()

    async def shutdown(self, reason: str = "shutdown") -> None:
        """Close runtime then release the Qwen worker only after stop proof."""
        with self._lock:
            if self._closed:
                return
        await self.stop(reason)
        waiter = getattr(self.tts_provider, "wait_idle_stopped", None)
        if not callable(waiter):
            raise TargetCompositionError("VOICE-TTS-COMPOSITION-STOP-UNOBSERVABLE")
        confirmed = await _invoke_provider_method(waiter, self.config.stop_timeout_s)
        if not confirmed:
            raise TargetCompositionError("VOICE-TTS-COMPOSITION-STOP-UNCONFIRMED")
        shutdown = getattr(self.tts_provider, "shutdown", None)
        if not callable(shutdown):
            raise TargetCompositionError("VOICE-TTS-COMPOSITION-SHUTDOWN-MISSING")
        await asyncio.to_thread(
            _invoke_sync_shutdown,
            shutdown,
            str(reason or "shutdown")[:160],
            self.config.stop_timeout_s,
        )
        with self._lock:
            self._closed = True

    def add_turn_observer(self, observer: Any) -> None:
        """Route completed-turn notifications to an external sink (memory etc.)."""
        self.chain.set_turn_observer(observer)

    def _playback_or_none(self) -> Any:
        return self.playback

    def _create_denoiser(self) -> Any:
        if not self.config.noise_suppressor_enabled:
            return None
        try:
            from backend.target_audio_processor import NEKOAudioProcessor, is_denoiser

            denoiser = NEKOAudioProcessor(
                noise_reduce_enabled=True, agc_enabled=True, limiter_enabled=True
            )
            if not is_denoiser(denoiser):
                return None
            return denoiser
        except Exception:
            return None

    def health(self) -> dict:
        """Return only redacted operational snapshots; never initialize a model."""
        with self._lock:
            runtime = self._runtime
            closed = self._closed
        return {
            "closed": closed,
            "config": self.config.to_dict(),
            "wake_word": WAKE_WORD,
            "memory": self.memory.runtime_status(),
            "provider": _safe_provider_snapshot(self.tts_provider, "health"),
            "provider_metrics": _safe_provider_snapshot(self.tts_provider, "metrics"),
            "chain": self.chain.snapshot(),
            "runtime": runtime.health() if runtime is not None else None,
        }

    def _create_process_provider(self, qwen: QwenTTSConfig) -> Any:
        return create_qwen_process_provider(
            qwen,
            worker_id=self.config.worker_id,
            startup_timeout_s=self.config.startup_timeout_s,
        )

    def _require_runtime(self) -> TargetVoiceRuntime:
        with self._lock:
            runtime = self._runtime
            closed = self._closed
        if closed:
            raise TargetCompositionError("VOICE-COMPOSITION-CLOSED")
        if runtime is None:
            raise TargetCompositionError("VOICE-COMPOSITION-RUNTIME-MISSING")
        return runtime


async def _invoke_provider_method(method: Callable[..., Any], *args: Any) -> Any:
    """Run synchronous Provider control off the event loop when required."""
    if inspect.iscoroutinefunction(method):
        return await method(*args)
    value = await asyncio.to_thread(method, *args)
    return await value if inspect.isawaitable(value) else value


def _invoke_sync_shutdown(method: Callable[..., Any], reason: str, timeout_s: float) -> None:
    """Provider lifecycle is synchronous at the persistent-worker boundary."""
    try:
        result = method(reason, timeout_s=timeout_s)
    except TypeError:
        result = method(reason)
    if inspect.isawaitable(result):
        close = getattr(result, "close", None)
        if callable(close):
            close()
        raise TargetCompositionError(
            "VOICE-TTS-COMPOSITION-ASYNC-SHUTDOWN",
            "persistent provider shutdown must be synchronous",
        )


def _safe_provider_snapshot(provider: Any, method_name: str) -> Mapping[str, Any]:
    method = getattr(provider, method_name, None)
    if not callable(method):
        return {"error_code": "VOICE-COMPOSITION-PROVIDER-SNAPSHOT-MISSING"}
    try:
        value = method()
        if inspect.isawaitable(value):
            close = getattr(value, "close", None)
            if callable(close):
                close()
            return {"error_code": "VOICE-COMPOSITION-PROVIDER-SNAPSHOT-ASYNC"}
        return _safe_snapshot_value(dict(value)) if isinstance(value, Mapping) else {"value": repr(value)[:160]}
    except Exception as exc:
        return {
            "error_code": "VOICE-COMPOSITION-PROVIDER-SNAPSHOT-FAILED",
            "detail": type(exc).__name__,
        }


def _safe_snapshot_value(value: Any, key: str = "") -> Any:
    if key.lower() in _SENSITIVE_KEYS:
        return "[redacted]"
    if isinstance(value, Mapping):
        return {str(item): _safe_snapshot_value(nested, str(item)) for item, nested in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe_snapshot_value(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)[:160]


__all__ = [
    "TargetCompositionError",
    "TargetVoiceComposition",
    "TargetVoiceCompositionConfig",
]
