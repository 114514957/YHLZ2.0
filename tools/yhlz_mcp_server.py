"""YHLZ MCP server (ledger 0160/0163): expose ledger/memory retrieval as tools so
coding assistants (利贞 on harness, via @deepseek-ai/dsh-mcp-client) query via
tool calls instead of reading files directly.

Routed through the SAME Capability Registry as agent sessions (single gate,
verify, commit) — ledger 0163 unification.  memory_save is wrapped with a
one-shot approval grant because invoking this tool from the dev agent IS the
user authorization (no interactive approver inside the MCP process).

Run (stdio):  python -B tools/yhlz_mcp_server.py
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _log_to_file(name: str) -> None:
    """stdio 传输下 stdout 只承载 JSON-RPC，stderr 会被宿主当成故障输出。

    FastMCP 的 configure_logging 会挂 RichHandler(console=stderr) 并调
    logging.basicConfig；而 basicConfig 在 root 已有 handler 时是空操作，
    所以提前给 root 装好文件 handler，日志就不会再进 stderr。
    """
    log_dir = _ROOT / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(log_dir / name, encoding="utf-8")
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-8s %(name)s %(message)s")
    )
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)

from mcp.server.fastmcp import FastMCP  # noqa: E402

from backend.target_scheduler_tools import (  # noqa: E402
    LEDGER_DELETE_POLICY,
    SAVE_APPROVAL_POLICY,
    setup_scheduler_capabilities,
)

_registry = setup_scheduler_capabilities()
mcp = FastMCP("yhlz")
_carriers_bound = False


def _ensure_carriers_bound() -> None:
    """Lazy owner-local binding; ledger reads never construct a memory service."""
    global _carriers_bound
    if _carriers_bound:
        return
    from backend.target_memory import TargetMemoryService
    from backend.memory_carriers import bind_memory_carriers
    service = TargetMemoryService(l1_scope="mcp")
    bind_memory_carriers(_registry, service, channel="owner_local", owner_access=True)
    _carriers_bound = True


async def _call_async(name: str, params: dict) -> str:
    if name in {"memory_save", "diary_write", "task_plan", "kb_add"}:
        _ensure_carriers_bound()
    res = await _registry.execute_openai_async(name, params)
    if not res.get("ok"):
        raise RuntimeError(f"{name} failed: {res.get('error', 'unknown')}")
    return str(res.get("output", ""))


@mcp.tool()
async def ledger_search(query: str, limit: int = 5) -> str:
    """Search the YHLZ project ledger (docs/上下文台账.md keyword index).
    Use for project history, decisions, record numbers, plans. Query in
    1-3 keywords (Chinese ok); returns matching lines with record ids."""
    return await _call_async("ledger_search", {"query": query, "limit": limit})


@mcp.tool()
async def ledger_get(no: int) -> str:
    """Read one YHLZ ledger record in full by its number (get numbers from
    ledger_search / ledger_list)."""
    return await _call_async("ledger_get", {"no": no})


@mcp.tool()
async def ledger_list(limit: int = 10, keyword: str = "") -> str:
    """List the most recent YHLZ ledger records (number + title). Optional
    keyword filters title/body."""
    return await _call_async("ledger_list", {"limit": limit, "keyword": keyword})


@mcp.tool()
async def ledger_add(title: str, body: str = "") -> str:
    """WRITE: append a new record to the YHLZ project ledger (single source of
    truth). Atomic write, auto-numbered, auto-backed-up. `body` is plain text
    (\\n for line breaks)."""
    return await _call_async("ledger_add", {"title": title, "body": body})


@mcp.tool()
async def ledger_update(no: int, title: str = "", append: str = "",
                        body: str = "") -> str:
    """WRITE: edit ledger record `no` — rename (title), append lines (append),
    or replace the whole body (body). Provide at least one."""
    return await _call_async("ledger_update", {
        "no": no, "title": title, "append": append, "body": body})


@mcp.tool()
async def ledger_delete(no: int) -> str:
    """WRITE/DESTRUCTIVE: delete ledger record `no`. The call itself is taken as
    the user's authorization (one-shot grant); a backup is always kept."""
    _registry.grant_policy_once(LEDGER_DELETE_POLICY)
    return await _call_async("ledger_delete", {"no": no})


@mcp.tool()
async def memory_recall(query: str, limit: int = 5) -> str:
    """Recall long-term memory entries (user preferences/decisions saved from
    conversations). Read-only; never deletes."""
    return await _call_async("memory_recall", {"query": query, "limit": limit})


@mcp.tool()
async def memory_health() -> str:
    """Owner-local READ ONLY memory status; counts only, no model or repair."""
    import json
    from backend.memory_health import snapshot
    report = snapshot(_ROOT / "cache/memstore/memstore.db",
                      kw_db_path=_ROOT / "cache/search/kw_index.db",
                      vec_db_path=_ROOT / "cache/embvec.db")
    return json.dumps(report, ensure_ascii=False)


@mcp.tool()
async def system_time() -> str:
    """Current local date/time and day of week."""
    return await _call_async("system_time", {})


@mcp.tool()
async def memory_save(content: str, kind: str = "preference", importance: int = 0) -> str:
    """WRITE operation: save a notable user preference/fact into long-term
    memory.  Kind: preference|fact|event|decision.  Content is checked by the
    constitution gate and deduplicated against existing memory.  Calling this
    tool records into the user's memory store — make sure the user asked for
    it."""
    _registry.grant_policy_once(SAVE_APPROVAL_POLICY)  # dev-agent call = user consent
    return await _call_async("memory_save", {"content": content, "kind": kind,
                                        "importance": importance})


@mcp.tool()
async def diary_read(limit: int = 5) -> str:
    """Read Yuanheng's diary (docs/元亨的日记.md), newest entries first."""
    return await _call_async("diary_list", {"limit": limit})


@mcp.tool()
async def diary_append(content: str) -> str:
    """Append an entry to Yuanheng's diary (her own notebook; shared access)."""
    return await _call_async("diary_write", {"content": content})


@mcp.tool()
async def file_list(path: str, limit: int = 30) -> str:
    """List a local directory (read-only). Whole-disk browsing allowed."""
    return await _call_async("file_list", {"path": path, "limit": limit})


@mcp.tool()
async def file_read(path: str, max_chars: int = 4000) -> str:
    """Read a local text file (read-only; sensitive/binary/huge files refused)."""
    return await _call_async("file_read", {"path": path, "max_chars": max_chars})


@mcp.tool()
async def web_fetch(url: str, max_chars: int = 4000) -> str:
    """Fetch a URL's text content (untrusted; category-filtered; source attached)."""
    return await _call_async("web_fetch", {"url": url, "max_chars": max_chars})


@mcp.tool()
async def web_search(query: str, limit: int = 5) -> str:
    """Zero-key web search (best-effort; returns sources)."""
    return await _call_async("web_search", {"query": query, "limit": limit})


if __name__ == "__main__":
    # Preload only with explicit semantic opt-in and never during training.
    # Preload the memory embedding model BEFORE serving.  Loading it lazily
    # inside the first memory_recall call blocks the stdio transport and the
    # client hangs (2026-09-29 fix).  ~12s one-time cost, then 0.1s per call.
    try:
        from backend.vector_memory import _load_model as _preload_vm
        from backend.memory_resource_policy import semantic_model_allowed
        if semantic_model_allowed():
            _preload_vm()
    except Exception:
        pass
    _log_to_file("yhlz_mcp_server.log")
    mcp.run(transport="stdio")
