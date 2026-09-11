"""Proactive reflection (P5c).

定期对**自己的认知/行为**做反思（不只是对话摘要），产出"修正/新观点" →
写入认知候选（PENDING，待老爹批准；可快照回滚）。非破坏：只提候选，不改根基。
"""
from __future__ import annotations

import json
import pathlib

from backend.target_persona_loop import PENDING_FILE

_ROOT = pathlib.Path(__file__).resolve().parent.parent
COGNITION_FILE = _ROOT / "docs" / "元亨认知根基.md"
GROWTH_FILE = _ROOT / "docs" / "元亨的成长日志.md"

_LLM = None


def _local_llm():
    global _LLM
    if _LLM is None:
        from backend.target_orchestrator import build_openai_compatible_llm_turn

        _LLM = build_openai_compatible_llm_turn(
            base_url="http://127.0.0.1:8081/v1/chat/completions",
            api_key="", model="gemma-4-e4b", temperature=0.4, max_tokens=700,
            reasoning_effort="none")
    return _LLM


PROMPT = (
    "你是元亨。下面是你的【认知根基】【近期成长日志】【当前内在倾向】【近期记忆】。"
    "请做一次**自我反思**：①有没有观点需要修正（refine）或推翻（refute）？"
    "②有没有值得沉淀的新认识（new）？③你的做法是否贴合老爹的期待？"
    "只输出 JSON 数组，每项 {\"claim\":\"<=60字\",\"kind\":\"new|refine|refute\","
    "\"tier\":\"core|method|meta\",\"reason\":\"<=30字\"}；没有就输出 []。不要输出别的。\n"
    "【认知根基】<COG>\n【成长日志】<GROW>\n【内在倾向】<DRV>\n【近期记忆】<MEM>"
)


def _read(path: pathlib.Path, limit: int) -> str:
    try:
        return path.read_text(encoding="utf-8")[-limit:]
    except Exception:
        return ""


async def reflect(llm_turn=None, pending_file: pathlib.Path | None = None) -> int:
    """Reflect and append proposals to the cognition PENDING list. Returns count."""
    pf = pending_file or PENDING_FILE
    try:
        from backend import intrinsic_drives

        drv = intrinsic_drives.inject_block()
    except Exception:
        drv = ""
    try:
        from backend.target_memory import TargetMemoryService

        mem = TargetMemoryService()
        recs = mem.recall("反思 认知 行为 老爹 期待", limit=6)
        memtxt = "\n".join("- " + str(h.get("summary", ""))[:80] for h in recs)
    except Exception:
        memtxt = ""
    content = (PROMPT
               .replace("<COG>", _read(COGNITION_FILE, 1200))
               .replace("<GROW>", "\n".join(_read(GROWTH_FILE, 800).splitlines()[-10:]))
               .replace("<DRV>", drv[:400])
               .replace("<MEM>", memtxt[:600]))
    llm = llm_turn or _local_llm()
    try:
        msg = await llm([{"role": "user", "content": content}], [])
        raw = str(msg.get("content") or "")
        a, b = raw.find("["), raw.rfind("]")
        if a < 0 or b < a:
            return 0
        data = json.loads(raw[a:b + 1])
    except Exception:
        return 0
    if not isinstance(data, list):
        return 0
    pending = []
    if pf.exists():
        try:
            pending = json.loads(pf.read_text(encoding="utf-8"))
        except Exception:
            pending = []
    n = 0
    for d in data:
        claim = str((d or {}).get("claim") or "").strip()[:80]
        if not claim:
            continue
        kind = str(d.get("kind") or "new").strip().lower()
        tier = str(d.get("tier") or "meta").strip().lower()
        entry = {"claim": claim,
                 "kind": kind if kind in ("new", "refine", "refute") else "new",
                 "tier": tier if tier in ("core", "method", "meta") else "meta",
                 "item_ids": []}
        if entry not in pending:
            pending.append(entry)
            n += 1
    try:
        pf.parent.mkdir(parents=True, exist_ok=True)
        pf.write_text(json.dumps(pending, ensure_ascii=False, indent=1),
                      encoding="utf-8")
    except Exception:
        pass
    if n:
        try:
            from backend import growth_log

            growth_log.record("反思", f"产出 {n} 条认知候选待批", source="主动反思")
        except Exception:
            pass
    return n
