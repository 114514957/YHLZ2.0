"""
测试: service.py AgentService 统一入口
覆盖: chat / chat_stream / plan / list_tools / memory_* / status
"""
from __future__ import annotations

import asyncio
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from backend.agent.llm_adapter import MockLLMAdapter, reset_adapter, set_adapter
from backend.agent.memory import MemoryManager, reset_memory_manager
from backend.agent.memory.sqlite_store import SQLiteMemoryStore
from backend.agent.schemas import Message
from backend.agent.service import AgentService, get_service, reset_all, reset_service
from backend.agent.tool_executor import ToolExecutor, reset_executor
from backend.agent.tool_registry import get_registry, reset_registry


class TestAgentService(unittest.TestCase):
    """AgentService 统一入口"""

    def setUp(self):
        os.environ["YHLZ_AGENT_MEMORY_DB"] = ":memory:"
        reset_all()
        self.adapter = MockLLMAdapter()
        set_adapter(self.adapter)
        self.registry = get_registry()
        self.executor = ToolExecutor(registry=self.registry, default_timeout=2.0)
        self.store = SQLiteMemoryStore(db_path=":memory:")
        self.memory = MemoryManager(store=self.store, llm_adapter=self.adapter)
        self.svc = AgentService(
            registry=self.registry,
            executor=self.executor,
            memory=self.memory,
            llm_adapter=self.adapter,
        )

    def tearDown(self):
        os.environ.pop("YHLZ_AGENT_MEMORY_DB", None)
        reset_all()

    # ── chat ──────────────────────────────────────────────────────
    def test_chat_simple(self):
        """简单对话"""
        async def run():
            r = await self.svc.chat("你好", use_tools=False, use_memory=False)
            self.assertTrue(r.success)
            self.assertGreater(len(r.answer), 0)
        asyncio.run(run())

    def test_chat_with_tool(self):
        """带工具的对话"""
        async def run():
            r = await self.svc.chat("现在几点", use_tools=True, use_memory=False)
            self.assertTrue(r.success)
            self.assertGreater(len(r.tool_calls), 0)
        asyncio.run(run())

    def test_chat_empty_query(self):
        """空查询 → 返回失败"""
        async def run():
            r = await self.svc.chat("", use_tools=False, use_memory=False)
            self.assertFalse(r.success)
            self.assertIn("空", r.error)
        asyncio.run(run())

    def test_chat_with_history(self):
        """带历史消息的对话"""
        async def run():
            history = [
                Message.user("之前我问过问题"),
                Message.assistant("之前回答过"),
            ]
            r = await self.svc.chat("继续", history=history, use_tools=False, use_memory=False)
            self.assertTrue(r.success)
        asyncio.run(run())

    # ── chat_stream ───────────────────────────────────────────────
    def test_chat_stream(self):
        """流式对话"""
        async def run():
            chunks = []
            async for ch in self.svc.chat_stream("你好", history=None):
                chunks.append(ch)
            self.assertGreater(len(chunks), 0)
            full = "".join(chunks)
            self.assertGreater(len(full), 0)
        asyncio.run(run())

    # ── plan ──────────────────────────────────────────────────────
    def test_plan(self):
        """同步规划"""
        plan = self.svc.plan("查询当前时间")
        self.assertIsNotNone(plan)
        self.assertGreaterEqual(len(plan.steps), 1)

    def test_plan_async(self):
        """异步规划"""
        async def run():
            plan = await self.svc.plan_async("查询当前时间")
            self.assertIsNotNone(plan)
            self.assertGreaterEqual(len(plan.steps), 1)
        asyncio.run(run())

    # ── 工具管理 ──────────────────────────────────────────────────
    def test_list_tools(self):
        """列出工具"""
        tools = self.svc.list_tools()
        self.assertGreater(len(tools), 0)
        names = [t["name"] for t in tools]
        self.assertIn("get_time", names)
        self.assertIn("calculator", names)

    def test_list_tools_by_category(self):
        """按类别列出工具"""
        builtin = self.svc.list_tools(category="builtin")
        self.assertGreater(len(builtin), 0)
        for t in builtin:
            self.assertEqual(t["category"], "builtin")

    def test_get_tool(self):
        """获取工具详情"""
        t = self.svc.get_tool("get_time")
        self.assertIsNotNone(t)
        self.assertEqual(t["name"], "get_time")

    def test_get_tool_nonexistent(self):
        """获取不存在的工具"""
        t = self.svc.get_tool("nonexistent_tool")
        self.assertIsNone(t)

    def test_export_openai_tools(self):
        """导出 OpenAI tools 格式"""
        tools = self.svc.export_openai_tools()
        self.assertGreater(len(tools), 0)
        for t in tools:
            self.assertIn("type", t)
            self.assertEqual(t["type"], "function")
            self.assertIn("function", t)

    # ── 记忆管理 ──────────────────────────────────────────────────
    def test_memory_add_and_get(self):
        """添加并获取记忆"""
        async def run():
            mid = await self.svc.memory_add("测试记忆", category="fact")
            self.assertIsNotNone(mid)
            entry = await self.svc.memory_get(mid)
            self.assertIsNotNone(entry)
            self.assertEqual(entry.content, "测试记忆")
        asyncio.run(run())

    def test_memory_list(self):
        """列出记忆"""
        async def run():
            await self.svc.memory_add("记忆1", category="fact")
            await self.svc.memory_add("记忆2", category="preference")
            all_items = await self.svc.memory_list()
            self.assertGreaterEqual(len(all_items), 2)
            facts = await self.svc.memory_list(category="fact")
            self.assertGreaterEqual(len(facts), 1)
        asyncio.run(run())

    def test_memory_search(self):
        """搜索记忆"""
        async def run():
            await self.svc.memory_add("用户喜欢咖啡", category="preference")
            results = await self.svc.memory_search("咖啡")
            self.assertGreaterEqual(len(results), 1)
        asyncio.run(run())

    def test_memory_count(self):
        """记忆计数"""
        async def run():
            initial = await self.svc.memory_count()
            await self.svc.memory_add("新记忆", category="fact")
            after = await self.svc.memory_count()
            self.assertEqual(after, initial + 1)
        asyncio.run(run())

    def test_memory_delete(self):
        """删除记忆"""
        async def run():
            mid = await self.svc.memory_add("待删除", category="fact")
            ok = await self.svc.memory_delete(mid)
            self.assertTrue(ok)
            entry = await self.svc.memory_get(mid)
            self.assertIsNone(entry)
        asyncio.run(run())

    def test_memory_clear(self):
        """清空记忆"""
        async def run():
            await self.svc.memory_add("记忆A", category="fact")
            await self.svc.memory_add("记忆B", category="preference")
            deleted = await self.svc.memory_clear()
            self.assertGreaterEqual(deleted, 2)
            count = await self.svc.memory_count()
            self.assertEqual(count, 0)
        asyncio.run(run())

    def test_memory_short_term(self):
        """短期记忆"""
        # short_term 在 store_dialogue_async 时填充
        async def run():
            await self.svc._memory.store_dialogue_async("用户问题", "AI回答")
            items = self.svc.memory_short_term(limit=10)
            self.assertGreaterEqual(len(items), 1)
        asyncio.run(run())

    # ── 状态 ──────────────────────────────────────────────────────
    def test_status(self):
        """系统状态"""
        s = self.svc.status()
        self.assertEqual(s["version"], "3.0.0")
        self.assertEqual(s["llm_mode"], "mock")
        self.assertGreater(s["tools_count"], 0)
        self.assertIn("get_time", s["builtin_tools"])
        self.assertTrue(s["memory_enabled"])

    # ── 单例 ──────────────────────────────────────────────────────
    def test_get_service_singleton(self):
        """get_service 单例"""
        s1 = get_service()
        s2 = get_service()
        self.assertIs(s1, s2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
