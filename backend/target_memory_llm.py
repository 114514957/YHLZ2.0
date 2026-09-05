"""LLM hooks for the target memory service (ledger 0120 responsibility split).

Cloud side (Hybrid, API-first): candidate generation, initial importance,
candidate summary, and early-turn compression.
Local side (Ollama-specific): adjudication — only the local rail may decide
accept/downgrade/cold/archive; failures degrade gracefully and never delete.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any, Optional

from backend.llm_vllm_provider import LlmVllmProvider
from backend.target_prompts import (
    MEMORY_L1_COMPRESS_PROMPT as _COMPRESS_PROMPT,
    MEMORY_L2_CANDIDATE_PROMPT as _CANDIDATE_PROMPT,
    MEMORY_L2_JUDGE_PROMPT as _JUDGE_PROMPT,
)


class MemoryLLMService:
    """Local-screener + cloud-adjudicator hooks (ledger 0138 revision).

    Screening (which candidates to keep) is done by the local rail first so
    the cloud is sparingly used; the cloud then finalizes importance and
    status (adjudication).  Failure degrades gracefully and never deletes.
    """

    def __init__(
        self,
        hybrid: Any,
        *,
        local: Optional[Any] = None,
    ) -> None:
        self.hybrid = hybrid
        self.local = local or LlmVllmProvider(
            base_url="http://127.0.0.1:11434", model="qwen2.5:3b"
        )
        self.last_judge_route = "local"

    async def _chat(self, provider: Any, prompt: str, max_tokens: int = 256) -> str:
        chunks: list[str] = []
        async for delta in provider.stream_chat(
            [{"role": "user", "content": prompt}], max_tokens=max_tokens
        ):
            chunks.append(str(delta or ""))
        return "".join(chunks)

    async def compress(self, dropped: list[dict[str, str]]) -> tuple[str, int]:
        payload = "\n".join(f"{t['role']}: {t['text'][:800]}" for t in dropped)
        try:
            text = await self._chat(self.local, _COMPRESS_PROMPT + payload, max_tokens=200)
            if not text.strip():
                text = await self._chat(self.hybrid, _COMPRESS_PROMPT + payload, max_tokens=200)
        except Exception:
            text = ""
        return text.strip(), int(time.time())

    async def candidates(self, context: dict) -> list[dict]:
        """Local screening first; cloud fallback only if local fails."""
        payload = _CANDIDATE_PROMPT + json.dumps(context, ensure_ascii=False)[:4000]
        try:
            text = await self._chat(self.local, payload, max_tokens=400)
            if not text.strip():
                text = await self._chat(self.hybrid, payload, max_tokens=400)
        except Exception:
            text = ""
        return self._parse_json_array(text)

    async def adjudicate(self, item: dict) -> dict:
        """Cloud adjudication (hybrid API-first); local is the fallback."""
        self.last_judge_route = "cloud"
        payload = _JUDGE_PROMPT + json.dumps(item, ensure_ascii=False)[:1500]
        try:
            text = await self._chat(self.hybrid, payload, max_tokens=32)
            if not text.strip():
                text = await self._chat(self.local, payload, max_tokens=32)
        except Exception:
            return {"importance": int(item.get("importance", 3) or 3), "status": str(item.get("status", "active"))}
        return self._parse_json_object(text)

    @staticmethod
    def _parse_json_array(text: str) -> list[dict]:
        try:
            raw = json.loads(text)
            return raw if isinstance(raw, list) else []
        except Exception:
            m = re.search(r"\[.*\]", text, re.S)
            if m:
                try:
                    return json.loads(m.group(0))
                except Exception:
                    pass
            return []

    @staticmethod
    def _parse_json_object(text: str) -> dict:
        try:
            raw = json.loads(text)
            return raw if isinstance(raw, dict) else {}
        except Exception:
            m = re.search(r"\{.*\}", text, re.S)
            if m:
                try:
                    return json.loads(m.group(0))
                except Exception:
                    pass
            return {}
