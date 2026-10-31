"""MCP server regression tests (ledger 0160/0163, Phase 6)."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import unittest
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from backend.target_capability_registry import Capability, CapabilityRegistry

ROOT = Path(__file__).resolve().parent.parent
SERVER = [sys.executable, "-B", "tools/yhlz_mcp_server.py"]
CORE_TOOLS = {"ledger_search", "memory_recall", "system_time"}


def _text(result):
    return "\n".join(getattr(item, "text", "") for item in result.content)


def _server_parameters():
    return StdioServerParameters(
        command=sys.executable,
        args=["-B", "tools/yhlz_mcp_server.py"],
        cwd=str(ROOT),
    )


class TestMCPRegistration(unittest.TestCase):
    def test_tools_listed(self):
        async def go():
            async with stdio_client(_server_parameters()) as (r, w):
                async with ClientSession(r, w) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    return {tool.name for tool in tools.tools}

        names = asyncio.run(go())
        self.assertTrue(
            {
                "ledger_search", "memory_recall", "system_time", "memory_save",
                "diary_read", "diary_append", "file_list", "file_read",
                "web_fetch", "web_search",
            } <= names
        )

    def test_ledger_search_real_call(self):
        async def go():
            async with stdio_client(_server_parameters()) as (r, w):
                async with ClientSession(r, w) as session:
                    await session.initialize()
                    return await session.call_tool(
                        "ledger_search", {"query": "\u9ea6\u514b\u98ce", "limit": 2}
                    )

        result = asyncio.run(go())
        self.assertFalse(result.isError, _text(result))
        out = _text(result)
        self.assertIn("ledger:", out)
        self.assertIn("\u9ea6\u514b\u98ce", out)

    def test_core_tools_can_be_called_twice_after_discovery(self):
        async def go():
            async with stdio_client(_server_parameters()) as (r, w):
                async with ClientSession(r, w) as session:
                    await session.initialize()
                    names = {tool.name for tool in (await session.list_tools()).tools}
                    self.assertTrue(CORE_TOOLS <= names)
                    results = []
                    for _ in range(2):
                        results.append(await session.call_tool("system_time", {}))
                        results.append(await session.call_tool(
                            "ledger_search", {"query": "\u5168\u53cc\u5de5", "limit": 1}))
                        results.append(await session.call_tool(
                            "memory_recall", {"query": "\u626c\u58f0\u5668", "limit": 1}))
                    return results

        results = asyncio.run(go())
        self.assertEqual(len(results), 6)
        for result in results:
            self.assertFalse(result.isError, _text(result))
            self.assertTrue(_text(result).strip())

    def test_invalid_arguments_and_connection_recovery(self):
        cases = [
            {"query": ""},
            {"query": "x" * 81},
            {"query": "MCP", "limit": 0},
            {"query": "MCP", "limit": -1},
            {"query": "MCP", "limit": 501},
        ]

        async def go():
            async with stdio_client(_server_parameters()) as (r, w):
                async with ClientSession(r, w) as session:
                    await session.initialize()
                    invalid = [
                        await session.call_tool("ledger_search", params)
                        for params in cases
                    ]
                    healthy = await session.call_tool("system_time", {})
                    return invalid, healthy

        invalid, healthy = asyncio.run(go())
        for result in invalid:
            self.assertTrue(result.isError, _text(result))
            self.assertIn("invalid arguments", _text(result).lower())
        self.assertFalse(healthy.isError, _text(healthy))
        self.assertTrue(_text(healthy).strip())


class TestCapabilityRegistryIsolation(unittest.TestCase):
    def test_failed_capability_does_not_block_healthy_capability(self):
        registry = CapabilityRegistry()

        def broken(_params):
            raise RuntimeError("controlled failure")

        registry.register_capability(Capability("test.broken", broken))
        registry.register_capability(
            Capability("test.healthy", lambda _params: "healthy")
        )

        async def go():
            failed = await registry.execute_openai_async("test_broken", {})
            healthy = await registry.execute_openai_async("test_healthy", {})
            return failed, healthy

        failed, healthy = asyncio.run(go())
        self.assertFalse(failed["ok"])
        self.assertIn("RuntimeError", failed["error"])
        self.assertTrue(healthy["ok"])
        self.assertEqual(healthy["output"], "healthy")


class TestMCPRawStdio(unittest.TestCase):
    def _start(self):
        return subprocess.Popen(
            SERVER,
            cwd=ROOT,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )

    @staticmethod
    def _send(proc, payload):
        proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
        proc.stdin.flush()

    def _read_json(self, proc):
        line = proc.stdout.readline()
        self.assertTrue(line, "MCP server closed stdout before replying")
        try:
            return json.loads(line)
        except json.JSONDecodeError as exc:
            self.fail(f"stdout is not JSON: {line!r}")
            raise exc

    def _round_trip(self):
        proc = self._start()
        try:
            self._send(proc, {
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "yhlz-regression", "version": "1"},
                },
            })
            initialized = self._read_json(proc)
            self.assertEqual(initialized.get("id"), 1)
            self.assertIn("result", initialized)

            self._send(proc, {
                "jsonrpc": "2.0", "method": "notifications/initialized"
            })
            self._send(proc, {
                "jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}
            })
            listed = self._read_json(proc)
            self.assertEqual(listed.get("id"), 2)
            tool_names = {item["name"] for item in listed["result"]["tools"]}
            self.assertTrue(CORE_TOOLS <= tool_names)

            self._send(proc, {
                "jsonrpc": "2.0", "id": 3, "method": "tools/call",
                "params": {"name": "system_time", "arguments": {}},
            })
            called = self._read_json(proc)
            self.assertEqual(called.get("id"), 3)
            self.assertIn("result", called)
            self.assertFalse(called["result"].get("isError", False))
            return initialized, listed, called
        finally:
            proc.stdin.close()
            try:
                self.assertEqual(proc.wait(timeout=15), 0)
            finally:
                proc.stdout.close()
                proc.stderr.close()

    def test_raw_stdio_is_newline_delimited_json_rpc(self):
        initialized, listed, called = self._round_trip()
        for message in (initialized, listed, called):
            self.assertEqual(message.get("jsonrpc"), "2.0")
        self.assertTrue(called["result"]["content"])

    def test_server_can_restart_after_clean_disconnect(self):
        first = self._round_trip()
        second = self._round_trip()
        self.assertEqual(first[2].get("id"), 3)
        self.assertEqual(second[2].get("id"), 3)


if __name__ == "__main__":
    unittest.main()
