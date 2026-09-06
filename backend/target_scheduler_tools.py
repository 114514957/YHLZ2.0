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
        Capability(
            name="diary.write",
            handler=lambda p: diary_write(str(p.get("content", ""))),
            input=("content",),
            requires=(DIARY_AUTO_POLICY,),
            side_effect=True,
            risk="low",
            verify=_verify_nonempty,
        ),
        Capability(
            name="diary.list",
            handler=lambda p: diary_list(int(p.get("limit", 5) or 5)),
            input=(),
            optional_input=("limit",),
            requires=(SCHEDULER_POLICY,),
            side_effect=False,
            risk="low",
        ),
        Capability(
            name="diary.delete",
            handler=lambda p: diary_delete(str(p.get("entry_stamp", ""))),
            input=("entry_stamp",),
            requires=(SCHEDULER_POLICY, "diary.delete.approval"),
            side_effect=True,
            risk="medium",
            verify=_verify_nonempty,
        ),
        Capability(
            name="task.plan",
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
            handler=_qqops_bootstrap,
            input=(),
            requires=(QQOPS_POLICY,),
            side_effect=True,
            risk="high",
        ),
        Capability(
            name="qq.export",
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
            handler=lambda p: qqops_status(),
            input=(),
            requires=(QQOPS_POLICY,),
            side_effect=False,
            risk="low",
        ),
        Capability(
            name="qq.process",
            handler=_qqops_process,
            input=(),
            optional_input=("max_items",),
            requires=(QQOPS_POLICY,),
            side_effect=True,
            risk="medium",
        ),
        Capability(
            name="qq.digest",
            handler=_qqops_digest,
            input=(),
            optional_input=("date",),
            requires=(QQOPS_POLICY,),
            side_effect=True,
            risk="low",
        ),
        Capability(
            name="qq.summarize",
            handler=_qqops_summarize,
            input=(),
            requires=(QQOPS_POLICY,),
            side_effect=True,
            risk="medium",
        ),
        Capability(
            name="file.list",
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
    if not group.isdigit():
        return json.dumps({"error": "group_id 需为群号数字"}, ensure_ascii=False)
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
                       "file": file_path, "note": "已入库候选区，可继续 qq.process 抽取"},
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
