"""Provider-neutral streaming LLM contract for the isolated voice chain.

The legacy :mod:`backend.llm_engine` mixes network clients, mock fallbacks and
no observable stop state.  This module is the small boundary used by the
target chain (Hexagonal driven-port, see ADR-006).  A provider may implement
the contract in a remote process (e.g. a WSL vLLM OpenAI-compatible server);
capability flags describe that fact but never certify behaviour.

Deliberately no network, model, persistence or device dependency here.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, AsyncIterator, Dict, Mapping, Optional, Protocol, runtime_checkable


LLM_PORT_VERSION = "1.1"


class LLMProviderError(RuntimeError):
    """A fail-closed error carrying an operational error code."""

    def __init__(self, code: str, detail: str = "") -> None:
        self.code = str(code or "LLM-UNKNOWN")[:160]
        self.detail = str(detail or "")[:400]
        message = self.code if not self.detail else f"{self.code}: {self.detail}"
        super().__init__(message)


class LLMProviderState(str, Enum):
    IDLE = "idle"
    STREAMING = "streaming"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class LLMProviderCapabilities:
    """Declared provider capabilities, separate from runtime evidence."""

    provider_id: str
    streaming: bool = True
    cancel_observable: bool = False
    max_model_len: int = 0
    endpoint: str = "openai-compatible"


@dataclass(frozen=True, slots=True)
class LLMStreamMetrics:
    """De-identified runtime metrics for one stream call."""

    first_token_ms: Optional[float] = None
    tokens: int = 0
    elapsed_ms: Optional[float] = None
    finish_reason: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "first_token_ms": self.first_token_ms,
            "tokens": self.tokens,
            "elapsed_ms": self.elapsed_ms,
            "finish_reason": self.finish_reason,
        }


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


@runtime_checkable
class LLMProviderPort(Protocol):
    """Streaming chat-completion boundary (Hexagonal driven port).

    ``messages`` follows the OpenAI chat shape with role/content pairs.
    ``signal`` is optional; when provided it must expose ``is_cancelled()``.
    The provider must stop yielding promptly when its call is aborted and any
    completion must be observable through ``wait_stopped``.
    """

    async def stream_chat(
        self,
        messages: list[Dict[str, str]],
        *,
        signal: Optional[Any] = None,
        temperature: float = 0.7,
        max_tokens: int = 256,
        tools: Optional[list[Dict[str, Any]]] = None,
        tool_choice: Optional[Any] = None,
    ) -> AsyncIterator[str]:
        """Yields response text deltas.

        ``tools``/``tool_choice`` (port 1.1) are pass-through in OpenAI shape
        (e.g. ``tools=[{"type":"function","function":{...}}]``) so an Agent
        layer can upgrade from the driving side without touching the core.
        """

    def abort(self, reason: str = "interrupt") -> None: ...

    async def wait_stopped(self, timeout_s: float) -> bool: ...

    def stop(self, reason: str = "shutdown") -> None: ...

    def health(self) -> dict: ...


def is_llm_provider_port(value: Any) -> bool:
    return isinstance(value, LLMProviderPort) and callable(value.stream_chat)


# Re-export capability flags used by downstream validation (e.g. the target
# composition root may fail-closed when the port claims no streaming).
def llm_health_snapshot(provider: Any) -> dict:
    try:
        return _safe_payload(dict(provider.health() or {}))
    except Exception as exc:
        return {"available": False, "state": "error", "error_code": type(exc).__name__}
