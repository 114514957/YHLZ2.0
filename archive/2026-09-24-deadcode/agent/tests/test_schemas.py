"""
测试: schemas.py 数据模型
覆盖: Message / Tool / ToolCall / Plan / AgentResult
"""
from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from backend.agent.schemas import (
    AgentResult, AgentStep, Message, Plan, PlanStep,
    Tool, ToolCall, ToolResult, ToolSchema,
)


class TestMessage(unittest.TestCase):
    """Message 数据模型"""

    def test_system_message(self):
        m = Message.system("hello")
        self.assertEqual(m.role, "system")
        self.assertEqual(m.content, "hello")

    def test_user_message(self):
        m = Message.user("hi")
        self.assertEqual(m.role, "user")
        self.assertEqual(m.content, "hi")

    def test_assistant_with_tool_calls(self):
        tc = ToolCall(id="c1", name="get_time", arguments={})
        m = Message.assistant(content=None, tool_calls=[tc])
        self.assertEqual(m.role, "assistant")
        self.assertIsNone(m.content)
        self.assertEqual(len(m.tool_calls), 1)

    def test_tool_message(self):
        m = Message.tool(content="result", tool_call_id="c1", name="get_time")
        self.assertEqual(m.role, "tool")
        self.assertEqual(m.tool_call_id, "c1")
        self.assertEqual(m.name, "get_time")

    def test_to_openai_dict(self):
        m = Message.system("hi")
        d = m.to_openai_dict()
        self.assertEqual(d, {"role": "system", "content": "hi"})

    def test_to_openai_dict_with_tool_calls(self):
        tc = ToolCall(id="c1", name="get_time", arguments={}, raw_arguments="{}")
        m = Message.assistant(content=None, tool_calls=[tc])
        d = m.to_openai_dict()
        self.assertIn("tool_calls", d)
        self.assertEqual(d["tool_calls"][0]["id"], "c1")


class TestToolCall(unittest.TestCase):
    """ToolCall 解析"""

    def test_from_openai_dict(self):
        d = {
            "id": "call_abc",
            "type": "function",
            "function": {"name": "get_time", "arguments": '{"format": "%Y"}'},
        }
        tc = ToolCall.from_openai_dict(d)
        self.assertEqual(tc.id, "call_abc")
        self.assertEqual(tc.name, "get_time")
        self.assertEqual(tc.arguments, {"format": "%Y"})

    def test_from_openai_dict_invalid_json(self):
        d = {
            "id": "call_x",
            "type": "function",
            "function": {"name": "calc", "arguments": "not json"},
        }
        tc = ToolCall.from_openai_dict(d)
        self.assertEqual(tc.arguments, {})  # 解析失败返回空 dict

    def test_to_openai_dict(self):
        tc = ToolCall(id="c1", name="get_time", arguments={"format": "%Y"},
                      raw_arguments='{"format": "%Y"}')
        d = tc.to_openai_dict()
        self.assertEqual(d["id"], "c1")
        self.assertEqual(d["function"]["name"], "get_time")


class TestTool(unittest.TestCase):
    """Tool 定义"""

    def test_tool_to_openai_dict(self):
        schema = ToolSchema(
            type="object",
            properties={"expr": {"type": "string"}},
            required=["expr"],
        )
        tool = Tool(name="calc", description="计算器", parameters=schema, handler=lambda p: "")
        d = tool.to_openai_dict()
        self.assertEqual(d["type"], "function")
        self.assertEqual(d["function"]["name"], "calc")
        self.assertEqual(d["function"]["parameters"]["required"], ["expr"])


class TestPlan(unittest.TestCase):
    """Plan / PlanStep"""

    def test_plan_create(self):
        plan = Plan.create(goal="test", step_descs=["step1", "step2"])
        self.assertEqual(plan.goal, "test")
        self.assertEqual(len(plan.steps), 2)
        self.assertEqual(plan.steps[0].id, "step_1")
        self.assertEqual(plan.steps[0].description, "step1")
        self.assertEqual(plan.steps[0].status, "pending")

    def test_plan_step_default(self):
        s = PlanStep(id="s1", description="do something")
        self.assertEqual(s.status, "pending")
        self.assertIsNone(s.tool)


class TestAgentResult(unittest.TestCase):
    """AgentResult"""

    def test_default(self):
        r = AgentResult()
        self.assertTrue(r.success)
        self.assertEqual(r.answer, "")
        self.assertEqual(r.iterations, 0)
        self.assertEqual(r.steps, [])

    def test_to_dict(self):
        r = AgentResult(answer="hello", iterations=1)
        d = r.to_dict()
        self.assertEqual(d["answer"], "hello")
        self.assertEqual(d["iterations"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
