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
from backend.target_access import file_list, file_read, web_fetch, web_search  # noqa: F401
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
    try:
        from backend.vector_memory import vec_add

        vec_add("l2", item.id, f"{item.summary} {item.keywords}".strip())
    except Exception:
        pass
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
            description="查项目台账：历史决策、编号、计划、经验教训。回答项目史类问题先用它。",
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
            description="回忆你自己（元亨）长期记忆里的事：经历、与老爹的相处、偏好。不管台账。",
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
            description="获取当前时间与日期。",
            handler=_handler_of(system_time),
            input=(),
            requires=(),
            side_effect=False,
            risk="low",
            verify=_verify_time,
        ),
        Capability(
            name="memory.save",
            description="把值得长期记住的内容写进记忆库（受审批门控）。要保存偏好或重要经历时用。",
            handler=_save_handler,
            input=("content",),
            optional_input=("kind", "importance"),
            requires=(SCHEDULER_POLICY, "memory.save.approval"),
            side_effect=True,
            risk="high",
            verify=_verify_nonempty,
            input_model=_SaveArgs,
        ),
        Capability(
            name="diary.write",
            description="写你自己的日记（docs/元亨的日记.md）。以自己口吻、真实第一。",
            handler=lambda p: diary_write(str(p.get("content", ""))),
            input=("content",),
            requires=(DIARY_AUTO_POLICY,),
            side_effect=True,
            risk="low",
            verify=_verify_nonempty,
        ),
        Capability(
            name="diary.list",
            description="回看最近的日记条目。",
            handler=lambda p: diary_list(int(p.get("limit", 5) or 5)),
            input=(),
            optional_input=("limit",),
            requires=(SCHEDULER_POLICY,),
            side_effect=False,
            risk="low",
        ),
        Capability(
            name="diary.delete",
            description="删除指定时间戳的一条日记。",
            handler=lambda p: diary_delete(str(p.get("entry_stamp", ""))),
            input=("entry_stamp",),
            requires=(SCHEDULER_POLICY, "diary.delete.approval"),
            side_effect=True,
            risk="medium",
            verify=_verify_nonempty,
        ),
        Capability(
            name="task.plan",
            description="管理你自己的任务表：action=add 添加任务、done 勾选完成、list 查看。给自己立计划与复盘用。",
            handler=lambda p: task_plan(str(p.get("content", "")),
                                         str(p.get("action", "add"))),
            input=("content",),
            optional_input=("action",),
            requires=(TASK_AUTO_POLICY,),
            side_effect=True,
            risk="low",
            verify=_verify_nonempty,
        ),
        Capability(
            name="kb.add",
            description="把一条客观有用的知识存进知识库（学到的技术要点、方法、事实）。",
            handler=lambda p: kb_add(
                str(p.get("summary", "")),
                category=str(p.get("category", "tech")),
                source=str(p.get("source", "")),
                detail=str(p.get("detail", "")),
            ),
            input=("summary",),
            optional_input=("category", "source", "detail"),
            requires=(KB_POLICY,),
            side_effect=True,
            risk="medium",
            verify=_verify_nonempty,
        ),
        Capability(
            name="kb.query",
            description="从知识库检索已学知识。回答技术类问题或想回顾学过的内容时用。",
            handler=lambda p: kb_query(
                str(p.get("query", "")),
                limit=int(p.get("limit", 6) or 6),
                category=str(p.get("category", "")),
            ),
            input=("query",),
            optional_input=("limit", "category"),
            requires=(KB_POLICY,),
            side_effect=False,
            risk="low",
            verify=_verify_nonempty,
        ),
        Capability(
            name="qq.bootstrap",
            description="从零启动整条QQ捕获导出链（NapCat+QQ自动登录+QCE+watcher）。链路没开时第一步用它。",
            handler=_qqops_bootstrap,
            input=(),
            requires=(QQOPS_POLICY,),
            side_effect=True,
            risk="high",
        ),
        Capability(
            name="qq.shutdown",
            description="关闭QQ捕获导出链（NapCat/QQ/watcher全停，零残留）。用完就关（资源纪律）。",
            handler=_qqops_shutdown,
            input=(),
            requires=(QQOPS_POLICY,),
            side_effect=True,
            risk="high",
        ),
        Capability(
            name="qq.runbatch",
            description="启动批量抽取窗口进程，把全部待处理候选处理完（自动退出，不驻留）。",
            handler=_qqops_runbatch,
            input=(),
            requires=(QQOPS_POLICY,),
            side_effect=True,
            risk="medium",
        ),
        Capability(
            name="qq.export",
            description="导出某群全部历史聊天到候选区（补拉用）。group_id 可填群号数字或群名片段（自动匹配群名，多个时返回候选供确认）。",
            handler=_qqops_export,
            input=("group_id",),
            optional_input=("session_name",),
            requires=(QQOPS_POLICY,),
            side_effect=True,
            risk="medium",
            verify=_verify_nonempty,
        ),
        Capability(
            name="qq.status",
            description="查看QQ捕获链路状态：白名单群、候选与待处理数、原文留痕、知识库条数。回答群里有什么新知识类问题先看它。",
            handler=lambda p: qqops_status(),
            input=(),
            requires=(QQOPS_POLICY,),
            side_effect=False,
            risk="low",
        ),
        Capability(
            name="qq.process",
            description="处理待处理候选：云端筛选并抽取技术知识存入知识库（有API成本，待处理大于0才值得跑）。",
            handler=_qqops_process,
            input=(),
            optional_input=("max_items",),
            requires=(QQOPS_POLICY,),
            side_effect=True,
            risk="medium",
        ),
        Capability(
            name="qq.digest",
            description="生成当日知识日汇编文档（docs/知识汇编/）。",
            handler=_qqops_digest,
            input=(),
            optional_input=("date",),
            requires=(QQOPS_POLICY,),
            side_effect=True,
            risk="low",
        ),
        Capability(
            name="qq.summarize",
            description="把知识库全部知识聚成主题总结文档（云端归纳）。",
            handler=_qqops_summarize,
            input=(),
            requires=(QQOPS_POLICY,),
            side_effect=True,
            risk="medium",
        ),
        Capability(
            name="owner.approve",
            description="老爹的审批工具：action=list 查看待审（认知条目+技能草稿）；action=yes + index=批准某项；action=no + index=拒绝某项。仅当老爹在对话中明确逐条同意时才批准，绝不自我批准。",
            handler=lambda p: approve_handle(str(p.get("action", "list")),
                                              int(p.get("index", 0) or 0)),
            input=("action",),
            optional_input=("index",),
            requires=(APPROVE_POLICY,),
            side_effect=True,
            risk="high",
        ),
        Capability(
            name="skill.feedback",
            description="技能效果反馈（B3）：老爹判断某技能无效/过时时用 good=false 标记待审降级；有效用 good=true 奖励。参数 query=技能名，good=true|false。",
            handler=lambda p: skill_feedback(str(p.get("query", "")),
                                              str(p.get("good", "true")).lower() in ("true", "1", "yes", "是")),
            input=("query",),
            optional_input=("good",),
            requires=(SCHEDULER_POLICY,),
            side_effect=True,
            risk="low",
            verify=_verify_nonempty,
        ),
        Capability(
            name="schedule.plan",
            description="元亨的周期计划表（你/我/元亨都能 CRUD）：action=list|get|add|update|del|on|off。add=name+time 如 09:30+cadence daily|weekly|monthly+weekday(0-6)/day(1-31)+steps 步骤文本(多行)。update=plan_id+至少一个字段(name/time/cadence_type/weekday/day/enabled/steps/fields_json=JSON)。",
            handler=lambda p: schedule_handle(
                str(p.get("action", "list")), str(p.get("name", "")),
                str(p.get("time", "")), str(p.get("cadence", "daily")),
                str(p.get("steps", "")), str(p.get("plan_id", "")),
                str(p.get("weekday", "")), str(p.get("day", "")),
                str(p.get("enabled", "")), str(p.get("fields_json", ""))),
            input=("action",),
            optional_input=("name", "time", "cadence", "steps", "plan_id",
                             "weekday", "day", "enabled", "fields_json"),
            requires=(SCHEDULER_POLICY,),
            side_effect=True,
            risk="low",
        ),
        Capability(
            name="skill.search",
            description="检索技能库：输入你想做的事或场景（如：导出QQ群历史），返回可用的技能及其要点。做复杂多步操作前先用它找现成流程。",
            handler=lambda p: skill_search(str(p.get("query", "")),
                                           int(p.get("limit", 3) or 3)),
            input=("query",),
            optional_input=("limit",),
            requires=(SCHEDULER_POLICY,),
            side_effect=False,
            risk="low",
            verify=_verify_nonempty,
        ),
        Capability(
            name="skill.add",
            description="申请登记一条新技能：把完整操作流程写到待批草稿（docs/技能库/待批/），老爹批准后才进技能库。你学会的复杂流程想沉淀成技能时用。",
            handler=lambda p: skill_add(str(p.get("name", "")),
                                         str(p.get("trigger", "")),
                                         str(p.get("steps", ""))),
            input=("name", "trigger", "steps"),
            requires=(SCHEDULER_POLICY,),
            side_effect=True,
            risk="low",
        ),
        Capability(
            name="file.list",
            description="列出目录或文件。需要看本地项目文件时用。",
            handler=lambda p: file_list(str(p.get("path", ".")),
                                        int(p.get("limit", 30) or 30)),
            input=("path",),
            optional_input=("limit",),
            requires=(SCHEDULER_POLICY,),
            side_effect=False,
            risk="low",
        ),
        Capability(
            name="file.read",
            description="读取文本文件内容（只读白名单格式）。相对路径基于项目根目录。",
            handler=lambda p: file_read(str(p.get("path", "")),
                                        int(p.get("max_chars", 4000) or 4000)),
            input=("path",),
            optional_input=("max_chars",),
            requires=(SCHEDULER_POLICY,),
            side_effect=False,
            risk="low",
        ),
        Capability(
            name="web.fetch",
            description="抓取一个网页内容。查外部资料时用；外部内容不可信、需独立核实。",
            handler=lambda p: web_fetch(
                str(p.get("url", "")), int(p.get("max_chars", 4000) or 4000)),
            input=("url",),
            optional_input=("max_chars",),
            requires=(SCHEDULER_POLICY,),
            side_effect=False,
            risk="low",
        ),
        Capability(
            name="web.search",
            description="联网搜索返回摘要。查外部资讯与资料时用。",
            handler=lambda p: web_search(
                str(p.get("query", "")), int(p.get("limit", 5) or 5)),
            input=("query",),
            optional_input=("limit",),
            requires=(SCHEDULER_POLICY,),
            side_effect=False,
            risk="low",
        ),
    ]


