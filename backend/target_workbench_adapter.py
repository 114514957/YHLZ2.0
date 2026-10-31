"""Thin workbench adapter for the isolated Target voice graph.

The workbench is allowed to choose a pipeline and an audio route, but it must
not own SessionKernel, turn generations, cancellation, history, or playback
state.  This module is deliberately a boundary adapter: all execution stays
inside TargetVoiceChain/TargetVoiceRuntime.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional

from backend.target_chain import PipelineSubmission, TargetVoiceChain
from backend.target_runtime import TargetVoiceRuntime


logger = logging.getLogger(__name__)

PIPELINE_LEGACY = "legacy"
PIPELINE_TARGET = "target"
AUDIO_ROUTE_UNKNOWN = "unknown"
AUDIO_ROUTE_HEADSET = "headset"
AUDIO_ROUTE_SPEAKER_MIC = "speaker_mic"
_ALLOWED_ROUTES = frozenset(
    {AUDIO_ROUTE_UNKNOWN, AUDIO_ROUTE_HEADSET, AUDIO_ROUTE_SPEAKER_MIC}
)


@dataclass(frozen=True, slots=True)
class WorkbenchVoiceRequest:
    """Normalized workbench policy fields; no live session state is retained."""

    pipeline: str = PIPELINE_LEGACY
    continuous: bool = False
    audio_route: str = AUDIO_ROUTE_UNKNOWN


@dataclass(frozen=True, slots=True)
class WorkbenchTurnResult:
    """Business result (contains text); telemetry must omit text."""

    pipeline: str
    status: str
    turn_id: Optional[str] = None
    text: str = ""
    error_code: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "pipeline": self.pipeline,
            "status": self.status,
            "turn_id": self.turn_id,
            "text": self.text,
            "error_code": self.error_code,
        }


class TargetWorkbenchAdapter:
    """Delegate Target workbench operations without creating a second graph."""

    def __init__(
        self,
        *,
        chain: TargetVoiceChain,
        runtime: Optional[TargetVoiceRuntime] = None,
        event_sink: Optional[Callable[[dict], Any]] = None,
    ) -> None:
        required_chain_methods = ("submit_transcript", "interrupt", "snapshot")
        if any(not callable(getattr(chain, name, None)) for name in required_chain_methods):
            raise TypeError("chain must expose TargetVoiceChain operations")
        if runtime is not None:
            if runtime.chain is not chain:
                raise ValueError("runtime and adapter must share the same TargetVoiceChain")
        if event_sink is not None and not callable(event_sink):
            raise TypeError("event_sink must be callable or None")
        if inspect.iscoroutinefunction(event_sink) or inspect.iscoroutinefunction(getattr(event_sink, '__call__', None)):
            raise TypeError('event_sink must be synchronous')
        self.chain = chain
        self.runtime = runtime
        self.event_sink = event_sink

    @staticmethod
    def normalize_request(body: Optional[Mapping[str, Any]]) -> WorkbenchVoiceRequest:
        """Normalize a JSON-like body; omitted pipeline remains legacy-safe."""
        if body is None:
            body = {}
        if not isinstance(body, Mapping):
            raise TypeError("workbench request must be a mapping")

        pipeline = str(body.get("pipeline", PIPELINE_LEGACY) or PIPELINE_LEGACY).strip().lower()
        if pipeline not in {PIPELINE_LEGACY, PIPELINE_TARGET}:
            raise ValueError("pipeline must be 'legacy' or 'target'")

        continuous_value = body.get("continuous", False)
        if isinstance(continuous_value, bool):
            continuous = continuous_value
        elif isinstance(continuous_value, (int, float)) and continuous_value in (0, 1):
            continuous = bool(continuous_value)
        elif isinstance(continuous_value, str) and continuous_value.strip().lower() in {
            "true", "1", "yes", "on"
        }:
            continuous = True
        elif isinstance(continuous_value, str) and continuous_value.strip().lower() in {
            "false", "0", "no", "off", ""
        }:
            continuous = False
        else:
            raise ValueError("continuous must be a boolean")

        default_route = AUDIO_ROUTE_SPEAKER_MIC if pipeline == PIPELINE_TARGET else AUDIO_ROUTE_UNKNOWN
        route = str(body.get("audio_route", default_route) or default_route).strip().lower()
        if route not in _ALLOWED_ROUTES:
            raise ValueError("audio_route must be unknown, headset, or speaker_mic")
        if pipeline == PIPELINE_TARGET and route == AUDIO_ROUTE_UNKNOWN:
            raise ValueError("target audio_route must be speaker_mic or headset")
        return WorkbenchVoiceRequest(pipeline, continuous, route)

    @staticmethod
    def is_target_request(body: Optional[Mapping[str, Any]]) -> bool:
        """Return whether a request explicitly opts into Target."""
        try:
            return TargetWorkbenchAdapter.normalize_request(body).pipeline == PIPELINE_TARGET
        except (TypeError, ValueError):
            return False

    async def submit_text(self, text: str, *, source: str = "workbench") -> WorkbenchTurnResult:
        """Submit one final transcript through the existing Target chain."""
        transcript = str(text or "").strip()
        if not transcript:
            return WorkbenchTurnResult(PIPELINE_TARGET, "failed", error_code="EMPTY-TRANSCRIPT")
        return await self._submit(transcript, source=source)

    async def submit_audio(self, audio, *, text: str = "",
                           source: str = "daemon_audio") -> WorkbenchTurnResult:
        """Submit one audio turn (节点A) through the same Target chain.

        The clip gets the same generation lease / TTS content queue /
        cancellation as a text turn; ``text`` is an optional placeholder the
        wake gate observes (audio turns may leave it empty).
        """
        audio_list = [str(a) for a in (audio or []) if a][:2]
        if not audio_list:
            return WorkbenchTurnResult(PIPELINE_TARGET, "failed",
                                       error_code="EMPTY-AUDIO")
        return await self._submit(str(text or "").strip(), source=source,
                                  audio=audio_list)

    async def _submit(self, transcript: str, *, source: str,
                      audio: Optional[list] = None) -> WorkbenchTurnResult:
        try:
            kwargs: dict[str, Any] = {"source": source}
            if audio:
                kwargs["audio"] = audio
                kwargs["explicit_audio"] = True
            submission = await self.chain.submit_transcript(transcript, **kwargs)
            if not isinstance(submission, PipelineSubmission):
                return WorkbenchTurnResult(
                    PIPELINE_TARGET, "failed", error_code="TARGET-SUBMISSION-CONTRACT"
                )
            lease = submission.lease
            if lease is None:
                event = getattr(submission.decision, "event", None)
                code = getattr(event, "value", None) or str(event or "INPUT-IGNORED")
                result = WorkbenchTurnResult(PIPELINE_TARGET, "ignored", error_code=code)
                self._emit("turn_ignored", result)
                return result
            if submission.task is None:
                result = WorkbenchTurnResult(
                    PIPELINE_TARGET,
                    "failed",
                    turn_id=lease.turn_id,
                    error_code="TARGET-TASK-MISSING",
                )
                self._emit("turn_failed", result)
                return result
            # The chain owns the task. HTTP waiter cancellation must not bypass
            # kernel cancellation. The session owner must explicitly stop/interrupt.
            outcome = await asyncio.shield(submission.task)
            status = str(getattr(outcome, "status", "completed") or "completed")
            result = WorkbenchTurnResult(
                PIPELINE_TARGET,
                status,
                turn_id=str(getattr(outcome, "turn_id", None) or lease.turn_id),
                text=str(getattr(outcome, "text", "") or ""),
                error_code=getattr(outcome, "error_code", None),
            )
            self._emit("turn_done", result)
            return result
        except Exception as exc:  # noqa: BLE001
            result = WorkbenchTurnResult(
                PIPELINE_TARGET,
                "failed",
                error_code=_error_code(exc),
            )
            self._emit("turn_failed", result)
            return result

    def ingest(self, samples: Any, **kwargs: Any) -> bool:
        """Forward audio to the one bound runtime; return false when not started."""
        runtime = self.runtime
        if runtime is None:
            return False
        return bool(runtime.ingest(samples, **kwargs))

    async def start(self, device: Any, capabilities: Any) -> Any:
        runtime = self._require_runtime()
        result = runtime.start(device, capabilities)
        self._emit("runtime_started", {"status": "started"})
        return result

    async def run(self) -> None:
        await self._require_runtime().run()

    async def interrupt(self, reason: str = "workbench_interrupt", timeout_s: float = 3.0) -> Any:
        result = await self.chain.interrupt(reason, timeout_s=timeout_s)
        self._emit("interrupt_result", {"status": "returned", "timed_out": bool(getattr(result, "timed_out_tasks", ())), "failed": bool(getattr(result, "failed_tasks", ()))})
        return result

    async def stop(self, reason: str = "workbench_stop") -> None:
        runtime = self.runtime
        if runtime is not None:
            await runtime.stop(reason)
        else:
            await self.chain.shutdown()
        self._emit("runtime_stopped", {"status": "stopped"})

    def health(self) -> dict:
        runtime = self.runtime
        return {
            "pipeline": PIPELINE_TARGET,
            "runtime": runtime.health() if runtime is not None else None,
            "chain": self.chain.snapshot(),
        }

    def _require_runtime(self) -> TargetVoiceRuntime:
        if self.runtime is None:
            raise RuntimeError("TARGET-RUNTIME-MISSING")
        return self.runtime

    def _emit(self, event: str, payload: Any) -> None:
        sink = self.event_sink
        if sink is None:
            return
        if isinstance(payload, WorkbenchTurnResult):
            payload = {
                "pipeline": payload.pipeline,
                "status": payload.status,
                "turn_id": payload.turn_id,
                "error_code": payload.error_code,
            }
        elif not isinstance(payload, Mapping):
            payload = {"status": str(payload)[:80]}
        safe = {"event": str(event)[:80], **_safe_mapping(payload)}
        try:
            value = sink(safe)
            if inspect.isawaitable(value):
                close = getattr(value, "close", None)
                if callable(close):
                    close()
                logger.warning("workbench event sink must be synchronous; event not delivered")
        except Exception:
            logger.warning("workbench event sink failed")


def _error_code(exc: BaseException) -> str:
    """Never copy arbitrary provider messages/codes into telemetry."""
    return "TARGET-ADAPTER-ERROR"


def _safe_mapping(value: Mapping[str, Any]) -> dict:
    sensitive = {"audio", "audio_ref", "content", "input", "raw_audio", "text", "transcript", "api_key", "token", "authorization"}

    def clean(item: Any) -> Any:
        if isinstance(item, Mapping):
            return _safe_mapping(item)
        if isinstance(item, (list, tuple)):
            return [clean(part) for part in item[:32]]
        if isinstance(item, (str, int, float, bool)) or item is None:
            return item
        return "[redacted]"

    return {
        str(key): "[redacted]" if str(key).lower() in sensitive else clean(item)
        for key, item in value.items()
    }

__all__ = [
    "AUDIO_ROUTE_HEADSET",
    "AUDIO_ROUTE_SPEAKER_MIC",
    "AUDIO_ROUTE_UNKNOWN",
    "PIPELINE_LEGACY",
    "PIPELINE_TARGET",
    "TargetWorkbenchAdapter",
    "WorkbenchTurnResult",
    "WorkbenchVoiceRequest",
]
