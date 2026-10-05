"""Turn evidence base (R1, 2026-10-03; ledger 0592/0593; R3 包B 强化).

目标：让"查到了 / 存好了 / 执行了"都有独立依据。

- ``new_id``：每轮分配唯一 run_id / trace_id。
- ``EVIDENCE_STAGES``：请求接受 → 模型开始 → 工具开始 → 工具返回 → 独立读回 → 输出发布。
- ``carrier_state``：写前廉价快照（文件 size/mtime），用于判断"本次是否真的写入"。
- ``readback``：写类工具成功后再从**载体**独立只读回读；结合写前快照，要求
  **载体确实变化 且 内容命中**，否则 effect_missing（防"旧前缀/旧记录"假验证，E1）。
只读、不写、不改变业务状态；失败不抛异常（返回 error 状态）。
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import uuid
from typing import Any

EVIDENCE_STAGES = (
    "request_accepted",
    "model_start",
    "tool_start",
    "tool_return",
    "independent_readback",
    "output_published",
)

_WRITE_CARRIERS = {
    "diary.write": "diary_file",
    "task.plan": "task_file",
    "schedule.plan": "schedule_file",
    "kb.add": "kb_db",
    "memory.save": "memstore_db",
}


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def _norm(name: str) -> str:
    return str(name or "").replace("_", ".")


def _read_text(path: Any) -> str:
    p = pathlib.Path(str(path))
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8", errors="replace")


def _file_state(path: Any) -> dict:
    p = pathlib.Path(str(path))
    if not p.exists():
        return {"exists": False}
    st = p.stat()
    return {"exists": True, "size": st.st_size, "mtime": st.st_mtime}


def _changed(before: dict | None, after: dict) -> bool:
    """载体是否相对写前快照发生变化；before 为 None（无快照）时不阻断。"""
    if not before:
        return True
    if not before.get("exists"):
        return bool(after.get("exists"))
    return (after.get("size") != before.get("size")
            or after.get("mtime") != before.get("mtime"))


def _carrier_path(carrier: str) -> Any:
    if carrier == "diary_file":
        import backend.target_scheduler_tools as st
        return st.DIARY_FILE
    if carrier == "task_file":
        import backend.target_scheduler_tools as st
        return st.TASK_FILE
    if carrier == "schedule_file":
        import backend.target_schedule as sched
        return sched.SCHED_FILE
    return None


def carrier_state(tool_name: str, arguments: dict[str, Any] | None = None) -> dict:
    """写前快照（仅文件类载体）；含"该内容写前是否已存在"用于幂等判定。"""
    carrier = _WRITE_CARRIERS.get(_norm(tool_name), "")
    try:
        p = _carrier_path(carrier)
        if p is None:
            return {}
        st = _file_state(p)
        needle = str((arguments or {}).get("content")
                     or (arguments or {}).get("summary")
                     or (arguments or {}).get("name") or "").strip()
        if needle and st.get("exists"):
            st["needle_present"] = needle[:24] in _read_text(p)
        return st
    except Exception:
        return {}


def _struct(carrier: str, status: str, action: str, needle: str, extra: dict | None = None) -> dict:
    """T2(0610): 结构化效果字段（供统一发布/恢复路径使用）。"""
    out = {"status": status, "carrier": carrier, "action": action,
           "subject_ref": carrier,
           "effect_id": (hashlib.sha256(needle[:24].encode("utf-8")).hexdigest()[:12]
                         if needle else "")}
    if extra:
        out.update(extra)
    return out


def readback(tool_name: str, arguments: dict[str, Any] | None = None,
             output: str = "", before: dict | None = None) -> dict[str, Any]:
    """独立只读回读，精确区分：新建成功 / 幂等已有 / 未见变化 / 未命中。

    T2(0608/0610)：返回结构化字段 `action/subject_ref/effect_id/version` 供统一
    发布与恢复路径使用；`idempotent_existing` 为合法幂等（非失败）。
    """
    name = _norm(tool_name)
    args = dict(arguments or {})
    carrier = _WRITE_CARRIERS.get(name, "")
    if not carrier:
        return {"status": "unsupported", "carrier": "", "detail": "非写类工具"}
    needle = str(args.get("content") or args.get("summary") or args.get("name") or "").strip()
    try:
        path = _carrier_path(carrier)
        if path is not None:
            after = _file_state(path)
            changed = _changed(before, after) if before else True
            body = _read_text(path)
            present = bool(needle) and needle[:24] in body
            ver = {"version": f"size:{after.get('size')}"}
            if present and before and not changed and before.get("needle_present"):
                return {**_struct(carrier, "idempotent_existing", "noop", needle, ver),
                        "detail": "写前已存在同内容且载体未变（合法幂等）"}
            if not changed:
                return {**_struct(carrier, "effect_missing", "unknown", needle, ver),
                        "detail": "载体未见变化（疑似本次未写入）"}
            if present:
                return {**_struct(carrier, "verified", "created", needle, ver),
                        "detail": "载体命中"}
            return {**_struct(carrier, "effect_missing", "unknown", needle, ver),
                    "detail": "载体未读到该内容"}
        if carrier == "kb_db":
            import backend.yuanheng_kb as kb
            p = pathlib.Path(str(kb.DEFAULT_KB_DB))
            if not p.exists():
                return {**_struct(carrier, "effect_missing", "unknown", needle),
                        "detail": "kb 库不存在"}
            hits = kb.kb_query(query=needle[:24], limit=3)
            return {**_struct(carrier, "verified" if hits else "effect_missing",
                                    "created" if hits else "unknown", needle),
                    "detail": f"kb_query 命中 {len(hits)}"}
        return {"status": "unsupported", "carrier": carrier,
                "detail": "需会话级 carrier 引用（R4 载体收口时接入）"}
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "carrier": carrier,
                "detail": f"{type(exc).__name__}: {str(exc)[:120]}"}


def _verdict(body: str, needle: str, carrier: str) -> dict[str, Any]:
    if not needle:
        return {"status": "unsupported", "carrier": carrier, "detail": "无可核对内容"}
    hit = needle[:24] in body
    return {"status": "verified" if hit else "effect_missing",
            "carrier": carrier, "detail": "载体命中" if hit else "载体未读到该内容"}


def summarize(tool_uses: list[Any]) -> dict[str, Any]:
    out = []
    for u in (tool_uses or []):
        out.append({
            "name": getattr(u, "name", ""),
            "ok": bool(getattr(u, "ok", False)),
            "trace_id": getattr(u, "trace_id", ""),
            "readback": getattr(u, "readback", ""),
            "elapsed_ms": getattr(u, "elapsed_ms", 0.0),
        })
    return {"n": len(out), "tool_uses": out}
