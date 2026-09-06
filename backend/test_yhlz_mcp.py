"""MCP server tests (ledger 0160): registration + stdio round-trip."""

import asyncio
import sys
import unittest

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SERVER = [sys.executable, "-B", "tools/yhlz_mcp_server.py"]


class TestMCPRegistration(unittest.TestCase):
    def test_tools_listed(self):
        async def go():
            async with stdio_client(StdioServerParameters(command=SERVER[0], args=SERVER[1:])) as (r, w):
                async with ClientSession(r, w) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    names = {t.name for t in tools.tools}
                    return names

        names = asyncio.run(go())
        self.assertTrue(
            {"ledger_search", "memory_recall", "system_time", "memory_save",
             "diary_read", "diary_append", "file_list", "file_read",
             "web_fetch", "web_search"} <= names
        )

    def test_ledger_search_real_call(self):
        async def go():
            async with stdio_client(StdioServerParameters(command=SERVER[0], args=SERVER[1:])) as (r, w):
                async with ClientSession(r, w) as session:
                    await session.initialize()
                    res = await session.call_tool("ledger_search", {"query": "麦克风", "limit": 2})
                    return str(res.content)[:200]

        out = asyncio.run(go())
        self.assertIn("ledger:", out)
        self.assertIn("麦克风", out)


if __name__ == "__main__":
    unittest.main()
