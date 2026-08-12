"""
测试: llm_adapter.py LLM 适配器
覆盖: MockLLMAdapter 行为 / get_adapter 工厂
"""
from __future__ import annotations

import asyncio
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from backend.agent.llm_adapter import (
    LLMAdapterError, MockLLMAdapter, get_adapter, reset_adapter, set_adapter,
)
from backend.agent.schemas import Message, ToolCall
from backend.agent.tool_registry import get_registry, reset_registry


class TestMockLLMAdapter(unittest.TestCase):
    """MockLLMAdapter 行为"""

    def setUp(self):
        reset_adapter()
        reset_registry()
        self.adapter = MockLLMAdapter()

    def tearDown(self):
        reset_adapter()
        reset_registry()

    def test_simple_text_response(self):
        """普通文本回应"""
        async def run():
            msgs = [Message.user("你好")]
            r = await self.adapter.generate_with_tools(msgs, tools=None)
            self.assertIsNotNone(r["content"])
            self.assertIsNone(r["tool_calls"])
            self.assertIn("你好", r["content"])
        asyncio.run(run())

    def test_time_tool_call(self):
        """含时间关键词 → 触发 get_time"""
        async def run():
            reg = get_registry()
            tools = reg.export_openai_tools()
            msgs = [Message.user("现在几点")]
            r = await self.adapter.generate_with_tools(msgs, tools=tools)
            self.assertIsNotNone(r["tool_calls"])
            self.assertEqual(r["tool_calls"][0].name, "get_time")
        asyncio.run(run())

    def test_date_tool_call(self):
        """含日期关键词 → 触发 get_date"""
        async def run():
            reg = get_registry()
            tools = reg.export_openai_tools()
            msgs = [Message.user("今天几号")]
            r = await self.adapter.generate_with_tools(msgs, tools=tools)
            self.assertIsNotNone(r["tool_calls"])
            self.assertEqual(r["tool_calls"][0].name, "get_date")
        asyncio.run(run())

    def test_calculator_tool_call(self):
        """含计算关键词 → 触发 calculator"""
        async def run():
            reg = get_registry()
            tools = reg.export_openai_tools()
            msgs = [Message.user("计算 1+2 等于多少")]
            r = await self.adapter.generate_with_tools(msgs, tools=tools)
            self.assertIsNotNone(r["tool_calls"])
            self.assertEqual(r["tool_calls"][0].name, "calculator")
        asyncio.run(run())

    def test_final_answer_after_tool_result(self):
        """含 tool 消息 → 生成最终回答"""
        async def run():
            msgs = [
                Message.user("几点了"),
                Message.assistant(content=None, tool_calls=[ToolCall(id="c1", name="get_time", arguments={})]),
                Message.tool(content='{"time": "12:00"}', tool_call_id="c1", name="get_time"),
            ]
            r = await self.adapter.generate_with_tools(msgs, tools=None)
            self.assertIsNotNone(r["content"])
            self.assertIsNone(r["tool_calls"])
            self.assertIn("12:00", r["content"])
        asyncio.run(run())

    def test_generate_no_tools(self):
        """generate 不带工具"""
        async def run():
            text = await self.adapter.generate([Message.user("hi")])
            self.assertIn("hi", text)
        asyncio.run(run())

    def test_stream_generate(self):
        """流式生成"""
        async def run():
            chunks = []
            async for ch in self.adapter.stream_generate([Message.user("hello")]):
                chunks.append(ch)
            self.assertGreater(len(chunks), 0)
            full = "".join(chunks)
            self.assertIn("hello", full)
        asyncio.run(run())


class TestGetAdapter(unittest.TestCase):
    """get_adapter 工厂"""

    def setUp(self):
        reset_adapter()

    def tearDown(self):
        reset_adapter()
        os.environ.pop("YHLZ_AGENT_TEST_MODE", None)
        os.environ.pop("YHLZ_TEST_MODE", None)

    def test_returns_mock_in_test_mode(self):
        """TEST_MODE → MockLLMAdapter"""
        os.environ["YHLZ_AGENT_TEST_MODE"] = "true"
        adapter = get_adapter()
        self.assertIsInstance(adapter, MockLLMAdapter)

    def test_set_adapter_override(self):
        """set_adapter 显式注入"""
        mock = MockLLMAdapter()
        set_adapter(mock)
        self.assertIs(get_adapter(), mock)

    def test_singleton(self):
        """单例: 多次调用返回同一实例"""
        os.environ["YHLZ_AGENT_TEST_MODE"] = "true"
        a1 = get_adapter()
        a2 = get_adapter()
        self.assertIs(a1, a2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
