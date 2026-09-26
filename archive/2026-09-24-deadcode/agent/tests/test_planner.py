"""
测试: planner.py 任务规划器
覆盖: 规则驱动规划 / LLM 规划退化
"""
from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from backend.agent.planner import Planner
from backend.agent.tool_registry import get_registry, reset_registry


class TestPlanner(unittest.TestCase):

    def setUp(self):
        reset_registry()
        self.reg = get_registry()
        self.planner = Planner(registry=self.reg, llm_adapter=None)

    def tearDown(self):
        reset_registry()

    def test_plan_time_query(self):
        """时间查询 → 单步 get_time"""
        plan = self.planner.plan("现在几点")
        self.assertEqual(len(plan.steps), 1)
        self.assertEqual(plan.steps[0].tool, "get_time")

    def test_plan_date_query(self):
        """日期查询 → 单步 get_date"""
        plan = self.planner.plan("今天几号")
        self.assertEqual(len(plan.steps), 1)
        self.assertEqual(plan.steps[0].tool, "get_date")

    def test_plan_calculator_query(self):
        """计算查询 → 单步 calculator"""
        plan = self.planner.plan("计算 1+2 等于多少")
        self.assertEqual(len(plan.steps), 1)
        self.assertEqual(plan.steps[0].tool, "calculator")

    def test_plan_general_query(self):
        """普通查询 → 单步直接回答"""
        plan = self.planner.plan("写一首诗")
        self.assertEqual(len(plan.steps), 1)
        self.assertIsNone(plan.steps[0].tool)

    def test_plan_with_restricted_tools(self):
        """限定可用工具"""
        plan = self.planner.plan("现在几点", available_tools=["get_date"])
        # get_time 不在 available_tools 中, 退化为直接回答
        self.assertIsNone(plan.steps[0].tool)

    def test_plan_async_without_llm(self):
        """异步规划 (无 LLM) → 退化为规则"""
        async def run():
            plan = await self.planner.plan_async("几点")
            self.assertEqual(len(plan.steps), 1)
        asyncio.run(run())

    def test_plan_async_with_mock_llm(self):
        """异步规划 + Mock LLM"""
        from backend.agent.llm_adapter import MockLLMAdapter
        planner = Planner(registry=self.reg, llm_adapter=MockLLMAdapter())

        async def run():
            plan = await planner.plan_async("帮我查时间然后告诉我")
            self.assertGreater(len(plan.steps), 0)
        asyncio.run(run())

    def test_update_step_status(self):
        """更新步骤状态"""
        plan = self.planner.plan("几点")
        step_id = plan.steps[0].id
        self.planner.update_step_status(plan, step_id, "done", "result")
        self.assertEqual(plan.steps[0].status, "done")
        self.assertEqual(plan.steps[0].result, "result")


if __name__ == "__main__":
    unittest.main(verbosity=2)
