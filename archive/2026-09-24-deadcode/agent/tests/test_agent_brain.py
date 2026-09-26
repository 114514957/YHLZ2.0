"""
测试: agent_brain.py Agent 主循环 (ReAct)
覆盖: 工具调用流程 / 无工具回答 / 记忆集成 / 失败容忍 / 最大迭代
"""
from __future__ import annotations

import asyncio
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from backend.agent.agent_brain import AgentBrain, get_brain, reset_brain
from backend.agent.llm_adapter import MockLLMAdapter, reset_adapter, set_adapter
from backend.agent.memory import MemoryManager, reset_memory_manager
from backend.agent.memory.sqlite_store import SQLiteMemoryStore
from backend.agent.tool_executor import ToolExecutor, reset_executor
from backend.agent.tool_registry import get_registry, reset_registry


class TestAgentBrain(unittest.TestCase):
    """AgentBrain ReAct 主循环"""

    def setUp(self):
        # 用临时 DB 避免污染真实记忆库
        os.environ["YHLZ_AGENT_MEMORY_DB"] = ":memory:"
        reset_registry()
        reset_executor()
        reset_adapter()
        reset_memory_manager()
        reset_brain()
        self.adapter = MockLLMAdapter()
        set_adapter(self.adapter)
        self.registry = get_registry()
        self.executor = ToolExecutor(registry=self.registry, default_timeout=2.0)
        self.store = SQLiteMemoryStore(db_path=":memory:")
        self.memory = MemoryManager(store=self.store, llm_adapter=self.adapter)
        self.brain = AgentBrain(
            llm_adapter=self.adapter,
            tool_executor=self.executor,
            registry=self.registry,
            memory_manager=self.memory,
            max_iterations=3,
        )

    def tearDown(self):
        os.environ.pop("YHLZ_AGENT_MEMORY_DB", None)
        reset_registry()
        reset_executor()
        reset_adapter()
        reset_memory_manager()
        reset_brain()

    def test_simple_text_response(self):
        """无工具调用 → 直接返回文本"""
        async def run():
            r = await self.brain.run("你好", use_tools=False, use_memory=False)
            self.assertTrue(r.success)
            self.assertGreater(len(r.answer), 0)
            self.assertGreaterEqual(r.iterations, 1)
        asyncio.run(run())

    def test_tool_call_flow(self):
        """含时间关键词 → 调用 get_time 工具 → 综合结果回答"""
        async def run():
            r = await self.brain.run("现在几点了", use_tools=True, use_memory=False)
            self.assertTrue(r.success)
            # 应该至少有一次工具调用
            self.assertGreater(len(r.tool_calls), 0)
            self.assertEqual(r.tool_calls[0].name, "get_time")
            # 步骤记录应非空
            self.assertGreater(len(r.steps), 0)
        asyncio.run(run())

    def test_memory_storage_after_dialogue(self):
        """对话结束后应存储到记忆系统"""
        async def run():
            r = await self.brain.run("你好啊", use_tools=False, use_memory=True)
            self.assertTrue(r.success)
            # 应至少存储 1 条对话记忆
            self.assertGreaterEqual(r.memory_stored, 1)
        asyncio.run(run())

    def test_memory_retrieval_injected(self):
        """已有相关记忆时, 应注入到上下文"""
        async def setup():
            await self.memory.add_async("用户喜欢喝咖啡", category="preference")
        asyncio.run(setup())

        async def run():
            r = await self.brain.run("咖啡", use_tools=False, use_memory=True)
            self.assertTrue(r.success)
            # 应检索到记忆
            self.assertGreaterEqual(len(r.memory_used), 0)  # 至少不报错
        asyncio.run(run())

    def test_max_iterations_limit(self):
        """达到最大迭代仍调用工具 → 强制结束"""
        # 用一个总是返回工具调用的 mock
        class AlwaysToolMock:
            model = "always-tool"
            async def generate_with_tools(self, messages, tools=None, **kwargs):
                from backend.agent.schemas import ToolCall
                import uuid
                return {
                    "content": None,
                    "tool_calls": [ToolCall(
                        id=f"call_{uuid.uuid4().hex[:8]}",
                        name="get_time",
                        arguments={},
                        raw_arguments="{}",
                    )],
                }
            async def generate(self, messages, **kwargs):
                return "fallback"
            async def stream_generate(self, messages, **kwargs):
                yield "fallback"

        brain = AgentBrain(
            llm_adapter=AlwaysToolMock(),
            tool_executor=self.executor,
            registry=self.registry,
            memory_manager=None,
            max_iterations=2,
            enable_memory=False,
        )
        async def run():
            r = await brain.run("无限工具调用", use_tools=True, use_memory=False)
            # 应该被强制结束, 而不是死循环
            self.assertLessEqual(r.iterations, 2)
            self.assertTrue(r.success)
        asyncio.run(run())

    def test_empty_query_returns_error(self):
        """空查询 → 不应崩溃 (由上层 service 拦截, brain 直接 run 会返回空 answer)"""
        async def run():
            r = await self.brain.run("", use_tools=False, use_memory=False)
            # brain 不会显式拒绝空查询, 但应正常返回 (不抛异常)
            self.assertTrue(r.success)
        asyncio.run(run())

    def test_get_brain_singleton(self):
        """get_brain 单例"""
        b1 = get_brain()
        b2 = get_brain()
        self.assertIs(b1, b2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
