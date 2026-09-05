"""Provider-neutral streaming TTS contract for the isolated voice chain.

The legacy TTS classes in :mod:`backend.tts` expose several incompatible
return shapes and do not own an observable stop state.  This module is the
small boundary used by the target chain while those providers are evaluated.
It deliberately contains no model, audio-device, network, or persistence
dependency.  A provider may implement the contract in a worker process; the
``worker_*`` capability flags describe that fact but never certify it.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator, Dict, Mapping, Optional, Protocol, Tuple, runtime_checkable


TTS_PORT_VERSION = "1.0"
PCM_SAMPLE_RATE = 24_000
PCM_CHANNELS = 1
PCM_FORMAT = "s16le"
PCM_SAMPLE_BYTES = 2
PCM_FRAME_MS = 20
PCM_FRAME_SAMPLES = PCM_SAMPLE_RATE * PCM_FRAME_MS // 1000
PCM_FRAME_BYTES = PCM_FRAME_SAMPLES * PCM_SAMPLE_BYTES * PCM_CHANNELS


class TTSProviderPortError(RuntimeError):
    """A fail-closed error carrying an operational error code."""

    def __init__(self, code: str, detail: str = "") -> None:
        self.code = str(code or "VOICE-TTS-UNKNOWN")[:160]
        self.detail = str(detail or "")[:400]
        message = self.code if not self.detail else f"{self.code}: {self.detail}"
        super().__init__(message)


class TTSProviderState(str, Enum):
    STARTING = "starting"
    READY = "ready"
    STREAMING = "streaming"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"


class TTSEventKind(str, Enum):
    READY = "READY"
    PCM_CHUNK = "PCM_CHUNK"
    FIRST_CHUNK = "FIRST_CHUNK"
    DONE = "DONE"
    ERROR = "ERROR"
    STOPPED = "STOPPED"


_SENSITIVE_KEYS = {
    "audio",
    "audio_ref",
    "content",
    "input",
    "raw_audio",
    "text",
    "transcript",
}


def _safe_payload(value: Any, key: str = "") -> Any:
    """Keep provider metadata useful without retaining text or audio."""
    if key.lower() in _SENSITIVE_KEYS:
        return "[redacted]"
    if isinstance(value, Mapping):
        return {str(k): _safe_payload(v, str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe_payload(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)[:160]


@dataclass(frozen=True, slots=True)
class TTSProviderCapabilities:
    """Declared provider capabilities, separate from runtime evidence.

    ``c_candidate`` is intentionally only a candidate check.  The target
    runtime still needs a device-bound acceptance run before it can report C.
    """

    provider_id: str
    true_audio_stream: bool = False
    text_stream: bool = False
    cancel_observable: bool = False
    offline: bool = True
    native_emotion: bool = False
    worker_isolated: bool = False
    worker_persistent: bool = False
    output_sample_rate: int = PCM_SAMPLE_RATE
    output_channels: int = PCM_CHANNELS
    output_format: str = PCM_FORMAT

    def __post_init__(self) -> None:
        if not str(self.provider_id).strip():
            raise ValueError("provider_id must not be empty")
        if self.output_sample_rate != PCM_SAMPLE_RATE:
            raise ValueError("output_sample_rate must be 24000")
        if self.output_channels != PCM_CHANNELS:
            raise ValueError("output_channels must be 1")
        if str(self.output_format).lower() != PCM_FORMAT:
            raise ValueError("output_format must be s16le")

    @property
    def c_candidate(self) -> bool:
        return not self.missing_for_candidate()

    def missing_for_candidate(self) -> Tuple[str, ...]:
        required = (
            ("true_audio_stream", self.true_audio_stream),
            ("text_stream", self.text_stream),
            ("cancel_observable", self.cancel_observable),
            ("worker_isolated", self.worker_isolated),
            ("worker_persistent", self.worker_persistent),
        )
        return tuple(name for name, present in required if not present)

    def to_dict(self) -> dict:
        return {
            "protocol_version": TTS_PORT_VERSION,
            "provider_id": self.provider_id,
            "true_audio_stream": self.true_audio_stream,
            "text_stream": self.text_stream,
            "cancel_observable": self.cancel_observable,
            "offline": self.offline,
            "native_emotion": self.native_emotion,
            "worker_isolated": self.worker_isolated,
            "worker_persistent": self.worker_persistent,
            "output_sample_rate": self.output_sample_rate,
            "output_channels": self.output_channels,
            "output_format": self.output_format,
            "c_candidate": self.c_candidate,
            "missing_for_candidate": list(self.missing_for_candidate()),
        }


def coerce_capabilities(value: Any) -> TTSProviderCapabilities:
    """Convert a provider declaration to the strict immutable type."""
    if isinstance(value, TTSProviderCapabilities):
        return value
    if isinstance(value, Mapping):
        data = dict(value)
        data.setdefault("provider_id", data.get("name", "unknown"))
        return TTSProviderCapabilities(
            provider_id=str(data["provider_id"]),
            true_audio_stream=bool(data.get("true_audio_stream", data.get("audio_stream", False))),
            text_stream=bool(data.get("text_stream", False)),
            cancel_observable=bool(data.get("cancel_observable", False)),
            offline=bool(data.get("offline", True)),
            native_emotion=bool(data.get("native_emotion", False)),
            worker_isolated=bool(data.get("worker_isolated", False)),
            worker_persistent=bool(data.get("worker_persistent", False)),
            output_sample_rate=int(data.get("output_sample_rate", PCM_SAMPLE_RATE)),
            output_channels=int(data.get("output_channels", PCM_CHANNELS)),
            output_format=str(data.get("output_format", PCM_FORMAT)),
        )
    raise TypeError("provider capabilities must be TTSProviderCapabilities or a mapping")


@dataclass(frozen=True, slots=True)
class TTSRequest:
    """Identity and voice selection bound to one TTS session."""

    session_id: str
    turn_id: str
    speech_id: str
    provider_epoch: int
    voice_id: str = "default"
    style: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("session_id", "turn_id", "speech_id", "voice_id"):
            if not str(getattr(self, name)).strip():
                raise ValueError(name + " must not be empty")
        if self.provider_epoch < 0:
            raise ValueError("provider_epoch must not be negative")
        if not isinstance(self.style, Mapping):
            raise TypeError("style must be a mapping")

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "speech_id": self.speech_id,
            "provider_epoch": self.provider_epoch,
            "voice_id": self.voice_id,
            "style": _safe_payload(dict(self.style)),
        }


@dataclass(frozen=True, slots=True)
class PCMChunk:
    """A normalized PCM block accepted by the target playback boundary."""

    data: bytes
    sequence: int
    sample_rate: int = PCM_SAMPLE_RATE
    channels: int = PCM_CHANNELS
    format: str = PCM_FORMAT

    def __post_init__(self) -> None:
        if isinstance(self.data, memoryview):
            object.__setattr__(self, "data", self.data.tobytes())
        elif isinstance(self.data, bytearray):
            object.__setattr__(self, "data", bytes(self.data))
        elif not isinstance(self.data, bytes):
            raise TypeError("PCM data must be bytes-like")
        if self.sequence < 0:
            raise ValueError("PCM sequence must not be negative")
        if self.sample_rate != PCM_SAMPLE_RATE:
            raise ValueError("PCM sample_rate must be 24000")
        if self.channels != PCM_CHANNELS:
            raise ValueError("PCM channels must be 1")
        if str(self.format).lower() != PCM_FORMAT:
            raise ValueError("PCM format must be s16le")
        if len(self.data) % PCM_SAMPLE_BYTES:
            raise ValueError("PCM data must contain complete s16le samples")

    @property
    def sample_count(self) -> int:
        return len(self.data) // PCM_SAMPLE_BYTES

    @property
    def duration_ms(self) -> int:
        return int(round(self.sample_count * 1000 / PCM_SAMPLE_RATE))

    @property
    def is_effective(self) -> bool:
        """Whether the block contains a non-silent sample."""
        return bool(self.data and any(self.data))

    def to_dict(self) -> dict:
        return {
            "sequence": self.sequence,
            "sample_rate": self.sample_rate,
            "channels": self.channels,
            "format": self.format,
            "byte_length": len(self.data),
            "sample_count": self.sample_count,
            "duration_ms": self.duration_ms,
            "effective": self.is_effective,
        }


@dataclass(frozen=True, slots=True)
class TTSProviderEvent:
    """Provider event carrying identity plus metadata, never raw text."""

    kind: str
    speech_id: str
    provider_epoch: int
    sequence: int = 0
    chunk: Optional[PCMChunk] = None
    code: Optional[str] = None
    detail: str = ""
    payload: Mapping[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.monotonic)

    def __post_init__(self) -> None:
        kind = self.kind.value if isinstance(self.kind, TTSEventKind) else str(self.kind)
        object.__setattr__(self, "kind", kind)
        valid = {item.value for item in TTSEventKind}
        if kind not in valid:
            raise ValueError("unknown TTS event kind: " + kind)
        if not str(self.speech_id).strip():
            raise ValueError("speech_id must not be empty")
        if self.provider_epoch < 0 or self.sequence < 0:
            raise ValueError("event identity values must not be negative")
        if kind == TTSEventKind.PCM_CHUNK.value and self.chunk is None:
            raise ValueError("PCM_CHUNK requires a chunk")
        if kind != TTSEventKind.PCM_CHUNK.value and self.chunk is not None:
            raise ValueError("only PCM_CHUNK may carry a chunk")
        if kind == TTSEventKind.ERROR.value and not str(self.code or "").strip():
            raise ValueError("ERROR requires a code")
        if not isinstance(self.payload, Mapping):
            raise TypeError("event payload must be a mapping")

    def to_dict(self) -> dict:
        result = {
            "protocol_version": TTS_PORT_VERSION,
            "kind": str(self.kind),
            "speech_id": self.speech_id,
            "provider_epoch": self.provider_epoch,
            "sequence": self.sequence,
            "code": self.code,
            "detail": str(self.detail)[:400],
            "payload": _safe_payload(dict(self.payload)),
            "timestamp": self.timestamp,
        }
        if self.chunk is not None:
            result["chunk"] = self.chunk.to_dict()
        return result


def coerce_pcm_chunk(value: Any, *, default_sequence: int = 0) -> PCMChunk:
    """Convert a provider-owned chunk mapping to the strict PCM type."""
    if isinstance(value, PCMChunk):
        return value
    if isinstance(value, Mapping):
        data = value.get("data", value.get("samples", value.get("audio")))
        return PCMChunk(
            data,
            int(value.get("sequence", default_sequence)),
            int(value.get("sample_rate", PCM_SAMPLE_RATE)),
            int(value.get("channels", PCM_CHANNELS)),
            str(value.get("format", PCM_FORMAT)),
        )
    if isinstance(value, (bytes, bytearray, memoryview)):
        return PCMChunk(value, default_sequence)
    raise TTSProviderPortError("VOICE-TTS-PCM-INVALID", "provider emitted an unknown PCM shape")


def coerce_provider_event(
    value: Any,
    *,
    request: TTSRequest,
    default_sequence: int = 0,
) -> TTSProviderEvent:
    """Normalize a dataclass or mapping emitted by a provider session."""
    if isinstance(value, TTSProviderEvent):
        return value
    if not isinstance(value, Mapping):
        raise TTSProviderPortError("VOICE-TTS-EVENT-INVALID", "provider emitted a non-mapping event")
    data = dict(value)
    kind_value = data.get("kind", data.get("event", ""))
    kind = kind_value.value if isinstance(kind_value, TTSEventKind) else str(kind_value)
    chunk_value = data.get("chunk")
    if kind == TTSEventKind.PCM_CHUNK.value and chunk_value is None:
        chunk_value = data.get(
            "pcm",
            data.get("audio", data.get("data", data.get("samples"))),
        )
    event_sequence = int(data.get("sequence", default_sequence))
    chunk = (
        coerce_pcm_chunk(chunk_value, default_sequence=int(event_sequence))
        if chunk_value is not None
        else None
    )
    if "sequence" not in data and chunk is not None:
        event_sequence = chunk.sequence
    return TTSProviderEvent(
        kind=kind,
        speech_id=str(data.get("speech_id", request.speech_id)),
        provider_epoch=int(data.get("provider_epoch", request.provider_epoch)),
        sequence=int(event_sequence),
        chunk=chunk,
        code=data.get("code"),
        detail=str(data.get("detail", "")),
        payload=data.get("payload", {}) or {},
        timestamp=float(data.get("timestamp", time.monotonic())),
    )


@dataclass(frozen=True, slots=True)
class TTSResourceMetrics:
    """Provider-neutral operational measurements for one session."""

    provider_id: str
    provider_epoch: int
    state: str = TTSProviderState.READY.value
    first_chunk_ms: Optional[int] = None
    pcm_duration_ms: int = 0
    input_chunk_count: int = 0
    output_frame_count: int = 0
    silent_chunk_count: int = 0
    duplicate_chunk_count: int = 0
    sequence_gap_count: int = 0
    stale_event_count: int = 0
    error_count: int = 0
    queue_depth: int = 0
    peak_memory_mb: Optional[float] = None
    peak_vram_mb: Optional[float] = None
    real_time_factor: Optional[float] = None
    last_error_code: Optional[str] = None
    provider: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "provider_id": self.provider_id,
            "provider_epoch": self.provider_epoch,
            "state": self.state,
            "first_chunk_ms": self.first_chunk_ms,
            "pcm_duration_ms": self.pcm_duration_ms,
            "input_chunk_count": self.input_chunk_count,
            "output_frame_count": self.output_frame_count,
            "silent_chunk_count": self.silent_chunk_count,
            "duplicate_chunk_count": self.duplicate_chunk_count,
            "sequence_gap_count": self.sequence_gap_count,
            "stale_event_count": self.stale_event_count,
            "error_count": self.error_count,
            "queue_depth": self.queue_depth,
            "peak_memory_mb": self.peak_memory_mb,
            "peak_vram_mb": self.peak_vram_mb,
            "real_time_factor": self.real_time_factor,
            "last_error_code": self.last_error_code,
            "provider": _safe_payload(dict(self.provider)),
        }


@runtime_checkable
class TTSProviderSession(Protocol):
    """One request-bound session opened from a TTS provider."""

    def push_text(self, delta: str) -> Any: ...

    def commit_text(self) -> Any: ...

    def audio_events(self) -> AsyncIterator[TTSProviderEvent]: ...

    def cancel(self, reason: str = "cancelled") -> Any: ...

    def wait_stopped(self, timeout_s: float) -> Any: ...

    def health(self) -> Mapping[str, Any]: ...

    def metrics(self) -> Mapping[str, Any]: ...


@runtime_checkable
class TTSProviderPort(Protocol):
    """Provider-level boundary used by the target chain."""

    def describe_capabilities(self) -> TTSProviderCapabilities: ...

    def open(self, request: TTSRequest) -> TTSProviderSession: ...

    def health(self) -> Mapping[str, Any]: ...

    def metrics(self) -> Mapping[str, Any]: ...


def is_tts_provider_port(value: Any) -> bool:
    """Structural check kept explicit so legacy engines remain compatible."""
    return value is not None and all(
        callable(getattr(value, name, None))
        for name in ("describe_capabilities", "open", "health", "metrics")
    )


def is_tts_provider_session(value: Any) -> bool:
    return value is not None and all(
        callable(getattr(value, name, None))
        for name in (
            "push_text",
            "commit_text",
            "audio_events",
            "cancel",
            "wait_stopped",
            "health",
            "metrics",
        )
    )


class PCMFrameRepacker:
    """Turn variable provider chunks into fixed 20 ms playback frames."""

    def __init__(self, frame_samples: int = PCM_FRAME_SAMPLES) -> None:
        if frame_samples <= 0:
            raise ValueError("frame_samples must be positive")
        self.frame_samples = int(frame_samples)
        self.frame_bytes = self.frame_samples * PCM_SAMPLE_BYTES * PCM_CHANNELS
        self._buffer = bytearray()
        self._next_sequence = 0

    def feed(self, chunk: PCMChunk) -> Tuple[PCMChunk, ...]:
        if not isinstance(chunk, PCMChunk):
            raise TypeError("repacker accepts PCMChunk only")
        self._buffer.extend(chunk.data)
        frames = []
        while len(self._buffer) >= self.frame_bytes:
            payload = bytes(self._buffer[: self.frame_bytes])
            del self._buffer[: self.frame_bytes]
            frames.append(self._new_frame(payload))
        return tuple(frames)

    def flush(self) -> Tuple[PCMChunk, ...]:
        if not self._buffer:
            return ()
        payload = bytes(self._buffer)
        self._buffer.clear()
        payload += b"\x00" * (self.frame_bytes - len(payload))
        return (self._new_frame(payload),)

    def _new_frame(self, payload: bytes) -> PCMChunk:
        frame = PCMChunk(payload, self._next_sequence)
        self._next_sequence += 1
        return frame


class TTSStreamNormalizer:
    """Validate identity/continuity and expose normalized PCM events."""

    def __init__(
        self,
        request: TTSRequest,
        capabilities: TTSProviderCapabilities,
        *,
        started_at: Optional[float] = None,
    ) -> None:
        self.request = request
        self.capabilities = capabilities
        self.started_at = time.monotonic() if started_at is None else float(started_at)
        self._repacker = PCMFrameRepacker()
        self._expected_provider_sequence = 0
        self._next_output_sequence = 0
        self._first_chunk_ms: Optional[int] = None
        self._saw_effective = False
        self._done = False
        self._pcm_duration_ms = 0
        self._input_chunk_count = 0
        self._output_frame_count = 0
        self._silent_chunk_count = 0
        self._duplicate_chunk_count = 0
        self._sequence_gap_count = 0
        self._stale_event_count = 0
        self._error_count = 0
        self._last_error_code: Optional[str] = None
        self._provider_metrics: Dict[str, Any] = {}

    @property
    def first_chunk_ms(self) -> Optional[int]:
        return self._first_chunk_ms

    @property
    def saw_effective_pcm(self) -> bool:
        return self._saw_effective

    @property
    def done(self) -> bool:
        return self._done

    def accept(self, event: TTSProviderEvent) -> Tuple[TTSProviderEvent, ...]:
        if not isinstance(event, TTSProviderEvent):
            raise TTSProviderPortError("VOICE-TTS-EVENT-INVALID", "provider emitted an unknown event")
        if event.speech_id != self.request.speech_id or event.provider_epoch != self.request.provider_epoch:
            self._stale_event_count += 1
            return ()
        kind = str(event.kind)
        if self._done and kind not in (TTSEventKind.STOPPED.value,):
            self._stale_event_count += 1
            return ()
        if kind == TTSEventKind.PCM_CHUNK.value:
            return self._accept_pcm(event)
        if kind == TTSEventKind.READY.value:
            return (event,)
        if kind == TTSEventKind.DONE.value:
            return self._accept_done(event)
        if kind == TTSEventKind.ERROR.value:
            self._error_count += 1
            self._last_error_code = str(event.code)
            raise TTSProviderPortError(str(event.code), event.detail)
        if kind == TTSEventKind.STOPPED.value:
            return (event,)
        if kind == TTSEventKind.FIRST_CHUNK.value:
            # FIRST_CHUNK is owned by this normalizer; provider declarations
            # are ignored so a provider cannot forge first-byte timing.
            self._stale_event_count += 1
            return ()
        raise TTSProviderPortError("VOICE-TTS-EVENT-INVALID", kind)

    def metrics(self, *, state: str = TTSProviderState.READY.value) -> TTSResourceMetrics:
        return TTSResourceMetrics(
            provider_id=self.capabilities.provider_id,
            provider_epoch=self.request.provider_epoch,
            state=state,
            first_chunk_ms=self._first_chunk_ms,
            pcm_duration_ms=self._pcm_duration_ms,
            input_chunk_count=self._input_chunk_count,
            output_frame_count=self._output_frame_count,
            silent_chunk_count=self._silent_chunk_count,
            duplicate_chunk_count=self._duplicate_chunk_count,
            sequence_gap_count=self._sequence_gap_count,
            stale_event_count=self._stale_event_count,
            error_count=self._error_count,
            last_error_code=self._last_error_code,
            provider=dict(self._provider_metrics),
        )

    def update_provider_metrics(self, metrics: Mapping[str, Any]) -> None:
        if not isinstance(metrics, Mapping):
            return
        self._provider_metrics = {
            str(key): _safe_payload(value, str(key))
            for key, value in metrics.items()
            if str(key).lower() not in _SENSITIVE_KEYS
        }

    def _accept_pcm(self, event: TTSProviderEvent) -> Tuple[TTSProviderEvent, ...]:
        chunk = event.chunk
        if chunk is None:
            raise TTSProviderPortError("VOICE-TTS-PCM-INVALID", "PCM_CHUNK has no payload")
        self._input_chunk_count += 1
        sequence = int(chunk.sequence)
        if sequence < self._expected_provider_sequence:
            self._duplicate_chunk_count += 1
            return ()
        if sequence > self._expected_provider_sequence:
            self._sequence_gap_count += 1
            raise TTSProviderPortError(
                "VOICE-TTS-PCM-SEQUENCE-GAP",
                f"expected {self._expected_provider_sequence}, received {sequence}",
            )
        self._expected_provider_sequence += 1
        if not chunk.is_effective:
            self._silent_chunk_count += 1
        frames = self._repacker.feed(chunk)
        output = []
        for frame in frames:
            if not self._saw_effective and not frame.is_effective:
                continue
            frame = self._output_frame(frame)
            if frame.is_effective and self._first_chunk_ms is None:
                self._saw_effective = True
                self._first_chunk_ms = max(0, int(round((time.monotonic() - self.started_at) * 1000)))
                output.append(
                    TTSProviderEvent(
                        kind=TTSEventKind.FIRST_CHUNK.value,
                        speech_id=self.request.speech_id,
                        provider_epoch=self.request.provider_epoch,
                        sequence=frame.sequence,
                        payload={"first_chunk_ms": self._first_chunk_ms},
                    )
                )
            output.append(
                TTSProviderEvent(
                    kind=TTSEventKind.PCM_CHUNK.value,
                    speech_id=self.request.speech_id,
                    provider_epoch=self.request.provider_epoch,
                    sequence=frame.sequence,
                    chunk=frame,
                )
            )
        return tuple(output)

    def _accept_done(self, event: TTSProviderEvent) -> Tuple[TTSProviderEvent, ...]:
        if self._done:
            return ()
        output = list(self._flush_frames())
        if not self._saw_effective:
            self._error_count += 1
            self._last_error_code = "VOICE-TTS-NO-EFFECTIVE-PCM"
            raise TTSProviderPortError(
                "VOICE-TTS-NO-EFFECTIVE-PCM",
                "provider completed without a non-silent PCM frame",
            )
        self._done = True
        output.append(
            TTSProviderEvent(
                kind=TTSEventKind.DONE.value,
                speech_id=self.request.speech_id,
                provider_epoch=self.request.provider_epoch,
                sequence=event.sequence,
                payload={"pcm_duration_ms": self._pcm_duration_ms},
            )
        )
        return tuple(output)

    def _flush_frames(self) -> Tuple[TTSProviderEvent, ...]:
        output = []
        for frame in self._repacker.flush():
            if not self._saw_effective and not frame.is_effective:
                continue
            frame = self._output_frame(frame)
            if frame.is_effective and self._first_chunk_ms is None:
                self._saw_effective = True
                self._first_chunk_ms = max(0, int(round((time.monotonic() - self.started_at) * 1000)))
                output.append(
                    TTSProviderEvent(
                        kind=TTSEventKind.FIRST_CHUNK.value,
                        speech_id=self.request.speech_id,
                        provider_epoch=self.request.provider_epoch,
                        sequence=frame.sequence,
                        payload={"first_chunk_ms": self._first_chunk_ms},
                    )
                )
            output.append(
                TTSProviderEvent(
                    kind=TTSEventKind.PCM_CHUNK.value,
                    speech_id=self.request.speech_id,
                    provider_epoch=self.request.provider_epoch,
                    sequence=frame.sequence,
                    chunk=frame,
                )
            )
        return tuple(output)

    def _output_frame(self, frame: PCMChunk) -> PCMChunk:
        """Assign a gap-free sequence after any leading silence is filtered."""
        normalized = PCMChunk(frame.data, self._next_output_sequence)
        self._next_output_sequence += 1
        self._output_frame_count += 1
        self._pcm_duration_ms += normalized.duration_ms
        return normalized


__all__ = [
    "PCM_CHANNELS",
    "PCM_FORMAT",
    "PCM_FRAME_BYTES",
    "PCM_FRAME_MS",
    "PCM_FRAME_SAMPLES",
    "PCM_SAMPLE_RATE",
    "TTS_PORT_VERSION",
    "PCMChunk",
    "PCMFrameRepacker",
    "TTSProviderCapabilities",
    "TTSProviderEvent",
    "TTSProviderPort",
    "TTSProviderPortError",
    "TTSProviderSession",
    "TTSProviderState",
    "TTSRequest",
    "TTSResourceMetrics",
    "TTSEventKind",
    "TTSStreamNormalizer",
    "coerce_capabilities",
    "coerce_pcm_chunk",
    "coerce_provider_event",
    "is_tts_provider_port",
    "is_tts_provider_session",
]
