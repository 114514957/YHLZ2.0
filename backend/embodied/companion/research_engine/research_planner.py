"""
YHLZ Embodied AI V9.0 - 研究计划器 (Research Planner)

职责:
    - 问题拆解
    - 资源规划
    - 验证路径设计
    - 成本评估

设计原则:
    - 纯规则计划 (可解释)
    - 计划含验证路径 (可审计)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class PlannerError(Exception):
    """研究计划操作异常"""


# 成本等级 (可解释)
COST_LEVELS: list = ["low", "medium", "high"]

# 资源类型 (可解释)
RESOURCE_TYPES: list = ["local", "user_authorized",
                        "cloud", "tool"]


class ResearchPlanner:
    """研究计划器 (问题 → 计划)

    用法:
        planner = ResearchPlanner()
        plan = planner.plan(question)
    """

    def __init__(self, enabled: bool = True,
                 max_steps: int = 5):
        if max_steps <= 0:
            raise PlannerError(
                f"max_steps 必须 > 0, 当前: {max_steps}"
            )
        self._lock = threading.RLock()
        self._enabled = bool(enabled)
        self._max_steps = int(max_steps)
        self._plans: list = []

    # ── 计划主入口 ───────────────────────────────────────────────
    def plan(
        self,
        question: str,
        importance: float = 0.5,
        now: Optional[float] = None,
    ) -> Dict[str, Any]:
        """制定研究计划

        Args:
            question: 问题
            importance: 重要性 (0~1)

        Returns:
            {
                'plan_id', 'question', 'steps', 'resources',
                'verification_path', 'estimated_cost', 'mode',
            }
        """
        with self._lock:
            now = now if now is not None else time.time()
            if not self._enabled:
                return {
                    "mode": "error_frame",
                    "ok": False,
                    "reason": "研究计划器停用",
                }
            steps = self._decompose(question)
            resources = self._plan_resources(importance)
            verification = self._verification_path(steps)
            cost = self._estimate_cost(importance, steps)
            plan = {
                "plan_id": "rp_" + uuid.uuid4().hex[:8],
                "question": str(question),
                "steps": steps,
                "resources": resources,
                "verification_path": verification,
                "estimated_cost": cost,
                "mode": "rule_based",
                "created_at": now,
            }
            self._plans.append(plan)
            return dict(plan)

    # ── 子步骤 (可解释) ─────────────────────────────────────────
    def _decompose(self, question: str) -> List[Dict[str, Any]]:
        """问题拆解"""
        steps = [
            {
                "step": 1,
                "action": f"收集与 '{question[:20]}' "
                          f"相关的既有知识",
                "method": "knowledge_acquisition",
            },
            {
                "step": 2,
                "action": "构建候选假设",
                "method": "hypothesis_loop",
            },
            {
                "step": 3,
                "action": "分析假设与证据",
                "method": "analysis",
            },
            {
                "step": 4,
                "action": "验证结果",
                "method": "validation",
            },
        ]
        return steps[:self._max_steps]

    @staticmethod
    def _plan_resources(importance: float) -> List[str]:
        """资源规划 (按重要性)"""
        if importance >= 0.8:
            return ["local", "user_authorized", "cloud",
                    "tool"]
        if importance >= 0.5:
            return ["local", "user_authorized", "cloud"]
        return ["local", "user_authorized"]

    @staticmethod
    def _verification_path(steps: list) -> List[str]:
        """验证路径"""
        return [
            f"步骤 {s['step']}: {s['method']}"
            for s in steps
        ]

    @staticmethod
    def _estimate_cost(importance: float,
                       steps: list) -> str:
        """成本评估 (按重要性, 低价值低成本)"""
        if importance >= 0.8:
            return "high"
        if importance >= 0.5:
            return "medium"
        return "low"

    # ── 查询 ─────────────────────────────────────────────────────
    def stats(self) -> Dict[str, Any]:
        """计划统计"""
        with self._lock:
            return {
                "mode": "rule_based",
                "enabled": self._enabled,
                "plan_count": len(self._plans),
                "cost_levels": list(COST_LEVELS),
                "resource_types": list(RESOURCE_TYPES),
            }

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = len(self._plans)
            self._plans.clear()
            return n


__all__ = [
    "COST_LEVELS",
    "PlannerError",
    "RESOURCE_TYPES",
    "ResearchPlanner",
]
