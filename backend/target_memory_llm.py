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

    async def _chat_msgs(self, provider: Any, messages: list[dict],
                         max_tokens: int = 256) -> str:
        chunks: list[str] = []
        async for delta in provider.stream_chat(
            messages, max_tokens=max_tokens
        ):
            chunks.append(str(delta or ""))
        return "".join(chunks)

    _L1_SUM_SYSTEM = (
        "你是记忆压缩助手。User 消息里是若干条早前对话（每行 role: 内容）。"
        "请把它压成一段不超过100字的中文摘要：保留核心实体、达成的结论、待办，"
        "末尾带一句情绪/关系走向。直接输出摘要正文——禁止任何前缀"
        "（如『摘要：』『以下是压缩结果』），禁止复述本要求。"
    )

    @staticmethod
    def _strip_prefix(text: str) -> str:
        import re

        t = str(text or "").strip()
        t = re.sub(r"^[\s>]*", "", t)
        for bad in ("摘要：", "摘要:", "总结：", "总结:", "以下是", "压缩结果",
                    "这段对话", "对话摘要", "本段"):
            if t.startswith(bad):
                t = t[len(bad):].strip()
        return t

    async def compress(self, dropped: list[dict[str, str]],
                       prev: str = "") -> tuple[str, int]:
        payload = "\n".join(f"{t['role']}: {t['text'][:800]}" for t in dropped)
        user = (f"上一段摘要（接续用，别重复）：{prev}\n\n" if prev else "") + payload
        msgs = [{"role": "system", "content": self._L1_SUM_SYSTEM},
                {"role": "user", "content": user}]
        try:
            text = self._strip_prefix(
                await self._chat_msgs(self.local, msgs, max_tokens=220))
            if not text.strip() and self.hybrid is not None:
                text = self._strip_prefix(
                    await self._chat_msgs(self.hybrid, msgs, max_tokens=220))
        except Exception:
            text = ""
        return (text.strip()[:300] if text.strip() else prev), int(time.time())

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