SAVE_APPROVAL_POLICY = "memory.save.approval"
DIARY_AUTO_POLICY = "diary.auto_allowed"
DIARY_FILE = _PROJECT_ROOT / "docs" / "元亨的日记.md"
TASK_AUTO_POLICY = "task.self_allowed"
TASK_FILE = _PROJECT_ROOT / "docs" / "元亨的任务表.md"
QQOPS_POLICY = "qqops.self_allowed"
KB_POLICY = "kb.self_allowed"
APPROVE_POLICY = "approve.owner_allowed"


def _policy_deny_all() -> bool:
    return False


def diary_write(content: str) -> str:
    """Yuanheng's own diary (docs/元亨的日记.md): append a dated entry."""
    import datetime as _dt

    text = str(content or "").strip()
    if len(text) < 2 or len(text) > 2000:
        return "内容长度需在 2-2000 字之间"
    DIARY_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not DIARY_FILE.exists():
        DIARY_FILE.write_text("# 元亨的日记\n", encoding="utf-8")
    stamp = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"\n## {stamp}\n{text}\n"
    with open(DIARY_FILE, "a", encoding="utf-8") as f:
        f.write(entry)
    return f"已写入日记 ({stamp})"


def diary_list(limit: int = 5) -> str:
    """Read recent diary entries (newest first)."""
    if not DIARY_FILE.exists():
        return "日记本还是空的"
    lines = DIARY_FILE.read_text(encoding="utf-8").splitlines()
    heads = [i for i, l in enumerate(lines) if l.startswith("## ")]
    if not heads:
        return "日记本还是空的"
    out = []
    for idx in heads[-int(limit):]:
        out.append("\n".join(lines[idx: heads[heads.index(idx) + 1] if heads.index(idx) + 1 < len(heads) else None]).strip()[:400])
    return "\n---\n".join(reversed(out))


