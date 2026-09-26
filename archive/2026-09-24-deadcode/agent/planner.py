"""
YHLZ Agent Core V3.0 - 任务规划器

职责:
    - 将用户目标分解为可执行步骤 (Plan)
    - 基于可用工具推断步骤
    - 支持静态规划 (一次性生成) 和动态规划 (执行中追加)
    - Mock 模式: 规则驱动, 测试可运行

设计:
    - 不强制要求 LLM 生成复杂计划 (避免过度工程)
    - 简单查询返回单步计划
    - 复杂任务可调用 LLM 分解 (可选)
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from backend.agent.schemas import Message, Plan, PlanStep
from backend.agent.tool_registry import ToolRegistry, get_registry

logger = logging.getLogger(__name__)


class PlannerError(Exception):
    """规划器错误"""


class Planner:
    """任务规划器

    用法:
        planner = Planner()
        plan = planner.plan("现在几点", tools_schema)
        for step in plan.steps:
            ...
    """

    def __init__(
        self,
        registry: Optional[ToolRegistry] = None,
        llm_adapter: Optional[Any] = None,
    ):
        self._registry = registry or get_registry()
        self._llm = llm_adapter

    def plan(self, goal: str, available_tools: Optional[List[str]] = None) -> Plan:
        """生成执行计划

        Args:
            goal: 用户目标
            available_tools: 可用工具名列表 (None=全部)
        """
        # 规则驱动的静态规划 (无需 LLM)
        return self._rule_based_plan(goal, available_tools)

    async def plan_async(self, goal: str, available_tools: Optional[List[str]] = None) -> Plan:
        """异步生成计划 (可调用 LLM)"""
        if self._llm is None:
            return self.plan(goal, available_tools)

        # 尝试 LLM 规划
        try:
            return await self._llm_plan(goal, available_tools)
        except Exception as e:
            logger.warning(f"LLM 规划失败, 退化为规则规划: {e}")
            return self.plan(goal, available_tools)

    def _rule_based_plan(self, goal: str, available_tools: Optional[List[str]] = None) -> Plan:
        """规则驱动规划

        规则:
            - 含时间/几点 → 单步 get_time
            - 含日期/几号 → 单步 get_date
            - 含计算/等于/算式 → 单步 calculator
            - 含 http/网页 → 单步 http_get
            - 其他 → 单步 "直接回答" (无工具)
        """
        goal_lower = goal.lower()
        steps: List[str] = []

        # 检查可用工具
        tool_names = available_tools or self._registry.list_names()

        if any(k in goal for k in ["时间", "几点", "现在几点"]) and "get_time" in tool_names:
            steps.append("调用 get_time 获取当前时间")
        elif any(k in goal for k in ["日期", "几号", "今天"]) and "get_date" in tool_names:
            steps.append("调用 get_date 获取当前日期")
        elif any(k in goal for k in ["计算", "等于", "多少"]) and "calculator" in tool_names:
            steps.append("调用 calculator 计算表达式")
        elif any(k in goal_lower for k in ["http", "网页", "url"]) and "http_get" in tool_names:
            steps.append("调用 http_get 获取网页内容")
        else:
            steps.append("直接根据知识回答用户问题")

        plan = Plan.create(goal=goal, step_descs=steps)
        # 标注预期工具
        for s in plan.steps:
            for tn in tool_names:
                if tn in s.description:
                    s.tool = tn
                    break
        logger.info(f"规划完成: goal='{goal}', steps={len(plan.steps)}")
        return plan

    async def _llm_plan(self, goal: str, available_tools: Optional[List[str]] = None) -> Plan:
        """LLM 驱动规划 (复杂任务)"""
        if self._llm is None:
            return self._rule_based_plan(goal, available_tools)

        tool_names = available_tools or self._registry.list_names()
        tools_desc = "\n".join(
            f"- {n}: {self._registry.get(n).description}"
            for n in tool_names if self._registry.get(n)
        )

        prompt = f"""你是任务规划助手。请将用户目标分解为 1-5 个步骤, 每步一句话。

可用工具:
{tools_desc}

用户目标: {goal}

输出 JSON 数组, 每项 {{"description": "步骤描述", "tool": "工具名或null"}}, 不要其他文字。
如果不需要工具, 输出 [{{"description": "直接回答用户问题", "tool": null}}]。"""

        messages = [Message.user(prompt)]
        text = await self._llm.generate(messages, temperature=0.3, max_tokens=512)

        # 解析 JSON
        try:
            # 去除可能的 markdown 代码块
            text = text.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            steps_data = json.loads(text)
            step_descs = [s.get("description", "") for s in steps_data if isinstance(s, dict)]
            if not step_descs:
                return self._rule_based_plan(goal, available_tools)

            plan = Plan.create(goal=goal, step_descs=step_descs)
            for i, s in enumerate(steps_data):
                if i < len(plan.steps) and isinstance(s, dict):
                    tool = s.get("tool")
                    if tool and tool in tool_names:
                        plan.steps[i].tool = tool
            return plan
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"LLM 规划输出解析失败: {e}, 退化为规则规划")
            return self._rule_based_plan(goal, available_tools)

    def update_step_status(
        self, plan: Plan, step_id: str, status: str, result: Optional[str] = None
    ) -> None:
        """更新步骤状态"""
        for s in plan.steps:
            if s.id == step_id:
                s.status = status
                if result is not None:
                    s.result = result
                break


__all__ = ["Planner", "PlannerError"]
