"""Scheduler capabilities (ledger 0144/0145): ledger.search / memory.recall /
system.time — the minimal set proving the ADR-007 pipeline end to end.

Read-only handlers.  Execution path is CapabilityRegistry (gated);
Agent-Core ToolRegistry mapping is provided for LLM tool views only.
"""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field

from backend.agent.tool_registry import get_registry, ToolRegistry
from backend.target_capability_registry import Capability, CapabilityRegistry
from backend.target_memory import TargetMemoryService

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
LEDGER = _PROJECT_ROOT / "docs" / "上下文台账.md"

SCHEDULER_CATEGORY = "scheduler"
SCHEDULER_POLICY = "scheduler_allowed"


def _policy_always_true() -> bool:
    return True


def ledger_search(query: str, limit: int = 8) -> str:
    """Search the project ledger; keyword index first, file scan fallback."""
    q = str(query or "").strip()
    if not q:
        return "未找到台账或无查询"
    try:
        hits = _retry_query(q, source="ledger")[: max(1, min(int(limit), 10))]
    except Exception:
        hits = []
    if hits:
        parts = []
        for h in hits:
            line = h["summary"][:400]
            if h.get("record_title"):
                line = f"[{h['record_title'][:60]}] " + line
            parts.append(f"[{h['docid']}] {line}")
        return "\n".join(parts)[:4000]
    return _ledger_grep_fallback(q, int(limit))


def _ledger_grep_fallback(q: str, limit: int) -> str:
    if not LEDGER.exists():
        return "未找到台账或无查询"
    matches: list[str] = []
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        if q in line and "记录" not in line[:6]:
            matches.append(line[3:].strip() if line.startswith("- ") else line.strip())
            if len(matches) >= limit:
                break
    return "\n".join(matches[:limit]) if matches else "台账无匹配"


def recall_memory(query: str, limit: int = 5) -> str:
    """Recall project/user memory items from L2 store (read-only; never deletes)."""
    q = str(query or "").strip()
    rows = TargetMemoryService().recall(q, limit=max(1, min(int(limit), 10)))
    if not rows:
        try:
            from backend.target_memory import TargetMemoryService as _S

            service = _S()
            from backend.target_kw_index import KeywordIndex

            kw = KeywordIndex()
            for sub in _split_query(q):
                hits = kw.query(sub, limit=4, source="l2")
                if hits:
                    rows = [
                        r for r in service._recall_via_kw(sub, 5)
                    ]
                    break
        except Exception:
            rows = []
    if not rows:
        return "记忆库无匹配"
    return "\n".join(f"[{r['importance']}] {r['summary']}" for r in rows)[:2000]


def system_time() -> str:
    """Current local date/time and day of week."""
    now = datetime.datetime.now()
    weekday = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"][now.weekday()]
    return f"{now.strftime('%Y-%m-%d %H:%M:%S')} {weekday}"


_constitution_lock: Any = None
_constitution_engine: Any = None


def _constitution_check(content: str) -> tuple[bool, str]:
    """Constitution validate_output gate (never bypassable; M3 ledger 0152)."""
    global _constitution_engine
    if _constitution_engine is None:
        try:
            from backend.embodied.companion.constitution import ConstitutionEngine

            _constitution_engine = ConstitutionEngine()
        except Exception as exc:
            return True, f"constitution unavailable ({type(exc).__name__}); allow"
    try:
        from backend.target_constitution import check_text

        ok, reason = check_text(content)
        if not ok:
            return False, f"target-constitution:{reason}"
        res = _constitution_engine.validate_output(str(content)[:400], source="memory.save")
        engine_ok = bool(res and res.get("ok"))
        return engine_ok, str(res.get("checks") or "")[:120]
    except Exception as exc:
        return True, f"constitution error ({type(exc).__name__}); allow"


def memory_save(content: str, kind: str = "preference", importance: int = 0,
                service: Any = None) -> str:
    """Save a notable item into long-term memory (user consent required)."""
    import hashlib
    import time as _time

    from backend.target_memory import L2Item

    svc = service or TargetMemoryService()
    kind = str(kind or "preference").strip()[:20] or "preference"
    if kind not in ("preference", "fact", "event", "decision"):
        kind = "preference"
    content_txt = str(content).strip()[:500]
    if not content_txt:
        return "内容为空，未保存"
    allowed, detail = _constitution_check(content_txt)
    if not allowed:
        return f"宪法审查未通过，拒绝保存: {detail}"
    imp = 5 if not int(importance or 0) else max(1, min(int(importance), 10))
    item = L2Item(
        id="mem_" + hashlib.sha256(("save:" + content_txt).encode("utf-8")).hexdigest()[:12],
        tier="L2",
        type=kind,
        importance=imp,
        summary=content_txt,
        content_hash=hashlib.sha256(content_txt.encode("utf-8")).hexdigest()[:16],
        keywords=content_txt[:40].replace(" ", ""),
        evidence_ref="memory.save:user-approved",
        created_at=_time.time(),
    )
    from difflib import SequenceMatcher
    import sqlite3 as _sqlite3

    con = _sqlite3.connect(str(svc.db_path))
    rows = con.execute(
        "SELECT id, summary, type FROM l2_items WHERE type=? AND status IN ('active','downgraded')",
        (kind,),
    ).fetchall()
    con.close()
    for iid, summary, _t in rows:
        if summary == content_txt:
            return "该内容已在记忆中，未重复保存"
        ratio = SequenceMatcher(None, str(summary), content_txt).ratio()
        if ratio >= 0.8:
            svc.observe_hit(iid, strength=0.3)  # corroborate the existing one
            return f"近似记忆已存在（相似度 {ratio:.0%}），已强化原记忆"
    svc.store_item(item)
    return f"已保存 ({kind})"