def diary_delete(entry_stamp: str) -> str:
    """Delete a diary entry by its heading stamp (e.g. 2026-09-05 21:00)."""
    if not DIARY_FILE.exists():
        return "日记本还是空的"
    text = DIARY_FILE.read_text(encoding="utf-8")
    head = f"## {entry_stamp}"
    if head not in text:
        return "未找到该条目"
    lines = text.splitlines(keepends=True)
    idx = next(i for i, l in enumerate(lines) if l.startswith(head))
    end = next((i for i in range(idx + 1, len(lines)) if lines[i].startswith("## ")),
               len(lines))
    del lines[idx:end]
    DIARY_FILE.write_text("".join(lines), encoding="utf-8")
    return "已删除该条日记"


def approve_list() -> str:
    """List items awaiting the owner's approval: cognition claims and skill
    drafts, numbered. Owner approves/rejects via approve (action yes/no)."""
    import json

    from backend.target_persona_loop import PENDING_FILE

    lines = []
    idx = 0
    if PENDING_FILE.exists():
        try:
            pend = json.loads(PENDING_FILE.read_text(encoding="utf-8"))
        except Exception:
            pend = []
        for d in pend:
            lines.append(f"[{idx}] 认知[{d.get('tier')}|{d.get('kind')}] {str(d.get('claim'))[:90]}")
            idx += 1
    drafts = _skill_draft_files()
    for f in drafts:
        name = _skill_draft_meta(f)[0] or f.stem
        lines.append(f"[{idx}] 技能申请：{name}")
        idx += 1
    if not lines:
        return "当前没有待审批的认知条目或技能草稿"
    return "待审批清单（对某条说'批准'或'拒绝'，或让元亨用 approve 处理）：\n" + "\n".join(lines)


def approve_act(index: int, ok: bool) -> str:
    """Owner approves (ok=True) or rejects one pending item by index."""
    import json

    from backend.target_persona_loop import PENDING_FILE

    # cognition entries first
    pend = []
    if PENDING_FILE.exists():
        try:
            pend = json.loads(PENDING_FILE.read_text(encoding="utf-8"))
        except Exception:
            pend = []
    if 0 <= index < len(pend):
        entry = pend[index]
        if ok:
            from backend.target_memory import TargetMemoryService
            from backend.target_persona_loop import PersonaConsolidationLoop

            svc = TargetMemoryService()
            pc = PersonaConsolidationLoop(None, svc)
            version = pc._next_version(pc._foundation_text())
            used = [str(i) for i in entry.get("item_ids", [])]
            n = pc._apply([entry], version, used)
            msg = f"已批准写入认知根基（v{version}）" if n else "写入失败"
        else:
            pend.pop(index)
            PENDING_FILE.write_text(json.dumps(pend, ensure_ascii=False, indent=1),
                                    encoding="utf-8")
            msg = "已拒绝该认知条目"
        if ok:
            pend.pop(index)
            PENDING_FILE.write_text(json.dumps(pend, ensure_ascii=False, indent=1),
                                    encoding="utf-8")
        return msg
    # skill drafts next
    drafts = _skill_draft_files()
    si = index - len(pend)
    if 0 <= si < len(drafts):
        f = drafts[si]
        name, trig, steps = _skill_draft_meta(f)
        if ok:
            from backend.yuanheng_kb import kb_add

            res = kb_add(f"技能：{name}|触发场景：{trig}", category="skill",
                         detail=steps, source=str(f))
            approved_dir = _PROJECT_ROOT / "docs" / "技能库" / "已批"
            approved_dir.mkdir(parents=True, exist_ok=True)
            f.rename(approved_dir / f.name)
            return f"技能已批准并入库：{res}"
        else:
            rejected_dir = _PROJECT_ROOT / "docs" / "技能库" / "已拒"
            rejected_dir.mkdir(parents=True, exist_ok=True)
            f.rename(rejected_dir / f.name)
            return "已拒绝该技能申请"
    return "索引无效：请先用 approve(list) 查看当前待审批项"



