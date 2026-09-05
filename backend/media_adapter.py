"""Provider-neutral microphone ingress for the target voice chain.

The adapter owns capture lifecycle and bounded frame ingress, but it does not
open a production device unless an explicit input source is supplied.  This
keeps hardware and optional audio libraries outside the Session Kernel while
making VAD/AEC behavior testable with synthetic frames.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import queue
import threading
import time
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Callable, Dict, Mapping, Optional, Protocol

from backend.session_kernel import (
    AudioRoute,
    CapabilityAssessment,
    DuplexMode,
    ProviderCapabilities,
)


logger = logging.getLogger(__name__)


class MediaError(RuntimeError):
    """Raised when a media source or frame violates the ingress contract."""


class MediaState(str, Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    DEGRADED = "degraded"
    STOPPING = "stopping"
    FAILED = "failed"


class MediaEventKind(str, Enum):
    STARTED = "MEDIA_STARTED"
    SPEECH_STARTED = "SPEECH_STARTED"
    SPEECH_ENDED = "SPEECH_ENDED"
    BACKPRESSURE = "MEDIA_BACKPRESSURE"
    STALE_FRAME = "MEDIA_STALE_FRAME"
    ERROR = "MEDIA_ERROR"
    STOPPED = "MEDIA_STOPPED"


@dataclass(frozen=True, slots=True)
class DeviceDescriptor:
    """A selected input/output route, without retaining a device handle."""

    device_id: str
    name: str
    input_channels: int
    output_channels: int
    sample_rate: int = 16_000
    route: str = AudioRoute.UNKNOWN.value
    reference_available: bool = False

    def __post_init__(self) -> None:
        if not str(self.device_id).strip():
            raise ValueError("device_id must not be empty")
        if self.input_channels <= 0:
            raise ValueError("input_channels must be positive")
        if self.output_channels < 0:
            raise ValueError("output_channels must not be negative")
        if self.sample_rate <= 0:
            raise ValueError("sample_rate must be positive")
        try:
            AudioRoute(self.route)
        except ValueError as exc:
            raise ValueError("route must be a known AudioRoute value") from exc

    def to_dict(self) -> dict:
        return {
            "device_id": self.device_id,
            "name": self.name,
            "input_channels": self.input_channels,
            "output_channels": self.output_channels,
            "sample_rate": self.sample_rate,
            "route": self.route,
            "reference_available": self.reference_available,
        }


@dataclass(frozen=True, slots=True)
class AudioFrame:
    """One in-memory capture frame.  Samples are never written by this module."""

    samples: Any
    sample_rate: int
    channels: int = 1
    sequence: int = 0
    generation: int = 0
    captured_at: float = field(default_factory=time.monotonic)
    duration_ms: int = 0
    reference_samples: Any = None

    def __post_init__(self) -> None:
        if self.samples is None:
            raise ValueError("samples must not be None")
        if self.sample_rate <= 0:
            raise ValueError("sample_rate must be positive")
        if self.channels <= 0:
            raise ValueError("channels must be positive")
        if self.sequence < 0 or self.generation < 0:
            raise ValueError("sequence and generation must not be negative")
        if self.duration_ms < 0:
            raise ValueError("duration_ms must not be negative")


@dataclass(frozen=True, slots=True)
class ProcessedAudioFrame:
    """Frame delivered to the ASR/VAD side of the target chain."""

    frame: AudioFrame
    samples: Any
    speech: Optional[bool]
    aec_applied: bool
    echo_return_loss: Optional[float] = None


@dataclass(frozen=True, slots=True)
class MediaEvent:
    """Operational event; payload intentionally excludes raw media."""

    kind: str
    code: Optional[str]
    event_seq: int
    generation: int
    sequence: int
    timestamp: float
    payload: Dict[str, Any] = field(default_factory=dict)


class InputSource(Protocol):
    """Minimal source lifecycle used by MediaAdapter."""

    def start(self, callback: Callable[..., Any], device: DeviceDescriptor) -> None: ...

    def stop(self) -> None: ...

    def health(self) -> Mapping[str, Any]: ...


class VADPort(Protocol):
    def detect_speech(self, audio: Any, sample_rate: int) -> bool: ...


class AECPort(Protocol):
    def process(self, mic_audio: Any, reference_audio: Any, sample_rate: int) -> Any: ...


class ResamplerPort(Protocol):
    def process(self, audio: Any, source_rate: int, target_rate: int) -> Any: ...


FrameHandler = Callable[[ProcessedAudioFrame], Any]
EventHandler = Callable[[MediaEvent], Any]


def _estimate_duration_ms(samples: Any, sample_rate: int, channels: int) -> int:
    """Estimate PCM duration without depending on numpy or an audio library."""
    if sample_rate <= 0 or channels <= 0:
        return 0
    try:
        if isinstance(samples, (bytes, bytearray, memoryview)):
            sample_count = len(samples) // 2 // channels
        else:
            shape = getattr(samples, "shape", None)
            sample_count = int(shape[0]) if shape else len(samples)
        return max(0, int(round(sample_count * 1000 / sample_rate)))
    except Exception:
        return 0


class MediaAdapter:
    """Own capture lifecycle, bounded ingress, VAD edges, and AEC evidence."""

    def __init__(
        self,
        *,
        source: Optional[InputSource] = None,
        vad: Optional[VADPort] = None,
        aec: Optional[AECPort] = None,
        resampler: Optional[ResamplerPort] = None,
        target_sample_rate: Optional[int] = None,
        on_frame: Optional[FrameHandler] = None,
        on_event: Optional[EventHandler] = None,
        queue_capacity: int = 32,
        max_queue_duration_ms: int = 5_000,
        voice_gate: Optional[Any] = None,
        denoiser: Optional[Any] = None,
    ) -> None:
        if queue_capacity <= 0:
            raise ValueError("queue_capacity must be positive")
        if max_queue_duration_ms <= 0:
            raise ValueError("max_queue_duration_ms must be positive")
        if target_sample_rate is not None and int(target_sample_rate) <= 0:
            raise ValueError("target_sample_rate must be positive when set")
        self.source = source
        self.vad = vad
        self.aec = aec
        self.resampler = resampler
        self.target_sample_rate = int(target_sample_rate) if target_sample_rate is not None else None
        self.voice_gate = voice_gate
        self.denoiser = denoiser
        self.on_frame = on_frame
        self.on_event = on_event
        self._queue: "queue.Queue[AudioFrame]" = queue.Queue(maxsize=queue_capacity)
        self._max_queue_duration_ms = int(max_queue_duration_ms)
        self._queue_duration_ms = 0
        self._queued_durations: Dict[int, int] = {}
        self._lock = threading.RLock()
        self._state = MediaState.STOPPED
        self._device: Optional[DeviceDescriptor] = None
        self._caps: Optional[ProviderCapabilities] = None
        self._assessment = CapabilityAssessment(DuplexMode.B, ("not_assessed",))
        self._generation = 0
        self._next_sequence = 0
        self._last_processed_sequence = 0
        self._event_sequence = 0
        self._speech_active = False
        self._dropped_frames = 0
        self._runtime_missing: list[str] = []

    @property
    def state(self) -> MediaState:
        with self._lock:
            return self._state

    @property
    def assessment(self) -> CapabilityAssessment:
        with self._lock:
            return self._assessment

    @property
    def capabilities(self) -> Optional[ProviderCapabilities]:
        """Return the capability set after local source checks."""
        with self._lock:
            return self._caps

    @property
    def generation(self) -> int:
        with self._lock:
            return self._generation

    @property
    def queue_capacity(self) -> int:
        return self._queue.maxsize

    @property
    def max_queue_duration_ms(self) -> int:
        return self._max_queue_duration_ms

    def start(
        self,
        device: DeviceDescriptor,
        capabilities: ProviderCapabilities,
    ) -> CapabilityAssessment:
        """Start one source and return the effective C/B assessment.

        Missing local adapters downgrade the effective capability instead of
        claiming C from configuration alone.  The caller remains responsible
        for passing this result to Session Kernel and for publishing it to the
        backend health endpoint.
        """
        with self._lock:
            if self._state in {
                MediaState.STARTING,
                MediaState.RUNNING,
                MediaState.DEGRADED,
            }:
                raise MediaError("media adapter is already running")
            self._state = MediaState.STARTING
            self._generation += 1
            self._next_sequence = 0
            self._last_processed_sequence = 0
            self._speech_active = False
            self._runtime_missing = []
            self._drain_queue_locked()
            self._queue_duration_ms = 0
            self._queued_durations.clear()
            self._device = device
            self._caps = self._effective_capabilities(device, capabilities)
            self._assessment = self._caps.assess()
            self._state = (
                MediaState.RUNNING
                if self._assessment.mode is DuplexMode.C
                else MediaState.DEGRADED
            )

        try:
            reset_resampler = getattr(self.resampler, "reset", None)
            if callable(reset_resampler):
                reset_resampler()
            if self.source is not None:
                self.source.start(self._source_callback, device)
        except Exception as exc:
            with self._lock:
                self._state = MediaState.FAILED
            self._emit(
                MediaEventKind.ERROR,
                "MEDIA-SOURCE-START",
                payload={"detail": type(exc).__name__},
            )
            raise MediaError("input source failed to start") from exc

        self._emit(
            MediaEventKind.STARTED,
            payload={
                "mode": self._assessment.mode.value,
                "missing_for_c": list(self._assessment.missing_for_c),
                "device": device.to_dict(),
            },
        )
        return self._assessment

    def stop(self) -> None:
        """Stop capture, invalidate queued frames, and release source ownership."""
        with self._lock:
            if self._state is MediaState.STOPPED:
                return
            self._state = MediaState.STOPPING
            self._generation += 1
            self._speech_active = False
            self._drain_queue_locked()
        try:
            if self.source is not None:
                self.source.stop()
        except Exception as exc:
            self._emit(
                MediaEventKind.ERROR,
                "MEDIA-SOURCE-STOP",
                payload={"detail": type(exc).__name__},
            )
        finally:
            with self._lock:
                self._state = MediaState.STOPPED
            self._emit(MediaEventKind.STOPPED)

    close = stop

    def ingest(
        self,
        samples: Any,
        *,
        sample_rate: Optional[int] = None,
        channels: int = 1,
        sequence: Optional[int] = None,
        generation: Optional[int] = None,
        captured_at: Optional[float] = None,
        duration_ms: Optional[int] = None,
        reference_samples: Any = None,
    ) -> bool:
        """Queue one frame from a source callback or a synthetic test."""
        with self._lock:
            if self._state not in {MediaState.RUNNING, MediaState.DEGRADED}:
                return False
            device = self._device
            current_generation = self._generation
            if device is None:
                return False
            effective_sequence = int(sequence or 0)
            if effective_sequence <= 0:
                self._next_sequence += 1
                effective_sequence = self._next_sequence
            else:
                self._next_sequence = max(self._next_sequence, effective_sequence)
            # ``None`` means "fill the current generation"; an explicit zero
            # remains a stale generation and must never be reclassified.
            effective_generation = current_generation if generation is None else int(generation)
            try:
                effective_sample_rate = int(sample_rate or device.sample_rate)
                effective_channels = int(channels)
                effective_duration = (
                    _estimate_duration_ms(samples, effective_sample_rate, effective_channels)
                    if duration_ms is None
                    else int(duration_ms)
                )
                frame = AudioFrame(
                    samples=samples,
                    sample_rate=effective_sample_rate,
                    channels=effective_channels,
                    sequence=effective_sequence,
                    generation=effective_generation,
                    captured_at=time.monotonic() if captured_at is None else float(captured_at),
                    duration_ms=effective_duration,
                    reference_samples=reference_samples,
                )
            except (TypeError, ValueError) as exc:
                self._emit(
                    MediaEventKind.ERROR,
                    "MEDIA-FRAME-INVALID",
                    sequence=effective_sequence,
                    payload={"detail": str(exc)},
                )
                return False
            if frame.generation != current_generation:
                self._emit(
                    MediaEventKind.STALE_FRAME,
                    "MEDIA-GENERATION-STALE",
                    generation=frame.generation,
                    sequence=frame.sequence,
                )
                return False
            if frame.sample_rate != device.sample_rate or frame.channels != device.input_channels:
                self._emit(
                    MediaEventKind.ERROR,
                    "MEDIA-FORMAT-MISMATCH",
                    sequence=frame.sequence,
                    payload={
                        "sample_rate": frame.sample_rate,
                        "expected_sample_rate": device.sample_rate,
                        "channels": frame.channels,
                        "expected_channels": device.input_channels,
                    },
                )
                return False
            if (
                self._queue_duration_ms + frame.duration_ms > self._max_queue_duration_ms
            ):
                self._dropped_frames += 1
                self._emit(
                    MediaEventKind.BACKPRESSURE,
                    "MEDIA-BACKPRESSURE-DURATION",
                    sequence=frame.sequence,
                    payload={
                        "queue_duration_ms": self._queue_duration_ms,
                        "frame_duration_ms": frame.duration_ms,
                        "capacity_ms": self._max_queue_duration_ms,
                        "dropped_frames": self._dropped_frames,
                    },
                )
                return False
            try:
                self._queue.put_nowait(frame)
            except queue.Full:
                self._dropped_frames += 1
                self._emit(
                    MediaEventKind.BACKPRESSURE,
                    "MEDIA-BACKPRESSURE",
                    sequence=frame.sequence,
                    payload={
                        "queue_depth": self._queue.qsize(),
                        "queue_duration_ms": self._queue_duration_ms,
                        "dropped_frames": self._dropped_frames,
                    },
                )
                return False
            self._queue_duration_ms += frame.duration_ms
            self._queued_durations[id(frame)] = frame.duration_ms
            return True

    async def process_one(self) -> Optional[ProcessedAudioFrame]:
        """Process one queued frame without starting a long-running worker."""
        try:
            frame = self._queue.get_nowait()
        except queue.Empty:
            return None
        try:
            with self._lock:
                self._dequeue_duration_locked(frame)
            return await self._process(frame)
        finally:
            self._queue.task_done()

    async def run(self) -> None:
        """Continuously process frames until ``stop`` invalidates the source."""
        while True:
            with self._lock:
                if self._state is MediaState.FAILED:
                    # A failed source must not leave a consumer spinning on a
                    # queue that can no longer be replenished.  Drain queued
                    # frames as stale runtime data and exit fail-closed.
                    self._drain_queue_locked()
                    return
                should_exit = self._state is MediaState.STOPPED and self._queue.empty()
            if should_exit:
                return
            try:
                frame = await asyncio.to_thread(self._queue.get, True, 0.1)
            except queue.Empty:
                continue
            try:
                with self._lock:
                    self._dequeue_duration_locked(frame)
                await self._process(frame)
            finally:
                self._queue.task_done()

    async def wait_idle(self) -> None:
        """Wait until all frames accepted so far have reached a terminal path."""
        await asyncio.to_thread(self._queue.join)

    def health(self) -> dict:
        with self._lock:
            device = self._device.to_dict() if self._device else None
            state = self._state.value
            mode = self._assessment.mode.value
            missing = list(dict.fromkeys((*self._assessment.missing_for_c, *self._runtime_missing)))
            source = self.source
            generation = self._generation
            queue_duration_ms = self._queue_duration_ms
            dropped_frames = self._dropped_frames
            last_processed_sequence = self._last_processed_sequence
        source_health: Mapping[str, Any] = {}
        if source is not None:
            try:
                source_health = dict(source.health())
            except Exception as exc:
                source_health = {"ok": False, "error": type(exc).__name__}
        resampler_health: Mapping[str, Any] = {}
        resampler = self.resampler
        if resampler is not None:
            health = getattr(resampler, "health", None)
            try:
                resampler_health = dict(health()) if callable(health) else {"state": "unknown"}
            except Exception as exc:
                resampler_health = {"state": "health_error", "error": type(exc).__name__}
        return {
            "state": state,
            "mode": mode,
            "c_verified": mode == DuplexMode.C.value and not missing,
            "missing_for_c": missing,
            "generation": generation,
            "queue_depth": self._queue.qsize(),
            "queue_capacity": self._queue.maxsize,
            "queue_duration_ms": queue_duration_ms,
            "queue_duration_capacity_ms": self._max_queue_duration_ms,
            "dropped_frames": dropped_frames,
            "last_processed_sequence": last_processed_sequence,
            "device": device,
            "source": source_health,
            "capture_sample_rate": device.get("sample_rate") if isinstance(device, Mapping) else None,
            "processing_sample_rate": self.target_sample_rate or (device.get("sample_rate") if isinstance(device, Mapping) else None),
            "resampler": resampler_health if resampler is not None else None,
        }

    def _effective_capabilities(
        self,
        device: DeviceDescriptor,
        capabilities: ProviderCapabilities,
    ) -> ProviderCapabilities:
        effective = capabilities
        if effective.audio_route != device.route:
            # A capability declaration for one physical route cannot certify
            # another route selected by the media adapter.
            effective = replace(
                effective,
                audio_route=device.route,
                audio_route_verified=False,
            )
        elif device.route == AudioRoute.UNKNOWN.value:
            effective = replace(effective, audio_route_verified=False)
        if self.source is None:
            effective = replace(effective, continuous_capture=False)
        if self.vad is None:
            effective = replace(effective, vad_verified=False)
        if self.target_sample_rate is not None and self.target_sample_rate != device.sample_rate and self.resampler is None:
            effective = replace(effective, vad_verified=False)
        if device.output_channels <= 0:
            effective = replace(effective, playback_verified=False)
        if device.route == AudioRoute.SPEAKER_MIC.value:
            if self.aec is None or not device.reference_available:
                effective = replace(
                    effective,
                    aec_reference_available=False,
                    aec_verified=False,
                )
        return effective

    def _source_callback(self, *args: Any, **kwargs: Any) -> None:
        """Normalize sounddevice-like callbacks without importing sounddevice."""
        if not args and "samples" not in kwargs:
            self._emit(MediaEventKind.ERROR, "MEDIA-SOURCE-CALLBACK")
            return
        samples = args[0] if args else kwargs.get("samples")
        status = args[3] if len(args) >= 4 else kwargs.get("status")
        if status:
            self._runtime_degrade("MEDIA-SOURCE-STATUS", detail=str(status)[:160])
        with self._lock:
            device = self._device
        if device is not None:
            with self._lock:
                device_sample_rate = device.sample_rate
                device_channels = device.input_channels
            frame_count = args[1] if len(args) >= 2 else kwargs.get("frames")
            try:
                callback_duration = int(round(float(frame_count) * 1000 / device_sample_rate))
            except (TypeError, ValueError):
                callback_duration = None
            self.ingest(
                samples,
                sample_rate=device_sample_rate,
                channels=device_channels,
                duration_ms=callback_duration,
            )

    async def _process(self, frame: AudioFrame) -> Optional[ProcessedAudioFrame]:
        with self._lock:
            current_generation = self._generation
            device = self._device
            vad = self.vad
            aec = self.aec
            if device is None or frame.generation != current_generation:
                self._emit(
                    MediaEventKind.STALE_FRAME,
                    "MEDIA-GENERATION-STALE",
                    generation=frame.generation,
                    sequence=frame.sequence,
                )
                return None
            if frame.sequence <= self._last_processed_sequence:
                self._emit(
                    MediaEventKind.STALE_FRAME,
                    "MEDIA-SEQUENCE-STALE",
                    sequence=frame.sequence,
                )
                return None
            self._last_processed_sequence = frame.sequence

        samples = frame.samples
        processed_frame = frame
        aec_applied = False
        echo_return_loss: Optional[float] = None
        if device.route == AudioRoute.SPEAKER_MIC.value:
            if aec is None or frame.reference_samples is None:
                self._runtime_degrade(
                    "MEDIA-AEC-REFERENCE-MISSING"
                    if frame.reference_samples is None
                    else "MEDIA-AEC-UNAVAILABLE"
                )
            else:
                try:
                    result = self._call_aec(aec, samples, frame.reference_samples, frame.sample_rate)
                    if isinstance(result, tuple) and len(result) >= 2:
                        samples, echo_return_loss = result[0], float(result[1])
                    else:
                        samples = result
                    aec_applied = True
                except Exception as exc:
                    self._runtime_degrade("MEDIA-AEC-FAILED", detail=type(exc).__name__)

        if self.denoiser is not None and frame.sample_rate >= 44_100:
            try:
                processed, _prob = self.denoiser.process_mono(samples, frame.sample_rate)
                if processed is not None and processed.size:
                    samples = processed
                    processed_frame = replace(
                        frame, samples=samples, sample_rate=16_000, channels=1
                    )
            except Exception as exc:
                self._runtime_degrade("MEDIA-DENOISER-FAILED", detail=type(exc).__name__)
                return None
        elif self.target_sample_rate is not None and self.target_sample_rate != frame.sample_rate:
            if self.resampler is None:
                self._runtime_degrade("MEDIA-RESAMPLER-UNAVAILABLE")
                return None
            try:
                samples = self.resampler.process(samples, frame.sample_rate, self.target_sample_rate)
                processed_frame = replace(
                    frame,
                    samples=samples,
                    sample_rate=self.target_sample_rate,
                    channels=1,
                )
            except Exception as exc:
                self._runtime_degrade("MEDIA-RESAMPLER-FAILED", detail=type(exc).__name__)
                return None

        speech: Optional[bool] = None
        if vad is not None:
            if self.voice_gate is not None:
                gate = getattr(self.voice_gate, "allow", None)
                if callable(gate):
                    try:
                        import numpy as _np

                        frame_rms = float(_np.sqrt(float(_np.mean(_np.square(samples)))))
                        if not gate(frame_rms) and processed_frame.sample_rate:
                            # Playback-reference mask (对话DEMO borrow, 0130):
                            # the assistant is speaking loudly enough that a
                            # likely echo must not open a new speech window.
                            self._update_speech_edge(processed_frame, False)
                            return None
                    except Exception:
                        self._runtime_degrade("MEDIA-VOICE-GATE-FAILED", detail=type(exc).__name__)
                        return None
            try:
                speech = bool(vad.detect_speech(samples, processed_frame.sample_rate))
            except Exception as exc:
                self._runtime_degrade("MEDIA-VAD-FAILED", detail=type(exc).__name__)
                return None
            self._update_speech_edge(processed_frame, speech)

        processed = ProcessedAudioFrame(
            frame=processed_frame,
            samples=samples,
            speech=speech,
            aec_applied=aec_applied,
            echo_return_loss=echo_return_loss,
        )
        handler = self.on_frame
        if handler is not None:
            try:
                result = handler(processed)
                if inspect.isawaitable(result):
                    await result
            except Exception as exc:
                self._runtime_degrade("MEDIA-FRAME-HANDLER-FAILED", detail=type(exc).__name__)
        return processed

    @staticmethod
    def _call_aec(aec: Any, mic: Any, reference: Any, sample_rate: int) -> Any:
        if hasattr(aec, "process"):
            return aec.process(mic, reference, sample_rate)
        if hasattr(aec, "process_audio"):
            return aec.process_audio(mic, reference, sample_rate)
        raise MediaError("AEC adapter has no process method")

    def _update_speech_edge(self, frame: AudioFrame, speech: bool) -> None:
        with self._lock:
            previous = self._speech_active
            self._speech_active = speech
        if speech and not previous:
            self._emit(MediaEventKind.SPEECH_STARTED, sequence=frame.sequence)
        elif previous and not speech:
            self._emit(MediaEventKind.SPEECH_ENDED, sequence=frame.sequence)
            reset = getattr(self.denoiser, "reset", None)
            if callable(reset):
                # N.E.K.O. borrow (0131): RNNoise GRU state drifts on steady
                # background noise; reset it once the speech window ends.
                try:
                    reset()
                except Exception:
                    pass

    def _runtime_degrade(self, code: str, *, detail: Optional[str] = None) -> None:
        with self._lock:
            if code not in self._runtime_missing:
                self._runtime_missing.append(code)
            self._state = MediaState.DEGRADED
            missing = tuple(dict.fromkeys((*self._assessment.missing_for_c, *self._runtime_missing)))
            self._assessment = CapabilityAssessment(DuplexMode.B, missing)
        payload = {"detail": detail} if detail else {}
        self._emit(MediaEventKind.ERROR, code, payload=payload)

    def _drain_queue_locked(self) -> None:
        while True:
            try:
                frame = self._queue.get_nowait()
            except queue.Empty:
                return
            else:
                self._dequeue_duration_locked(frame)
                self._queue.task_done()

    def _dequeue_duration_locked(self, frame: AudioFrame) -> None:
        duration = self._queued_durations.pop(id(frame), frame.duration_ms)
        self._queue_duration_ms = max(0, self._queue_duration_ms - duration)

    def _emit(
        self,
        kind: MediaEventKind,
        code: Optional[str] = None,
        *,
        generation: Optional[int] = None,
        sequence: int = 0,
        payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        with self._lock:
            self._event_sequence += 1
            event = MediaEvent(
                kind=kind.value,
                code=code,
                event_seq=self._event_sequence,
                generation=self._generation if generation is None else generation,
                sequence=sequence,
                timestamp=time.time(),
                payload=dict(payload or {}),
            )
            sink = self.on_event
        if sink is not None:
            try:
                sink(event)
            except Exception:
                logger.exception("media event sink failed for %s", kind.value)


class SoundDeviceInputSource:
    """Optional lazy sounddevice bridge; importing this class has no side effect."""

    def __init__(self, sounddevice_module: Any = None, *, blocksize: int = 1600) -> None:
        if blocksize <= 0:
            raise ValueError("blocksize must be positive")
        self._sd = sounddevice_module
        self._blocksize = blocksize
        self._stream: Any = None
        self._device: Optional[DeviceDescriptor] = None

    def _module(self) -> Any:
        if self._sd is None:
            try:
                import sounddevice as sd  # type: ignore
            except ImportError as exc:
                raise MediaError("sounddevice is not installed") from exc
            self._sd = sd
        return self._sd

    def enumerate_devices(self) -> list[dict]:
        rows = self._module().query_devices()
        devices = []
        for index, row in enumerate(rows):
            input_channels = int(row.get("max_input_channels", 0))
            output_channels = int(row.get("max_output_channels", 0))
            if input_channels <= 0:
                continue
            devices.append(
                DeviceDescriptor(
                    device_id=str(index),
                    name=str(row.get("name", "unknown")),
                    input_channels=input_channels,
                    output_channels=output_channels,
                    sample_rate=int(float(row.get("default_samplerate", 16_000))),
                    # Endpoint channel counts do not identify the physical
                    # microphone/playback route. Route selection must be an
                    # explicit higher-level decision before C is considered.
                    route=AudioRoute.UNKNOWN.value,
                ).to_dict()
            )
        return devices

    def start(self, callback: Callable[..., Any], device: DeviceDescriptor) -> None:
        sd = self._module()

        def capture_callback(*args: Any, **kwargs: Any) -> None:
            """Detach PortAudio's reusable callback buffer before queueing it."""
            if args:
                samples = args[0]
                copier = getattr(samples, "copy", None)
                if callable(copier):
                    args = (copier(), *args[1:])
            elif "samples" in kwargs:
                samples = kwargs["samples"]
                copier = getattr(samples, "copy", None)
                if callable(copier):
                    kwargs = dict(kwargs)
                    kwargs["samples"] = copier()
            callback(*args, **kwargs)

        # Device probes use string IDs for serializable metadata, whereas
        # sounddevice treats a numeric string as a device name rather than an
        # index. Convert only canonical integer IDs; named endpoints remain
        # named endpoints.
        device_argument: Any = device.device_id
        try:
            device_argument = int(device.device_id)
        except (TypeError, ValueError):
            pass
        stream = sd.InputStream(
            samplerate=device.sample_rate,
            channels=device.input_channels,
            dtype="float32",
            blocksize=self._blocksize,
            device=device_argument,
            callback=capture_callback,
        )
        try:
            stream.start()
        except Exception:
            close = getattr(stream, "close", None)
            if callable(close):
                close()
            raise
        self._stream = stream
        self._device = device

    def stop(self) -> None:
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.stop()
            finally:
                stream.close()
        self._device = None

    def health(self) -> Mapping[str, Any]:
        stream = self._stream
        return {
            "ok": stream is not None and bool(getattr(stream, "active", True)),
            "kind": "sounddevice",
            "device_id": self._device.device_id if self._device else None,
        }


__all__ = [
    "AudioFrame",
    "DeviceDescriptor",
    "InputSource",
    "MediaAdapter",
    "MediaError",
    "MediaEvent",
    "MediaEventKind",
    "MediaState",
    "ProcessedAudioFrame",
    "ResamplerPort",
    "SoundDeviceInputSource",
]
