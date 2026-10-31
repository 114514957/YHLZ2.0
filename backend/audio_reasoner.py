"""Audio-aware reasoner adapter for the Target chain (节点A：联合流式).

An accepted turn may carry an audio clip instead of ASR text.  This adapter
gives that clip the **same** ``TargetVoiceChain`` generation lease, TTS content
queue and cancellation as a text turn: it builds an OpenAI ``input_audio`` user
message and streams the local model's content deltas through the same
``LLMProviderPort``.  No second session/kernel and no extra model process.

Text turns keep the ``generate`` contract; audio turns use ``generate_audio``
(the chain calls it only when the reasoner advertises it — see
``TargetVoiceChain._reasoner_generate``).
"""

from __future__ import annotations

import time
from typing import Any, Callable, Optional

from backend.llm_provider_port import LLMProviderError, is_llm_provider_port

SYSTEM_PROMPT = "先进始于计算，元亨开拓未来"


def _default_audio_parts(audio: list) -> list[dict]:
    """Local wav path / data-uri -> llama.cpp ``input_audio`` content parts."""
    from backend.target_orchestrator import _to_input_audio

    parts: list[dict] = []
    for item in (audio or [])[:2]:
        part = _to_input_audio(str(item)) if item else None
        if part:
            parts.append(part)
    return parts


class AudioReasoner:
    """Streaming reasoner that also accepts a per-turn audio clip."""

    def __init__(
        self,
        provider: Any,
        *,
        system_prompt: str = SYSTEM_PROMPT,
        audio_builder: Optional[Callable[[list], list]] = None,
        temperature: float = 0.7,
        max_tokens: int = 256,
    ) -> None:
        if not is_llm_provider_port(provider):
            raise ValueError("AudioReasoner requires a conforming LLMProviderPort")
        self.provider = provider
        self.system_prompt = str(system_prompt or SYSTEM_PROMPT)
        self.temperature = float(temperature)
        self.max_tokens = int(max_tokens)
        self._audio_builder = audio_builder or _default_audio_parts
        self.last_error_code: Optional[str] = None
        self.last_first_token_ms: Optional[float] = None
        self.last_tokens = 0

    async def generate(self, text: str, signal: Any):
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": str(text or "")},
        ]
        async for delta in self._stream(messages, signal):
            yield delta

    async def generate_audio(self, text: str, audio: list, signal: Any):
        content: list[dict] = [{"type": "text", "text": str(text or "")}]
        content.extend(self._audio_builder(audio))
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": content},
        ]
        async for delta in self._stream(messages, signal):
            yield delta

    async def _stream(self, messages: list, signal: Any):
        self.last_error_code = None
        self.last_first_token_ms = None
        self.last_tokens = 0
        started = time.perf_counter()
        try:
            async for delta in self.provider.stream_chat(
                messages,
                signal=signal,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                tools=None,
                tool_choice=None,
            ):
                if signal is not None and signal.is_cancelled():
                    return
                if self.last_first_token_ms is None:
                    self.last_first_token_ms = round(
                        (time.perf_counter() - started) * 1000, 1)
                self.last_tokens += 1
                yield str(delta or "")
        except LLMProviderError:
            raise
        except Exception as exc:  # noqa: BLE001
            self.last_error_code = "AUDIO-REASONER-FAILED"
            raise LLMProviderError(self.last_error_code, type(exc).__name__) from exc