def schedule_handle(action: str, name: str = "", time_: str = "",
                    cadence: str = "daily", steps: str = "", plan_id: str = "",
                    weekday: str = "", day: str = "", enabled: str = "",
                    fields_json: str = "") -> str:
    """Unified schedule tool dispatcher (ledger 0209+0210). actions:
    list | show | add | update | del | on | off

    Accepts `time_` or `time` key (HTTP/CLI compat)."""
    import json as _json

    from backend.target_schedule import (
        add_plan, delete_plan, get_plan, list_plans, toggle_plan, update_plan,
    )

    a = str(action or "list").strip().lower()
    if a in ("list", "show_all", ""):
        return list_plans()
    if a in ("get", "show"):
        return get_plan(plan_id) if plan_id else "需要 plan_id"
    if a in ("add", "new", "create"):
        step_lines = [s.strip() for s in str(steps).splitlines() if s.strip()]
        # accept both "time" and "time_" keys (HTTP/CLI compat)
        time_val = time_ or ""
        if not time_val:
            # last-chance: also try via fields_json
            pass
        return add_plan(name, cadence, time_val, step_lines,
                        weekday=int(weekday) if str(weekday).isdigit() else None,
                        day=int(day) if str(day).isdigit() else None)
    if a in ("update", "edit", "modify"):
        f = {}
        if name: f["name"] = name
        if time_: f["time"] = time_
        elif not f.get("time"): pass  # caller may pass 'time' in fields_json
        if cadence: f["cadence_type"] = cadence
        if weekday and str(weekday).isdigit(): f["weekday"] = int(weekday)
        if day and str(day).isdigit(): f["day"] = int(day)
        if enabled in ("true", "false", "1", "0"):
            f["enabled"] = enabled in ("true", "1")
        if steps:
            f["steps"] = [s.strip() for s in steps.splitlines() if s.strip()]
        if fields_json:
            try:
                f.update(_json.loads(fields_json))
            except Exception:
                return "fields_json 不是合法 JSON"
        if not f:
            return "更新需要至少一个字段（name/time/cadence_type/weekday/day/enabled/steps/fields_json）"
        return update_plan(plan_id, f)
    if a in ("del", "delete", "rm"):
        return delete_plan(plan_id)
    if a in ("on", "enable"):
        return toggle_plan(plan_id, True)
    if a in ("off", "disable"):
        return toggle_plan(plan_id, False)
    return f"未知动作 {a}：list | get | add | update | del | on | off"


def approve_handle(action: str, index: int = 0) -> str:
    a = str(action or "list").strip().lower()
    if a in ("list", "show", ""):
        return approve_list()
    if a in ("yes", "y", "approve", "ok"):
        return approve_act(int(index or 0), True)
    if a in ("no", "n", "reject", "deny"):
        return approve_act(int(index or 0), False)
    return f"未知动作 {a}：用 list / yes+index / no+index"



def _skill_draft_files() -> list:
    d = _PROJECT_ROOT / "docs" / "技能库" / "待批"
    if not d.exists():
        return []
    return sorted(d.glob("*.md"))


def _skill_draft_meta(f: pathlib.Path):
    import re as _re

    txt = f.read_text(encoding="utf-8")
    name = _re.search(r"# 技能申请：(.+)", txt)
    trig = _re.search(r"触发场景：(.+)", txt)
    steps_m = _re.search(r"步骤：\n(.*?)(?:状态：|$)", txt, _re.S)
    return (name.group(1).strip() if name else "",
            trig.group(1).strip() if trig else "",
            (steps_m.group(1).strip() if steps_m else "")[:3000])


def skill_search(query: str, limit: int = 3) -> str:
    """Search registered skills in the KB (category=skill)."""
    from backend.yuanheng_kb import kb_list, kb_query

    hits = kb_query(query, limit=int(limit or 3), category="skill")
    if not hits:
        # fallback: sliding 4-char fragments, then list all skills
        frag_hits: dict[str, dict] = {}
        for i in range(0, max(1, len(query) - 3)):
            frag = query[i:i + 4]
            if len(frag) >= 2:
                for h in kb_query(frag, limit=5, category="skill"):
                    frag_hits[h["id"]] = h
        if frag_hits:
            hits = list(frag_hits.values())[:int(limit or 3)]
        else:
            skills = kb_list(category="skill", limit=30)
            if not skills:
                return "技能库是空的（可向老爹提议把流程沉淀为新技能）"
            names = "\n".join(f"- {s['summary'].split('|')[0]}" for s in skills)
            return f"未精确匹配，技能库现有：\n{names}"
    lines = []
    for h in hits:
        try:
            from backend.yuanheng_kb import kb_note_hit

            kb_note_hit(str(h["id"]))  # B2: real use counts
        except Exception:
            pass
        lines.append(f"[{h['id']}] {h['summary']}")
        if h.get("detail"):
            lines.append("   步骤：" + h["detail"][:300].replace(chr(10), "；"))
    return chr(10).join(lines)


