"""YHLZ MCP server (ledger 0160/0163): expose ledger/memory retrieval as tools so
coding assistants (opencode etc.) query via tool calls instead of reading
files directly.

Routed through the SAME Capability Registry as agent sessions (single gate,
verify, commit) — ledger 0163 unification.  memory_save is wrapped with a
one-shot approval grant because invoking this tool from opencode IS the user
authorization (no interactive approver inside the MCP process).

Run (stdio):  python -B tools/yhlz_mcp_server.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from mcp.server.fastmcp import FastMCP  # noqa: E402

from backend.target_scheduler_tools import (  # noqa: E402
    SAVE_APPROVAL_POLICY,
    setup_scheduler_capabilities,
)

_registry = setup_scheduler_capabilities()
mcp = FastMCP("yhlz")


def _call(name: str, params: dict) -> str:
    res = _registry.execute_openai(name, params)
    if not res.get("ok"):
        raise RuntimeError(f"{name} failed: {res.get('error', 'unknown')}")
    return str(res.get("output", ""))


@mcp.tool()
def ledger_search(query: str, limit: int = 5) -> str:
    """Search the YHLZ project ledger (docs/上下文台账.md keyword index).
    Use for project history, decisions, record numbers, plans. Query in
    1-3 keywords (Chinese ok); returns matching lines with record ids."""
    return _call("ledger_search", {"query": query, "limit": limit})


@mcp.tool()
def memory_recall(query: str, limit: int = 5) -> str:
    """Recall long-term memory entries (user preferences/decisions saved from
    conversations). Read-only; never deletes."""
    return _call("memory_recall", {"query": query, "limit": limit})


@mcp.tool()
def system_time() -> str:
    """Current local date/time and day of week."""
    return _call("system_time", {})


@mcp.tool()
def memory_save(content: str, kind: str = "preference", importance: int = 0) -> str:
    """WRITE operation: save a notable user preference/fact into long-term
    memory.  Kind: preference|fact|event|decision.  Content is checked by the
    constitution gate and deduplicated against existing memory.  Calling this
    tool records into the user's memory store — make sure the user asked for
    it."""
    _registry.grant_policy_once(SAVE_APPROVAL_POLICY)  # opencode call = user consent
    return _call("memory_save", {"content": content, "kind": kind,
                                 "importance": importance})


if __name__ == "__main__":
    mcp.run(transport="stdio")
