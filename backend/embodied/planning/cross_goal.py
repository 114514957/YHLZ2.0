"""
YHLZ Embodied AI V4.6 - 跨目标规划器 (Cross-Goal Planner)

职责:
    - 分组: 相同 scene × goal_type × action_sequence → 目标组 (批量规划)
    - 排序: 组间/组内按优先级 + 策略质量排序 (可解释)
    - 预算分配: 跨目标 max_steps 统筹 (预算分配器)
    - 战略规划: 输出完整规划 (组 → 共享步骤 → 预算 → 执行顺序)

核心数据模型:
    CrossGoalPlan:
    {
        plan_id, goals, groups, shared_steps, budget_allocation,
        explainable_reason, mode: "rule_based"
    }

设计原则:
    - 规划只读策略/目标, 输出规划方案 (执行仍走 Service.run_goal / Permission)
    - 纯规则 + 统计 + 阈值: 禁止黑盒优化
    - 规划动作只影响审计日志 (追踪) + 规划结果 (不写 Agent Memory)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import uuid
from typing import Any, Dict, List, Optional

from backend.embodied.experience.policy import PolicyTable
from backend.embodied.planning.budget import BudgetAllocator, BudgetError
from backend.embodied.planning.dependency import (
    DependencyError,
    GoalDependencyAnalyzer,
    plan_action_sequence,
)
from backend.embodied.schema import EmbodiedGoal
from backend.embodied.strategy.audit import PolicyAuditLog

logger = logging.getLogger(__name__)


class CrossGoalError(Exception):
    """跨目标规划操作异常"""


# 组间排序权重 (可解释): 优先级为主, 组大小为辅
GROUP_PRIORITY_ORDER = {"high": 3, "medium": 2, "low": 1}


class CrossGoalPlanner:
    """跨目标规划器 (分组 → 排序 → 预算 → 战略规划)

    用法:
        planner = CrossGoalPlanner(
            table=table, audit=audit,
            max_budget=100, min_group_size=2,
        )
        plan = planner.plan(goals)
        groups = planner.analyze_groups(goals)
        budget = planner.allocate_budget(goals)
    """

    def __init__(
        self,
        table: Optional[PolicyTable] = None,
        audit: Optional[PolicyAuditLog] = None,
        max_budget: int = 100,
        min_group_size: int = 2,
        min_archive_hit_rate: float = 0.5,
    ):
        self._lock = threading.RLock()
        self._table = table
        self._audit = audit
        self._analyzer = GoalDependencyAnalyzer(min_group_size=min_group_size)
        self._allocator = BudgetAllocator(
            max_budget=max_budget,
            quality_bonus_threshold=min_archive_hit_rate,
        )
        self._min_group_size = min_group_size

    # ── 策略质量查询 (供预算分配) ─────────────────────────────────
    def _quality_for_goal(self, goal: EmbodiedGoal) -> float:
        """目标最优策略质量 (hit_rate): 同场景×goal_type 最优 active 策略"""
        if self._table is None:
            return 0.0
        seq = plan_action_sequence(goal)
        action_type = seq[0]["action_type"] if seq else ""
        candidates = self._table.candidates(
            action_type=action_type or None,
            scene=goal.scene or None,
            goal_type=goal.intent or None,
        )
        best = max((p.hit_rate for p in candidates), default=0.0)
        return best

    def _quality_map(self, goals: List[EmbodiedGoal]) -> Dict[str, float]:
        return {g.goal_id: self._quality_for_goal(g) for g in goals}

    # ── 分组 + 排序 ───────────────────────────────────────────────
    def analyze_groups(self, goals: List[EmbodiedGoal]) -> Dict[str, Any]:
        """目标分组分析 (经规划器, 带排序)"""
        with self._lock:
            result = self._analyzer.analyze_groups(
                goals, min_group_size=self._min_group_size,
            )
        # 组间排序: 组内最高优先级 → 组大小 (可解释)
        groups = result["groups"]
        def group_priority(g):
            priorities = [m.get("priority", "medium") for m in g.get("goals", [])]
            return max(GROUP_PRIORITY_ORDER.get(p, 2) for p in priorities)
        groups.sort(key=lambda g: (group_priority(g), g["member_count"]),
                    reverse=True)
        result["groups"] = groups
        result["rule"] = (
            "相同 scene×goal_type×action_sequence → 目标组; "
            "组间按优先级 + 组大小排序 (可解释)"
        )
        return result

    # ── 共享步骤 ──────────────────────────────────────────────────
    def shared_steps(self, groups: Dict[str, Any]) -> Dict[str, Any]:
        """共享步骤识别 (一次 scan 服务多目标)"""
        return self._analyzer.shared_steps(groups)

    # ── 预算 ──────────────────────────────────────────────────────
    def allocate_budget(
        self,
        goals: List[EmbodiedGoal],
        groups: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """跨目标预算分配 (策略质量 + 优先级 + 共享节省)"""
        with self._lock:
            groups = groups or self.analyze_groups(goals)
            shared = self._analyzer.shared_steps(groups)
            # 共享节省 → 按组内成员均摊 (每成员减 saved/members 步)
            saved_by_goal: Dict[str, int] = {}
            for s in shared.get("shared_steps", []):
                per_member = max(0, s["saved_steps"] // max(1, s["member_count"]))
                for gid in s.get("goal_ids", []):
                    saved_by_goal[gid] = saved_by_goal.get(gid, 0) + per_member
            sequences = {}
            for g in groups.get("groups", []):
                for goal_dict in g.get("goals", []):
                    sequences[goal_dict["goal_id"]] = len(
                        g.get("action_sequence", [])
                    )
            demands = self._allocator.demands(
                goals, sequences=sequences, shared_saved=saved_by_goal,
            )
            quality = self._quality_map(goals)
            return self._allocator.allocate(
                goals, demands=demands, strategy_quality=quality,
            )

    # ── 规划主入口 ────────────────────────────────────────────────
    def plan(
        self,
        goals: List[EmbodiedGoal],
        budget: Optional[int] = None,
        record_audit: bool = True,
    ) -> Dict[str, Any]:
        """跨目标战略规划主入口

        Args:
            goals: 目标列表 (>= 1)
            budget: 总步骤预算 (None=默认 max_budget)
            record_audit: 是否记录规划审计 (默认 True)

        Returns:
            CrossGoalPlan:
            {
                'plan_id', 'goals', 'groups', 'shared_steps',
                'budget_allocation', 'explainable_reason',
                'mode': 'rule_based',
            }

        Raises:
            CrossGoalError: 目标列表为空 / 非法目标
        """
        if not goals:
            raise CrossGoalError("目标列表不能为空 (cross_goal_plan 需要 >= 1 个目标)")
        for g in goals:
            if g is None or not g.goal_id:
                raise CrossGoalError(f"非法目标: {g}")
        with self._lock:
            allocator = self._allocator
            if budget is not None:
                if budget <= 0:
                    raise CrossGoalError(f"budget 必须 > 0, 当前: {budget}")
                allocator = BudgetAllocator(
                    max_budget=budget,
                    quality_bonus_threshold=allocator._quality_bonus_threshold,
                )
            groups = self.analyze_groups(goals)
            shared = self.shared_steps(groups)
            saved_by_goal: Dict[str, int] = {}
            for s in shared.get("shared_steps", []):
                # 共享节省 (members-1) 步均摊到组内成员, 余数按序分配
                gids = list(s.get("goal_ids", []))
                per_member = s["saved_steps"] // max(1, len(gids))
                remainder = s["saved_steps"] % max(1, len(gids))
                for i, gid in enumerate(gids):
                    saved_by_goal[gid] = (
                        saved_by_goal.get(gid, 0) + per_member
                        + (1 if i < remainder else 0)
                    )
            sequences = {}
            for g in groups.get("groups", []):
                for goal_dict in g.get("goals", []):
                    sequences[goal_dict["goal_id"]] = len(
                        g.get("action_sequence", [])
                    )
            demands = allocator.demands(
                goals, sequences=sequences, shared_saved=saved_by_goal,
            )
            quality = self._quality_map(goals)
            allocation = allocator.allocate(
                goals, demands=demands, strategy_quality=quality,
            )
            reason_lines = self._build_reason(
                goals, groups, shared, allocation,
            )
            plan_id = "plan_" + uuid.uuid4().hex[:8]
            plan = {
                "plan_id": plan_id,
                "goals": [g.to_dict() for g in goals],
                "groups": groups,
                "shared_steps": shared,
                "budget_allocation": allocation,
                "explainable_reason": "\n".join(reason_lines),
                "mode": "rule_based",
            }
            if record_audit and self._audit is not None:
                self._audit.record(
                    trigger="cross_goal_plan",
                    action="cross_goal",
                    applied=True,
                    goal_id=",".join(g.goal_id for g in goals[:10]),
                    kind="planning",
                    scene=",".join(sorted({g.scene or "*" for g in goals})),
                    reason=(
                        f"跨目标规划: {len(goals)} 个目标, "
                        f"{len(groups.get('groups', []))} 组, "
                        f"共享节省 {shared.get('total_saved', 0)} 步, "
                        f"预算分配 {allocation.get('total_allocated', 0)}/{budget or self._allocator._max_budget}"
                    ),
                )
            return plan

    # ── 可解释原因 ────────────────────────────────────────────────
    @staticmethod
    def _build_reason(
        goals: List[EmbodiedGoal],
        groups: Dict[str, Any],
        shared: Dict[str, Any],
        allocation: Dict[str, Any],
    ) -> List[str]:
        lines = [
            f"跨目标战略规划 (rule_based): 共 {len(goals)} 个目标, "
            f"形成 {len(groups.get('groups', []))} 个目标组",
        ]
        for g in groups.get("groups", []):
            marker = "可批量" if g["batch_plan"] else "独立"
            lines.append(
                f"  [组 {g['group_id']}] scene={g['scene']} "
                f"goal_type={g['goal_type']} 动作序列={g['action_sequence']} "
                f"{g['member_count']} 个目标 ({marker})"
            )
        for s in shared.get("shared_steps", []):
            lines.append(f"  [共享步骤] {s['reason']}")
        c = allocation.get("conflict", {})
        if c.get("conflict"):
            lines.append(
                f"  [预算冲突] 需求 {c['total_demand']} > 预算 {c['budget']}, "
                f"缺口 {c['deficit']}, 建议降级低优先级目标"
            )
        for a in allocation.get("allocations", []):
            lines.append(f"  [预算] 目标 {a['goal_id']}: {a['reason']}")
        return lines


__all__ = [
    "CrossGoalError",
    "CrossGoalPlanner",
    "GROUP_PRIORITY_ORDER",
]