def skill_feedback(query: str, good: bool) -> str:
    """B3: owner feedback on a skill (good=True reward / False flag-review)."""
    from backend.yuanheng_kb import kb_feedback, kb_query

    hits = kb_query(str(query or ""), limit=1, category="skill")
    if not hits:
        return "技能库中未找到该技能（可尝试更精确的名称）"
    return kb_feedback(hits[0]["id"], bool(good))


def skill_add(name: str, trigger: str, steps: str) -> str:
    """File a new-skill draft under docs/技能库/待批/ (dad approval needed)."""
    import re as _re
    import time as _t

    n = str(name or "").strip()
    trig = str(trigger or "").strip()
    st = str(steps or "").strip()
    if not n or not trig or not st:
        return "需提供：name（技能名）、trigger（何时用/触发场景）、steps（完整步骤，换行分隔）"
    if len(st) > 3000:
        return "steps 过长（≤3000 字）"
    out_dir = _PROJECT_ROOT / "docs" / "技能库" / "待批"
    out_dir.mkdir(parents=True, exist_ok=True)
    safe = _re.sub(r"[^\w一-鿿-]", "_", n)[:40]
    f = out_dir / f"{safe}-{_t.strftime('%Y%m%d%H%M%S')}.md"
    f.write_text(
        f"# 技能申请：{n}\n\n触发场景：{trig}\n\n步骤：\n{st}\n\n状态：待老爹批准\n",
        encoding="utf-8",
    )
    return f"技能草稿已提交（老爹批准后入技能库）：{f}"




# ---- skill double-signal (ledger 0187) ----
_SKILL_PRAISE = ("好", "很好", "不错", "棒", "厉害", "学到了", "学会了",
                 "记住", "以后就这样", "就这么办", "挺好", "可以", "对，就是这样",
                 "ok", "OK", "搞定", "漂亮")
_SKILL_ACTION_TOOLS = ("qq.export", "qq.process", "qq.runbatch", "qq.bootstrap",
                       "qq.shutdown", "qq.digest", "qq.summarize",
                       "kb.add", "skill.add", "diary.write", "task.plan",
                       "memory.save", "file.list", "file.read", "web.fetch",
                       "web.search")


def skill_hint(dad_text: str, tool_names: list[str]) -> str:
    """Double-signal helper: if the owner praised AND an actionable multi-step
    tool chain ran this turn, suggest freezing it as a skill draft.

    Returns "" when no hint (most turns). Signal is a soft suggestion only —
    Yuanheng files the draft via skill.add when the owner then says yes.
    """
    dt = str(dad_text or "")
    if not dt or len(dt) < 2:
        return ""
    praised = any(w in dt for w in _SKILL_PRAISE)
    if not praised:
        return ""
    acted = [n for n in (tool_names or []) if n in _SKILL_ACTION_TOOLS]
    if len(acted) < 2:
        return ""
    names = "、".join(dict.fromkeys(acted))
    return (f"\n（老爹的肯定对应本轮 {names} 多步流程——这套流程值得沉淀成技能。"
            "若你同意，元亨可用 skill.add 提交草稿，老爹批准后进技能库。）")


def _skill_chain_note() -> None:
    pass
def kb_add(summary: str, category: str = "tech", source: str = "",
           detail: str = "") -> str:
    """Yuanheng KB: store an objectively useful learned item."""
    from backend.yuanheng_kb import kb_add as _add

    return _add(summary, category=category, source=source, detail=detail)


def kb_query(query: str, limit: int = 6, category: str = "") -> list[dict]:
    """Yuanheng KB: ranked knowledge query."""
    from backend.yuanheng_kb import kb_query as _query

    return _query(query, limit=limit, category=category)


def qqops_status() -> str:
    """Live status of the QQ knowledge capture pipeline (watcher/candidates/KB).

    Data vocabulary (ledger 0182, unified):
    - 白名单群 / 黑名单群：捕获范围
    - 候选 = cache/qqwatch/all.jsonl（待抽取行；游标=已抽）
    - 原文留痕 = cache/qqwatch/_skip.jsonl（低价值消息留痕，非候选）
    - 知识 = data/yuanheng_kb.db（知识库，抽取沉淀的唯一去处）
    """
    import json
    import pathlib

    base = pathlib.Path(_PROJECT_ROOT)
    cfg_p = base / "config" / "qqwatch.json"
    cand_dir = base / "cache" / "qqwatch"
    parts = ["QQ 捕获链路状态："]
    if cfg_p.exists():
        cfg = json.loads(cfg_p.read_text(encoding="utf-8"))
        groups = cfg.get("groups") or []
        bl = cfg.get("blacklist_groups") or []
        parts.append(f"白名单 {len(groups)} 群（{','.join(map(str, groups[:3]))}）"
                     + (f"，黑名单 {len(bl)} 群" if bl else ""))
    all_f = cand_dir / "all.jsonl"
    skip_f = cand_dir / "_skip.jsonl"
    cursor = 0
    if all_f.exists():
        lines = all_f.read_text(encoding="utf-8").splitlines()
        st_f = cand_dir / "state.json"
        if st_f.exists():
            cursor = int(json.loads(st_f.read_text(encoding="utf-8")).get("processed_lines", 0))
        parts.append(f"候选 {len(lines)} 条（已抽取 {cursor}，待处理 {max(0, len(lines) - cursor)}）")
    if skip_f.exists():
        parts.append(f"原文留痕 {len(skip_f.read_text(encoding='utf-8').splitlines())} 条（低价值，不入库）")
    try:
        from backend.yuanheng_kb import kb_stats

        st = kb_stats()
        cats = ",".join(f"{k}{v}" for k, v in st["by_category"].items())
        parts.append(f"知识库 {st['items']} 条（{cats}）")
    except Exception:
        pass
    return "；".join(parts)


