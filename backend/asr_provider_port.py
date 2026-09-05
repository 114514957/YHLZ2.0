"""Explicit ASR provider contract for the isolated target voice chain.

This module intentionally contains no model loader.  Until a local ASR model
has passed the same source, resource, cancellation, and accuracy gates as the
TTS/VAD providers, the target path reports ``unavailable`` rather than routing
audio to a legacy global object, a network endpoint, or a mock transcript.
"""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable

from backend.speech_segment import SpeechSegment
from backend.target_chain import CancellationSignal


class ASRProviderError(RuntimeError):
    """Stable error from a target-chain ASR provider."""

    def __init__(self, code: str, detail: str = "") -> None:
        self.code = str(code)[:160]
        self.detail = str(detail)[:400]
        super().__init__(self.code + (": " + self.detail if self.detail else ""))


class ASRProviderState(str, Enum):
    UNAVAILABLE = "unavailable"
    STARTING = "starting"
    READY = "ready"
    STOPPED = "stopped"
    FAILED = "failed"


class ASRStreamUpdateKind(str, Enum):
    """Non-persistent dispositions emitted by a live ASR stream."""

    PARTIAL = "partial"
    FINAL = "final"
    EMPTY = "empty"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class ASRStreamUpdate:
    """One ephemeral ASR stream result.

    ``text`` stays in-memory for the bridge to make the final wake-word
    decision. Callers must not put it in telemetry, logs, or health snapshots.
    """

    stream_id: str
    generation: int
    kind: ASRStreamUpdateKind
    text: str = ""
    elapsed_ms: float = 0.0


@runtime_checkable
class ASRProviderPort(Protocol):
    """Lifecycle and cancellation contract consumed by ``ASRBridge``."""

    def start(self) -> None: ...

    def transcribe(self, segment: SpeechSegment, signal: CancellationSignal) -> Any: ...

    def interrupt(self, reason: str = "interrupt") -> None: ...

    def wait_stopped(self, timeout_s: float) -> Any: ...

    def stop(self, reason: str = "shutdown") -> None: ...

    def health(self) -> Mapping[str, Any]: ...


@runtime_checkable
class StreamingASRProviderPort(Protocol):
    """Sessionized extension used by the target incremental-ASR bridge.

    The extension deliberately does not inherit ``ASRProviderPort``. A
    transcribe-only provider is not upgraded accidentally into a streaming
    provider, and a live provider never needs to buffer a completed segment.
    """

    def start(self) -> None: ...

    def open_stream(
        self,
        stream_id: str,
        generation: int,
        sample_rate: int,
        channels: int,
        signal: CancellationSignal,
    ) -> None: ...

    def push_audio(
        self,
        stream_id: str,
        samples: Any,
        sample_rate: int,
        signal: CancellationSignal,
    ) -> Sequence[ASRStreamUpdate]: ...

    def finish_stream(
        self,
        stream_id: str,
        signal: CancellationSignal,
    ) -> ASRStreamUpdate: ...

    def interrupt(self, reason: str = "interrupt") -> None: ...

    def wait_stopped(self, timeout_s: float) -> Any: ...

    def stop(self, reason: str = "shutdown") -> None: ...

    def health(self) -> Mapping[str, Any]: ...


def is_asr_provider_port(value: Any) -> bool:
    """Return whether an object exposes all target ASR lifecycle operations."""
    return all(
        callable(getattr(value, name, None))
        for name in ("start", "transcribe", "interrupt", "wait_stopped", "stop", "health")
    )


def is_streaming_asr_provider_port(value: Any) -> bool:
    """Return whether an object has every live-stream lifecycle operation."""
    return all(
        callable(getattr(value, name, None))
        for name in (
            "start",
            "open_stream",
            "push_audio",
            "finish_stream",
            "interrupt",
            "wait_stopped",
            "stop",
            "health",
        )
    )


class UnavailableASRProvider:
    """Fail-closed placeholder used until one local ASR provider is certified."""

    def __init__(
        self,
        *,
        provider_id: str = "local-asr-unconfigured",
        reason_code: str = "ASR-MODEL-UNAVAILABLE",
    ) -> None:
        if not str(provider_id).strip() or not str(reason_code).strip():
            raise ValueError("provider_id and reason_code must not be empty")
        self.provider_id = str(provider_id)[:160]
        self.reason_code = str(reason_code)[:160]
        self._lock = threading.RLock()
        self._state = ASRProviderState.UNAVAILABLE
        self._requests = 0
        self._interrupts = 0
        self._last_error_code = self.reason_code
        self._stopped = threading.Event()
        self._stopped.set()

    @property
    def state(self) -> ASRProviderState:
        with self._lock:
            return self._state

    def start(self) -> None:
        """Remain explicitly unavailable; model loading is never implicit."""
        with self._lock:
            self._state = ASRProviderState.UNAVAILABLE
            self._last_error_code = self.reason_code
            self._stopped.set()

    def transcribe(self, segment: SpeechSegment, signal: CancellationSignal) -> str:
        del segment
        with self._lock:
            self._requests += 1
            if signal.is_cancelled():
                self._last_error_code = "ASR-CANCELLED"
                raise ASRProviderError("ASR-CANCELLED")
            self._last_error_code = self.reason_code
            raise ASRProviderError(self.reason_code)

    def interrupt(self, reason: str = "interrupt") -> None:
        del reason
        with self._lock:
            self._interrupts += 1
            self._stopped.set()

    async def wait_stopped(self, timeout_s: float) -> bool:
        if float(timeout_s) < 0:
            raise ValueError("timeout_s must not be negative")
        return await asyncio.to_thread(self._stopped.wait, float(timeout_s))

    def stop(self, reason: str = "shutdown") -> None:
        del reason
        with self._lock:
            self._state = ASRProviderState.STOPPED
            self._stopped.set()

    close = stop

    def health(self) -> dict:
        with self._lock:
            return {
                "provider_id": self.provider_id,
                "state": self._state.value,
                "available": False,
                "local_only": True,
                "model_loaded": False,
                "last_error_code": self._last_error_code,
                "metrics": {
                    "requests": self._requests,
                    "interrupts": self._interrupts,
                },
                "stopped": self._stopped.is_set(),
            }


__all__ = [
    "ASRProviderError",
    "ASRProviderPort",
    "ASRProviderState",
    "ASRStreamUpdate",
    "ASRStreamUpdateKind",
    "StreamingASRProviderPort",
    "UnavailableASRProvider",
    "is_asr_provider_port",
    "is_streaming_asr_provider_port",
]
