"""Conflict resolution judge (P5b).

素材短板③：主流"冲突靠规则（时间戳覆盖）"。这里用 LLM **判断哪条更可信**
（更新/更具体/更有依据者优先），非破坏性：只用于"降权旧条 / 发起证伪提案"。

judge(new, old) -> "new" | "old" | "uncertain"
"""
from __future__ import annotations

import json

_LLM = None


def _local_llm():
    global _LLM
    if _LLM is None:
        from backend.target_orchestrator import build_openai_compatible_llm_turn

        _LLM = build_openai_compatible_llm_turn(
            base_url="http://127.0.0.1:8081/v1/chat/completions",
            api_key="", model="gemma-4-e4b", temperature=0.1, max_tokens=200,
            reasoning_effort="none")
    return _LLM


PROMPT = (
    "元亨的记忆里有一条旧说法与一条新说法可能冲突。请判断**哪条更可信**——"
    "通常：更新（时间更近）、更具体、更有依据、或明确纠正旧说法者更可信；"
    "若无法判断则 uncertain。只输出 JSON："
    '{"more_credible":"new|old|uncertain","reason":"<=30字"}。\n'
    "旧说法：<OLD>\n新说法：<NEW>"
)


async def judge(new_text: str, old_text: str, llm_turn=None) -> str:
    llm = llm_turn or _local_llm()
    content = (PROMPT.replace("<OLD>", str(old_text)[:200])
               .replace("<NEW>", str(new_text)[:200]))
    try:
        msg = await llm([{"role": "user", "content": content}], [])
        raw = str(msg.get("content") or "")
        a, b = raw.find("{"), raw.rfind("}")
        if a < 0 or b < a:
            return "uncertain"
        data = json.loads(raw[a:b + 1])
        v = str(data.get("more_credible", "")).strip().lower()
        return v if v in ("new", "old", "uncertain") else "uncertain"
    except Exception:
        return "uncertain"