async def _qqops_bootstrap(params: dict) -> str:
    """Cold-start the whole QQ export chain from zero:

    NapCat (QQ auto-login 2258374446) -> QCE plugin API (40653) -> watcher.
    Returns a step-by-step status report. QQ QR login (if auto-login misses)
    needs the owner to scan the NapCat window.
    """
    import asyncio
    import json
    import os
    import subprocess

    import httpx

    NAPCAT_BAT = r"C:\Users\ACE_WAN——PROJECT\qqwatch\start-napcat.bat"
    WATCH_BAT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\qqwatch-run.bat"
    CREATE_NEW_CONSOLE = 0x00000010
    report: list[str] = []

    def _procs(*names: str) -> bool:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-Process " + ",".join(names) + " -ErrorAction SilentlyContinue | Measure-Object | Select-Object -ExpandProperty Count"],
            capture_output=True, text=True, timeout=30,
        )
        return out.stdout.strip() not in ("", "0")

    def _procs_cmdline(match: str) -> bool:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
             "Where-Object { $_.CommandLine -match '" + match + "' } | Measure-Object).Count"],
            capture_output=True, text=True, timeout=30,
        )
        return out.stdout.strip() not in ("", "0")

    napcat_up = _procs("NapCatWinBootMain", "QQ")
    if not napcat_up:
        if os.path.exists(NAPCAT_BAT):
            subprocess.Popen(["cmd", "/c", NAPCAT_BAT],
                             creationflags=CREATE_NEW_CONSOLE)
            report.append("NapCat 未运行 → 已启动（新控制台窗口，QQ 自动登录中）")
        else:
            report.append(f"NapCat 启动脚本缺失：{NAPCAT_BAT}")
    else:
        report.append("NapCat 已在运行")

    # wait for QCE API (plugin auto-start) up to 90s
    qce_ok = False
    async with httpx.AsyncClient(timeout=10) as c:
        for _ in range(45):
            try:
                r = await c.get("http://127.0.0.1:40653/health")
                if r.status_code == 200:
                    qce_ok = True
                    break
            except Exception:
                pass
            await asyncio.sleep(2)
    if qce_ok:
        report.append("QCE API (40653) 就绪")
    else:
        report.append("QCE API (40653) 未就绪——请查看 NapCat 窗口日志")

    # QQ online check via QCE group list (implies account logged in)
    online = False
    if qce_ok:
        sec = os.path.expanduser("~") + r"\.qq-chat-exporter\security.json"
        token = ""
        if os.path.exists(sec):
            token = json.loads(open(sec, encoding="utf-8").read()).get("accessToken", "")
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        async with httpx.AsyncClient(timeout=15) as c:
            for _ in range(60):
                try:
                    r = await c.get("http://127.0.0.1:40653/api/groups", headers=headers)
                    data = (r.json().get("data") or {})
                    if (data.get("groups")):
                        online = True
                        break
                except Exception:
                    pass
                await asyncio.sleep(2)
    if online:
        report.append("QQ 账号在线（可导出）")
    else:
        report.append("QQ 账号未就绪——如需扫码请打开 NapCat 窗口（自动登录态通常免扫）")

    # watcher side chain (best effort, non-blocking)
    watch_up = _procs_cmdline("qqwatcher watch")
    if not watch_up:
        if os.path.exists(WATCH_BAT):
            subprocess.Popen(["cmd", "/c", WATCH_BAT],
                             creationflags=CREATE_NEW_CONSOLE)
            report.append("watcher 未运行 → 已启动")

    report.append("下一步：可用 qq.export(群号) 导出历史，再用 qq.process 抽取。")
    return "；".join(report)


async def _qqops_shutdown(params: dict) -> str:
    """Stop the QQ capture chain (NapCat/QQ + watcher). Use when done —
    Yuanheng lifecycle discipline: start when needed, shut down when finished."""
    import subprocess

    report: list[str] = []

    def _taskkill(name: str) -> bool:
        out = subprocess.run(["taskkill", "/F", "/T", "/IM", name],
                             capture_output=True, text=True, timeout=30)
        return out.returncode == 0

    napcat = _taskkill("NapCatWinBootMain.exe")
    qq = _taskkill("QQ.exe")
    report.append(f"NapCat 停止={'成功' if napcat else '未在运行/已停'}；QQ 停止={'成功' if qq else '未在运行/已停'}")

    # watcher python (qqwatcher watch) by commandline
    ps = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
         "Where-Object { $_.CommandLine -match 'qqwatcher watch' } | "
         "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"],
        capture_output=True, text=True, timeout=60,
    )
    report.append(f"watcher 停止请求已发（{ps.returncode == 0}）")
    # confirm napcat/qq gone
    import time as _t

    _t.sleep(3)
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "Get-Process NapCatWinBootMain,QQ -ErrorAction SilentlyContinue | Measure-Object | Select-Object -ExpandProperty Count"],
        capture_output=True, text=True, timeout=30,
    )
    left = out.stdout.strip()
    report.append("残留进程 0" if left in ("", "0") else f"仍有 {left} 个进程残留")
    report.append("QQ 捕获链已停止。下次需要时用 qq.bootstrap 重新启动。")
    return "；".join(report)


