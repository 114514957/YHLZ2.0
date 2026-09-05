"""Structured event relay from target adapters into the Session Journal."""

from __future__ import annotations

from typing import Any, Dict, Mapping

from backend.session_kernel import EventKind, SessionKernel


_SENSITIVE_KEYS = {
    "audio",
    "audio_ref",
    "content",
    "input",
    "raw_audio",
    "text",
    "transcript",
}


def _safe_value(value: Any, key: str = "") -> Any:
    if key.lower() in _SENSITIVE_KEYS:
        return "[redacted]"
    if isinstance(value, Mapping):
        return {str(k): _safe_value(v, str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe_value(item) for item in value]
    if isinstance(value, str):
        return value[:160]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return repr(value)[:160]


class RuntimeEventRelay:
    """Forward operational events while preserving the Kernel as sole journal owner."""

    def __init__(self, kernel: SessionKernel) -> None:
        self.kernel = kernel

    def media(self, event: Any) -> None:
        self._forward("media", event)

    def segment(self, event: Any) -> None:
        self._forward("segment", event)

    def asr(self, event: Any) -> None:
        self._forward("asr", event)

    def playback(self, event: Any) -> None:
        self._forward("playback", event)

    def _forward(self, component: str, event: Any) -> None:
        kind = str(getattr(event, "kind", "EVENT"))
        code = getattr(event, "code", None)
        if code is None:
            payload = getattr(event, "payload", {}) or {}
            code = payload.get("code") if isinstance(payload, Mapping) else None
        code_text = str(code) if code is not None else ""
        is_error = (
            "ERROR" in kind
            or "BACKPRESSURE" in kind
            or "UNDERRUN" in kind
            or bool(code_text.endswith(("ERROR", "FAILED", "TIMEOUT")))
            or "BACKPRESSURE" in code_text
            or "UNDERRUN" in code_text
        )
        payload: Dict[str, Any] = {
            "component": component,
            "event_kind": kind,
            "source_event_seq": getattr(event, "event_seq", 0),
        }
        if code is not None:
            payload["code"] = str(code)[:160]
        raw_payload = getattr(event, "payload", {})
        if isinstance(raw_payload, Mapping):
            payload["details"] = _safe_value(dict(raw_payload))
        turn_id = getattr(event, "turn_id", None)
        if turn_id is not None:
            turn_id = str(turn_id)[:160]
        trace_id = getattr(event, "trace_id", "") or ""
        self.kernel.record_system_event(
            EventKind.ERROR if is_error else EventKind.TASK,
            payload,
            generation=getattr(event, "generation", None),
            turn_id=turn_id,
            trace_id=str(trace_id)[:160],
        )


__all__ = ["RuntimeEventRelay"]
