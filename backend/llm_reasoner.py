"""Hexagonal driven-adapter: LLM Reasoner for the target voice chain.

Bridges an ``LLMProviderPort`` to the ``reasoner.generate(text, signal)``
contract used by ``TargetVoiceChain`` (ADR-006/ADR-002).  The system prompt is
fixed for probe validation: "先进始于计算，元亨开拓未来".  No memory, no
business history, no persistence.
"""

from __future__ import annotations

import asyncio
import inspect
import time
from typing import Any, AsyncIterator, Dict, Optional

from backend.llm_provider_port import LLMProviderError, is_llm_provider_port

SYSTEM_PROMPT = "先进始于计算，元亨开拓未来"


class LLMReasoner:
    """Streaming chat reasoner backed by any conforming LLM provider port."""

    def __init__(
        self,
        provider: Any,
        *,
        system_prompt: str = SYSTEM_PROMPT,
        temperature: float = 0.7,
        max_tokens: int = 256,
        memory_service: Any = None,
    ) -> None:
        if not is_llm_provider_port(provider):
            raise ValueError("LLMReasoner requires a conforming LLMProviderPort")
        self.provider = provider
        self.system_prompt = str(system_prompt or SYSTEM_PROMPT)
        self.temperature = float(temperature)
        self.max_tokens = int(max_tokens)
        self.tools: Optional[list[Dict[str, Any]]] = None
        self.tool_choice: Optional[Any] = None
        self.memory_service = memory_service
        self._summary_tasks: list[Any] = []
        self.last_error_code: Optional[str] = None
        self.last_error_detail: str = ""
        self.last_first_token_ms: Optional[float] = None
        self.last_tokens: int = 0

    async def generate(self, text: str, signal: Any):
        memory = self.memory_service
        system_parts = [self.system_prompt]
        if memory is not None:
            persona = memory.persona_draft()
            if persona and persona != self.system_prompt:
                system_parts.append(persona)
            memory.append_turn(role="user", text=str(text or ""))
        messages: list[Dict[str, str]] = [
            {"role": "system", "content": "\n".join(system_parts)[:2000]},
        ]
        if memory is not None:
            ctx = memory.context_block()
            if ctx:
                messages.append({"role": "system", "content": ctx[:2500]})
        messages.append({"role": "user", "content": str(text or "")})
        resp_parts: list[str] = []
        self.last_error_code = None
        self.last_error_detail = ""
        self.last_first_token_ms = None
        self.last_tokens = 0
        started = time.perf_counter()
        try:
            async for delta in self.provider.stream_chat(
                messages,
                signal=signal,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                tools=self.tools,
                tool_choice=self.tool_choice,
            ):
                if signal is not None and signal.is_cancelled():
                    return
                if self.last_first_token_ms is None:
                    self.last_first_token_ms = round((time.perf_counter() - started) * 1000, 1)
                self.last_tokens += 1
                resp_parts.append(str(delta or ""))
                yield str(delta or "")
            if memory is not None:
                memory.append_turn(role="assistant", text="".join(resp_parts))
                if memory._summary_pending:
                    task = asyncio.ensure_future(memory.process_summary())
                    self._summary_tasks.append(task)
        except LLMProviderError as exc:
            self.last_error_code = exc.code
            self.last_error_detail = exc.detail
            raise
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.last_error_code = "REASONER-GENERATE-FAILED"
            self.last_error_detail = type(exc).__name__
            raise LLMProviderError(self.last_error_code, self.last_error_detail) from exc

    async def health(self) -> dict:
        raw = self.provider.health()
        if inspect.isawaitable(raw):
            raw = await raw
        base = dict(raw or {})
        base.update(
            {
                "reasoner_error_code": self.last_error_code,
                "reasoner_detail": self.last_error_detail[:160],
                "reasoner_first_token_ms": self.last_first_token_ms,
                "reasoner_tokens": self.last_tokens,
            }
        )
        return base