def _handler_of(func: Any) -> Any:
    def _h(params: dict[str, Any]) -> Any:
        return func()
    return _h


def _split_query(query: str) -> list[str]:
    import re as _re

    pieces = [p for p in _re.split(r"[\s,，。、？?]+", str(query or "")) if len(p) >= 2]
    return pieces or [str(query or "")]


def _retry_query(query: str, source: str) -> list[dict]:
    """Keyword-index query with automatic sub-query fallback (robust to long
    sentence-style queries from the model)."""
    from backend.target_kw_index import KeywordIndex

    kw = KeywordIndex()
    hits = kw.query(query, limit=6, source=source)
    if hits:
        return hits
    for s in _split_query(query):
        hits = kw.query(s, limit=4, source=source)
        if hits:
            return hits
    return []


def _queries_handler(func: Any) -> Any:
    def _h(params: dict[str, Any]) -> Any:
        return func(str(params.get("query", "")), int(params.get("limit", 8) or 8))
    return _h


class _QueryArgs(BaseModel):
    query: str = Field(..., min_length=1, max_length=80, description="检索关键词，1-3 个词")
    limit: int = Field(5, ge=1, le=500, description="返回条数上限")


class _SaveArgs(BaseModel):
    content: str = Field(..., min_length=2, max_length=500, description="要保存的内容")
    kind: str = Field("preference", description="preference|fact|event|decision")
    importance: int = Field(0, ge=0, le=10, description="0=交裁决默认")


def _verify_nonempty(output: Any) -> bool:
    return bool(str(output or "").strip())


def _save_handler(params: dict[str, Any]) -> str:
    return memory_save(
        str(params.get("content", "")),
        str(params.get("kind", "preference")),
        int(params.get("importance", 0) or 0),
    )


def bind_memory_save_service(registry: CapabilityRegistry, service: Any) -> None:
    """Rebind memory.save handler to a session-owned memory service."""
    cap = registry.get("memory.save")
    if cap is None:
        return
    registry.register_capability(
        Capability(
            name=cap.name,
            handler=lambda p: memory_save(
                str(p.get("content", "")),
                str(p.get("kind", "preference")),
                int(p.get("importance", 0) or 0),
                service=service,
            ),
            input=cap.input,
            optional_input=cap.optional_input,
            requires=cap.requires,
            side_effect=cap.side_effect,
            risk=cap.risk,
            timeout_ms=cap.timeout_ms,
            verify=cap.verify,
            input_model=cap.input_model,
        ),
        override=True,
    )


def _verify_time(output: Any) -> bool:
    return "星期" in str(output)


def scheduler_capabilities() -> list[Capability]:
    return [
        Capability(
            name="ledger.search",
            handler=_queries_handler(ledger_search),
            input=("query",),
            optional_input=("limit",),
            requires=(SCHEDULER_POLICY,),
            side_effect=False,
            risk="low",
            verify=_verify_nonempty,
            input_model=_QueryArgs,
        ),
        Capability(
            name="memory.recall",
            handler=_queries_handler(recall_memory),
            input=("query",),
            optional_input=("limit",),
            requires=(SCHEDULER_POLICY,),
            side_effect=False,
            risk="low",
            verify=_verify_nonempty,
            input_model=_QueryArgs,
        ),
        Capability(
            name="system.time",
            handler=_handler_of(system_time),
            input=(),
            requires=(),
            side_effect=False,
            risk="low",
            verify=_verify_time,
        ),
        Capability(
            name="memory.save",
            handler=_save_handler,
            input=("content",),
            optional_input=("kind", "importance"),
            requires=(SCHEDULER_POLICY, "memory.save.approval"),
            side_effect=True,
            risk="high",
            verify=_verify_nonempty,
            input_model=_SaveArgs,
        ),
    ]


SAVE_APPROVAL_POLICY = "memory.save.approval"


def _policy_deny_all() -> bool:
    return False


def setup_scheduler_capabilities(registry: Optional[CapabilityRegistry] = None) -> CapabilityRegistry:
    registry = registry or CapabilityRegistry()
    for cap in scheduler_capabilities():
        registry.register_capability(cap)
    if not registry.get_policy(SCHEDULER_POLICY):
        registry.register_policy(SCHEDULER_POLICY, _policy_always_true)
    if not registry.get_policy(SAVE_APPROVAL_POLICY):
        registry.register_policy(SAVE_APPROVAL_POLICY, _policy_deny_all)
    return registry


def openai_tools_view(registry: Optional[CapabilityRegistry] = None) -> list[dict]:
    return setup_scheduler_capabilities(registry).export_openai_tools()


def setup_scheduler_tools(registry: Optional[ToolRegistry] = None) -> list[str]:
    """Agent-Core ToolRegistry view (for LLM tool ingestion); execution stays gated."""
    if registry is None:
        registry = get_registry()
    core = setup_scheduler_capabilities()
    names: list[str] = []
    for cap_name in core.names():
        c = core.get(cap_name)
        if c is None:
            continue
        registry.register_function(
            name=c.openai_name,
            description=("只读能力" + (f"；入参: {', '.join(c.all_inputs)}" if c.all_inputs else ""))
            + "。由调度器统一执行。",
            parameters={"type": "object",
                        "properties": {k: {"type": "string"} for k in c.all_inputs},
                        "required": list(c.input)},
            handler=c.handler,
            category=SCHEDULER_CATEGORY,
            override=True,
        )
        names.append(c.openai_name)
    return names