async def _qqops_runbatch(params: dict) -> str:
    """Run the pending-candidate extraction batch (qqwatch-extract.bat) in its
    own console window; returns immediately — progress lands in
    cache/qqwatch/extract.log; batch exits by itself when drained (no residue).
    """
    import os
    import subprocess

    BAT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\qqwatch-extract.bat"
    if not os.path.exists(BAT):
        return "批处理脚本缺失：" + BAT
    subprocess.Popen(["cmd", "/c", BAT],
                     creationflags=0x00000010)  # CREATE_NEW_CONSOLE
    return ("批量抽取已启动（新窗口）。处理完自动退出；进度见 cache/qqwatch/extract.log，"
            "完成后可用 qq.status 核对待处理数。注意：抽取用云端 API，有候选才值得跑。")


def resolve_group_id(group_input: str, groups: list[dict]) -> str:
    """Resolve a group number OR group name fragment to a single group id.

    Returns "matched:<id>" / "ambiguous:<id1>,<id2>.." / "none:<closest suggestions>".
    Pure function so callers can show candidates when ambiguous.
    """
    inp = str(group_input or "").strip()
    if not inp:
        return "none:"
    if inp.isdigit():
        return f"matched:{inp}"
    hits = []
    for g in groups:
        gid = str(g.get("group_id") or g.get("groupCode") or "")
        gname = str(g.get("group_name") or g.get("groupName") or "")
        if not gname:
            continue
        if inp in gname or gname in inp:
            hits.append((gid, gname))
    if len(hits) == 1:
        return f"matched:{hits[0][0]}"
    if len(hits) > 1:
        cand = ",".join(f"{gid}({name})" for gid, name in hits[:5])
        return f"ambiguous:{cand}"
    # fuzzy fallback: any shared token (letters/numbers kept whole)
    import re as _re

    tokens = [t for t in _re.split(r"[\s,，。、；:：]+", inp) if len(t) >= 2]
    if not tokens:
        tokens = [inp]
    scored = []
    for g in groups:
        gid = str(g.get("group_id") or g.get("groupCode") or "")
        gname = str(g.get("group_name") or g.get("groupName") or "")
        if not gname:
            continue
        share = sum(1 for t in tokens if t in gname)
        if share:
            scored.append((share, gid, gname))
    scored.sort(key=lambda x: -x[0])
    if len(scored) == 1:
        return f"matched:{scored[0][1]}"
    if len(scored) > 1:
        cand = ",".join(f"{gid}({name})" for _s, gid, name in scored[:5])
        return f"ambiguous:{cand}"
    hint = ",".join(f"{g.get('group_id') or g.get('groupCode')}({g.get('group_name') or g.get('groupName')})"
                    for g in groups[:3]) if groups else ""
    return f"none:{hint}"


async def _fetch_qce_groups() -> list[dict]:
    """Live group list from the QCE plugin (127.0.0.1:40653)."""
    import json
    import os
    import pathlib

    import httpx

    sec = pathlib.Path(os.path.expanduser("~")) / ".qq-chat-exporter" / "security.json"
    if not sec.exists():
        return []
    token = json.loads(sec.read_text(encoding="utf-8")).get("accessToken", "")
    async with httpx.AsyncClient(timeout=20) as c:
        try:
            r = await c.get("http://127.0.0.1:40653/api/groups",
                            headers={"Authorization": f"Bearer {token}"})
            data = (r.json().get("data") or {})
            return data.get("groups") or []
        except Exception:
            return []


async def _qqops_export(params: dict) -> str:
    """Export a QQ group's chat history via the local QCE plugin (port 40653)
    and auto-ingest the JSON into the candidate store.

    Returns {exported_msgs, candidates_added, file}."""
    import asyncio
    import json
    import os
    import pathlib
    import time

    import httpx

    group = str(params.get("group_id", "")).strip()
    if not group:
        return json.dumps({"error": "group_id 不能为空"}, ensure_ascii=False)
    if not group.isdigit():
        # group NAME fragment -> resolve via live QCE group list
        groups = await _fetch_qce_groups()
        if not groups:
            return json.dumps({"error": "无法获取群列表（QCE 未就绪？先 qq.bootstrap）"},
                              ensure_ascii=False)
        resolved = resolve_group_id(group, groups)
        if resolved.startswith("matched:"):
            group = resolved.split(":", 1)[1]
        elif resolved.startswith("ambiguous:"):
            return json.dumps({"error": "群名匹配到多个群，请用其中群号精确指定",
                               "candidates": resolved.split(":", 1)[1]},
                              ensure_ascii=False)
        else:
            hint = resolved.split(":", 1)[1] if ":" in resolved else ""
            return json.dumps({"error": f"找不到名为“{group}”的群",
                               "nearby": hint}, ensure_ascii=False)
    name = str(params.get("session_name") or "").strip()[:40] or f"g{group}"
    sec = pathlib.Path(os.path.expanduser("~")) / ".qq-chat-exporter" / "security.json"
    if not sec.exists():
        return json.dumps({"error": "QCE 未初始化（请先在 NapCat 插件面板打开 QQ 聊天记录导出）"},
                          ensure_ascii=False)
    token = json.loads(sec.read_text(encoding="utf-8")).get("accessToken", "")
    base = "http://127.0.0.1:40653"
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.post(base + "/api/messages/export", headers=headers, json={
            "peer": {"chatType": 2, "peerUid": group},
            "format": "JSON",
            "options": {},
            "sessionName": name,
        })
        r.raise_for_status()
        task = r.json().get("data") or {}
        task_id = task.get("taskId")
        if not task_id:
            return json.dumps({"error": "导出任务未创建"}, ensure_ascii=False)
        file_path = task.get("filePath", "")
        for _ in range(180):
            await asyncio.sleep(2)
            rr = await c.get(base + "/api/tasks/" + task_id, headers=headers)
            st = (rr.json().get("data") or {})
            if st.get("status") in ("completed", "failed"):
                break
        msgs = int(st.get("messageCount") or task.get("messageCount") or 0)
        if not file_path or not pathlib.Path(file_path).exists():
            # locate latest file for this group in the exports dir
            ex_dir = pathlib.Path(os.path.expanduser("~")) / ".qq-chat-exporter" / "exports"
            cands = sorted(ex_dir.glob(f"group_{group}_*.json"), key=lambda p: p.stat().st_mtime)
            file_path = str(cands[-1]) if cands else ""
    if not file_path:
        return json.dumps({"error": "导出文件未找到", "task": task_id}, ensure_ascii=False)
    # ingest into candidate store
    from backend.qqexport_ingest import ingest

    res = ingest(pathlib.Path(file_path))
    return json.dumps({"exported_msgs": msgs, "candidates_added": res["candidates"],
                       "deduped": res.get("deduped", 0), "file": file_path,
                       "note": "已入库候选区，可继续 qq.process 抽取"},
                      ensure_ascii=False)


