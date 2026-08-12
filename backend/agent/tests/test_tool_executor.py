"""
测试: tool_executor.py 工具执行器
覆盖: 执行/参数校验/超时/异常隔离
"""
from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from backend.agent.schemas import Tool, ToolCall, ToolSchema
from backend.agent.tool_executor import ToolExecutor, get_executor, reset_executor
from backend.agent.tool_registry import get_registry, reset_registry


class TestToolExecutor(unittest.TestCase):

    def setUp(self):
        reset_registry()
        reset_executor()
        self.reg = get_registry()
        self.exec = ToolExecutor(registry=self.reg, default_timeout=2.0)

    def tearDown(self):
        reset_registry()
        reset_executor()

    def test_execute_builtin_get_time(self):
        """执行内置工具 get_time"""
        tc = ToolCall(id="c1", name="get_time", arguments={})
        result = self.exec.execute(tc)
        self.assertFalse(result.is_error)
        self.assertIn("time", result.output)
        self.assertGreater(result.latency_ms, 0)

    def test_execute_builtin_calculator(self):
        """执行 calculator"""
        tc = ToolCall(id="c2", name="calculator", arguments={"expression": "2**10"})
        result = self.exec.execute(tc)
        self.assertFalse(result.is_error)
        self.assertIn("1024", result.output)

    def test_execute_nonexistent_tool(self):
        """工具不存在"""
        tc = ToolCall(id="c3", name="nonexistent", arguments={})
        result = self.exec.execute(tc)
        self.assertTrue(result.is_error)
        self.assertIn("不存在", result.output)

    def test_execute_missing_required_param(self):
        """缺少必填参数"""
        tc = ToolCall(id="c4", name="calculator", arguments={})  # 缺 expression
        result = self.exec.execute(tc)
        self.assertTrue(result.is_error)
        self.assertIn("参数校验失败", result.output)

    def test_execute_wrong_type_param(self):
        """参数类型错误"""
        tc = ToolCall(id="c5", name="calculator", arguments={"expression": 123})
        result = self.exec.execute(tc)
        self.assertTrue(result.is_error)
        self.assertIn("参数", result.output)

    def test_execute_timeout(self):
        """工具执行超时"""
        # 注册一个会 sleep 的工具
        def slow_handler(params):
            time.sleep(5)
            return "done"

        schema = ToolSchema(properties={}, required=[])
        self.reg.register(Tool(name="slow", description="慢工具", parameters=schema, handler=slow_handler))
        tc = ToolCall(id="c6", name="slow", arguments={})
        result = self.exec.execute(tc, timeout=0.5)
        self.assertTrue(result.is_error)
        self.assertIn("超时", result.output)

    def test_execute_exception_isolation(self):
        """工具异常不应中断执行器"""
        def bad_handler(params):
            raise ValueError("boom")

        schema = ToolSchema(properties={}, required=[])
        self.reg.register(Tool(name="bad", description="坏工具", parameters=schema, handler=bad_handler))
        tc = ToolCall(id="c7", name="bad", arguments={})
        result = self.exec.execute(tc)
        self.assertTrue(result.is_error)
        self.assertIn("boom", result.output)

    def test_execute_batch(self):
        """批量执行"""
        tc1 = ToolCall(id="b1", name="get_time", arguments={})
        tc2 = ToolCall(id="b2", name="get_date", arguments={})
        results = self.exec.execute_batch([tc1, tc2])
        self.assertEqual(len(results), 2)
        self.assertFalse(results[0].is_error)
        self.assertFalse(results[1].is_error)

    def test_output_truncation(self):
        """超长输出截断"""
        def long_handler(params):
            return "x" * 10000

        schema = ToolSchema(properties={}, required=[])
        self.reg.register(Tool(name="long", description="长输出", parameters=schema, handler=long_handler))
        tc = ToolCall(id="c8", name="long", arguments={})
        result = self.exec.execute(tc)
        self.assertFalse(result.is_error)
        self.assertIn("已截断", result.output)


if __name__ == "__main__":
    unittest.main(verbosity=2)
