"""Regression probe for the project's yhlz stdio MCP client/server contract.

This tool deliberately does not claim that a DeepSeek desktop UI is connected.
It proves the local stdio contract that a compatible work-agent client can use.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parent.parent
SERVER = ROOT / "tools" / "yhlz_mcp_server.py"
CORE_TOOLS = {"ledger_search", "memory_recall", "system_time"}
LEDGER_SOURCE_RE = re.compile(r"ledger:\d{4}:[^\s,)\]}]+")
SENSITIVE_RE = re.compile(
    r"(?i)(?:api[_ -]?key|access[_ -]?token|secret|password|bearer)\s*[:=]\s*[^\s,}]+"
)


def _text(result) -> str:
    return "\n".join(
        getattr(item, "text", "") for item in getattr(result, "content", [])
    )


def _server_parameters() -> StdioServerParameters:
    return StdioServerParameters(
        command=sys.executable,
        args=["-B", str(SERVER)],
        cwd=str(ROOT),
    )


async def _call(session, tool: str, arguments: dict) -> dict:
    started = time.perf_counter()
    result = await session.call_tool(tool, arguments)
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    return {
        "tool": tool,
        "arguments": arguments,
        "is_error": bool(result.isError),
        "elapsed_ms": elapsed_ms,
        "text": _text(result),
    }


async def _one_connection(queries: list[str], connection_id: int) -> dict:
    report = {"connection_id": connection_id, "steps": [], "passed": True}
    async with stdio_client(_server_parameters()) as (read, write):
        async with ClientSession(read, write) as session:
            info = await session.initialize()
            report["server"] = {
                "name": getattr(info.serverInfo, "name", ""),
                "version": getattr(info.serverInfo, "version", ""),
            }
            listed = await session.list_tools()
            report["tools"] = sorted(tool.name for tool in listed.tools)
            report["initialize_ok"] = bool(report["server"]["name"])
            report["core_tools_present"] = CORE_TOOLS <= set(report["tools"])

            report["steps"].append(await _call(session, "system_time", {}))
            for query in queries:
                report["steps"].append(
                    await _call(
                        session,
                        "ledger_search",
                        {"query": query, "limit": 10},
                    )
                )
            report["steps"].append(
                await _call(
                    session,
                    "memory_recall",
                    {"query": "扬声器", "limit": 3},
                )
            )

            invalid = await _call(
                session,
                "ledger_search",
                {"query": "", "limit": 10},
            )
            report["invalid_argument"] = invalid
            report["steps"].append(invalid)
            recovery = await _call(session, "system_time", {})
            report["after_invalid_recovery"] = recovery
            report["steps"].append(recovery)

    successful_ledger = [
        step
        for step in report["steps"]
        if step["tool"] == "ledger_search" and not step["is_error"]
    ]
    report["ledger_source_ids"] = sorted(
        set(
            match
            for step in successful_ledger
            for match in LEDGER_SOURCE_RE.findall(step["text"])
        )
    )
    report["passed"] = all(
        [
            report["initialize_ok"],
            report["core_tools_present"],
            bool(successful_ledger),
            bool(report["ledger_source_ids"]),
            any(
                step["tool"] == "memory_recall" and not step["is_error"]
                for step in report["steps"]
            ),
            report["invalid_argument"]["is_error"],
            not report["after_invalid_recovery"]["is_error"],
        ]
    )
    return report


async def probe(queries: list[str], output: Path | None) -> int:
    connections = [
        await _one_connection(queries, 1),
        await _one_connection(queries, 2),
    ]
    all_text = json.dumps(connections, ensure_ascii=False)
    report = {
        "phase": "Phase 7",
        "probe": "DeepSeek-compatible local MCP client regression",
        "generated_by": "tools/voice_ledger_mcp_probe.py",
        "queries": queries,
        "connections": connections,
        "two_independent_connections_ok": all(item["passed"] for item in connections),
        "sensitive_information_found": bool(SENSITIVE_RE.search(all_text)),
        "limitations": [
            "仅证明本地 stdio MCP client/server 契约可用。",
            "未自动验证 DeepSeek 桌面端或工作 Agent 的真实配置界面。",
            "ledger_append 不在当前工具集合中，本探针不伪造台账写入。",
        ],
    }
    report["passed"] = (
        report["two_independent_connections_ok"]
        and not report["sensitive_information_found"]
    )
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--query",
        action="append",
        help="ledger_search query; repeat for multiple queries",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    raise SystemExit(asyncio.run(probe(args.query or ["适配器", "全双工"], args.output)))