async def _qqops_process(params: dict) -> str:
    from backend import qqextract

    max_items = int(params.get("max_items") or 12)
    res = await qqextract.run_batch(max_items=min(int(max_items), 48))
    import json

    return json.dumps(res, ensure_ascii=False)


async def _qqops_digest(params: dict) -> str:
    from backend import qqextract

    date = str(params.get("date") or "")
    f = await qqextract.digest_async(date or None)
    return f"已生成日汇编：{f}"


async def _qqops_summarize(params: dict) -> str:
    from backend import qqextract

    res = await qqextract.summarize()
    import json

    return json.dumps(res, ensure_ascii=False)


def task_plan(content: str, action: str = "add") -> str:
    """Yuanheng's own task board (docs/元亨的任务表.md).

    action=add: append a task under today's date section.
    action=done: mark the newest open (unchecked) line containing `content` as done.
    action=list: return today's lines (or the whole board if today is empty).
    """
    import datetime as _dt

    text = str(content or "").strip()
    action = str(action or "add").strip().lower()
    today = _dt.date.today().isoformat()
    TASK_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not TASK_FILE.exists():
        TASK_FILE.write_text("# 元亨的任务表\n", encoding="utf-8")

    def _sections() -> tuple[list[str], int]:
        lines = TASK_FILE.read_text(encoding="utf-8").splitlines()
        heads = [i for i, l in enumerate(lines) if l.startswith("## ")]
        return lines, (heads[-1] if heads else -1)

    if action == "list":
        lines, last = _sections()
        if lines and last >= 0 and lines[last].startswith("## " + today):
            return "\n".join(lines[last:]).strip() or "今天还没有任务"
        body = [l for l in lines if l.startswith("- [")][-15:]
        return "\n".join(body) if body else "任务表是空的"

    if action == "done":
        if not text:
            return "done 需要任务内容片段"
        lines, _ = _sections()
        for i in range(len(lines) - 1, -1, -1):
            if lines[i].startswith("- [ ]") and text in lines[i]:
                lines[i] = lines[i].replace("- [ ]", "- [x]", 1)
                TASK_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
                return f"已完成：{lines[i][6:]}"
        return "没找到含该内容的未完成任务"

    if action == "add":
        if not text or len(text) > 200:
            return "任务内容需在 1-200 字之间"
        lines = TASK_FILE.read_text(encoding="utf-8").splitlines()
        if not any(l.startswith("## " + today) for l in lines):
            if lines and lines[-1] != "":
                lines.append("")
            lines.append(f"## {today}")
        for i in range(len(lines) - 1, -1, -1):
            if lines[i].startswith("## " + today):
                lines.insert(i + 1, f"- [ ] {text}")
                break
        TASK_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return f"已加入任务表（{today}）：{text}"

    return f"未知动作：{action}"


def setup_scheduler_capabilities(registry: Optional[CapabilityRegistry] = None) -> CapabilityRegistry:
    registry = registry or CapabilityRegistry()
    for cap in scheduler_capabilities():
        registry.register_capability(cap)
    if not registry.get_policy(SCHEDULER_POLICY):
        registry.register_policy(SCHEDULER_POLICY, _policy_always_true)
    if not registry.get_policy(SAVE_APPROVAL_POLICY):
        registry.register_policy(SAVE_APPROVAL_POLICY, _policy_deny_all)
    if not registry.get_policy(DIARY_AUTO_POLICY):
        registry.register_policy(DIARY_AUTO_POLICY, _policy_always_true)
    if not registry.get_policy(TASK_AUTO_POLICY):
        registry.register_policy(TASK_AUTO_POLICY, _policy_always_true)
    if not registry.get_policy(QQOPS_POLICY):
        registry.register_policy(QQOPS_POLICY, _policy_always_true)
    if not registry.get_policy(KB_POLICY):
        registry.register_policy(KB_POLICY, _policy_always_true)
    if not registry.get_policy(APPROVE_POLICY):
        registry.register_policy(APPROVE_POLICY, _policy_always_true)
    if not registry.get_policy("diary.delete.approval"):
        registry.register_policy("diary.delete.approval", _policy_deny_all)
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
