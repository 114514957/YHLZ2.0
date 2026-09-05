"""Hexagonal driven-adapter: hybrid LLM provider (API primary + local backup).

Routes streaming chat to a primary OpenAI-compatible endpoint (typically a
cloud API) and fails over to a local endpoint (typically Ollama on
127.0.0.1:11434) when the primary is unhealthy.  Implements the same
``LLMProviderPort`` contract so the voice chain never sees the difference.

Policy:
- primary health probe runs lazily at the start of each stream and on demand;
- a healthy primary is sticky: only two consecutive probe failures switch to
  the backup;
- after a switch, the primary is retried after ``recheck_s`` seconds and the
  route returns only when a probe succeeds;
- both endpoints down: stream raises ``LLM-PROVIDER-ALL-DOWN`` (fail-closed).

Never saves prompts, outputs, or business text.
"""

from __future__ import annotations

import asyncio
import inspect
import time
from typing import Any, AsyncIterator, Dict, Optional

from backend.llm_provider_port import LLMProviderError, LLMProviderState, is_llm_provider_port

DEFAULT_PROBE_TIMEOUT = 2.0
DEFAULT_RECHECK_S = 60.0
DEFAULT_FAIL_THRESHOLD = 2


class HybridLLMProvider:
    """Route API-first, local-fallback bridge over two provider ports."""

    def __init__(
        self,
        primary: Any,
        backup: Any,
        *,
        probe_timeout_s: float = DEFAULT_PROBE_TIMEOUT,
        recheck_s: float = DEFAULT_RECHECK_S,
        fail_threshold: int = DEFAULT_FAIL_THRESHOLD,
    ) -> None:
        if not is_llm_provider_port(primary):
            raise ValueError("primary must conform to LLMProviderPort")
        if not is_llm_provider_port(backup):
            raise ValueError("backup must conform to LLMProviderPort")
        self.primary = primary
        self.backup = backup
        self.probe_timeout_s = float(probe_timeout_s)
        self.recheck_s = float(recheck_s)
        self.fail_threshold = int(max(1, fail_threshold))
        self.state = LLMProviderState.IDLE
        self.last_error_code: Optional[str] = None
        self._consecutive_failures = 0
        self._using_backup = False
        self._next_probe_at = 0.0

    @property
    def using_backup(self) -> bool:
        return self._using_backup

    async def _probe(self, provider: Any) -> bool:
        raw = provider.health()
        if inspect.isawaitable(raw):
            raw = await raw
        return bool(raw and raw.get("available"))

    def _route(self) -> Any:
        if self._using_backup:
            return self.backup
        return self.primary

    async def _maybe_recheck_primary(self) -> None:
        now = time.monotonic()
        if not self._using_backup or now < self._next_probe_at:
            return
        try:
            ok = await asyncio.wait_for(
                self._probe(self.primary), timeout=self.probe_timeout_s
            )
        except (asyncio.TimeoutError, Exception):
            ok = False
        if ok:
            self._using_backup = False
            self._consecutive_failures = 0
            self.last_error_code = None
        else:
            self._next_probe_at = now + self.recheck_s

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
        await self._maybe_recheck_primary()
        while True:
            endpoint = self._route()
            try:
                started = time.monotonic()
                async for delta in endpoint.stream_chat(
                    messages,
                    signal=signal,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    tools=tools,
                    tool_choice=tool_choice,
                ):
                    yield delta
                if endpoint is self.primary:
                    self._consecutive_failures = 0
                    self.last_error_code = None
                return
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.last_error_code = getattr(exc, "code", None) or type(exc).__name__
                if endpoint is self.primary and not self._using_backup:
                    self._consecutive_failures += 1
                    if self._consecutive_failures >= self.fail_threshold:
                        self._using_backup = True
                        self._next_probe_at = time.monotonic() + self.recheck_s
                        continue
                    raise
                if endpoint is self.backup:
                    raise LLMProviderError(
                        "LLM-PROVIDER-ALL-DOWN",
                        "primary and backup endpoints both failed",
                    ) from exc
                raise

    def abort(self, reason: str = "interrupt") -> None:
        self.primary.abort(reason)
        self.backup.abort(reason)

    async def wait_stopped(self, timeout_s: float) -> bool:
        task = None
        try:
            name = "_stream_task"
            task = getattr(self._route(), name, None)
        except Exception:
            task = None
        if task is not None and not getattr(task, "done", lambda: True)():
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=float(timeout_s))
            except (asyncio.TimeoutError, asyncio.CancelledError):
                return False
        return True

    def stop(self, reason: str = "shutdown") -> None:
        self.primary.stop(reason)
        self.backup.stop(reason)

    def health(self) -> dict:
        return {
            "available": True,
            "port_version": "1.1",
            "provider_id": "hybrid-api-local",
            "using_backup": bool(self._using_backup),
            "primary_consecutive_failures": int(self._consecutive_failures),
            "state": self.state.value,
            "error_code": self.last_error_code,
        }
