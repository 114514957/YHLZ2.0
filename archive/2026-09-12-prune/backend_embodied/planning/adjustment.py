"""
YHLZ Embodied AI V4.7 - 计划调整与风险评估 (Plan Adjustment & Risk)

职责:
    - adjust_plan(goal_id): 长期任务调整 (失败次数增加 / 资源不足 / 时间变化 /
      环境变化触发)
    - 输出: 新 milestone 顺序 / 优先级 / 建议 (禁止自动执行, 必须经 Permission)
    - 风险预测: 根据历史失败经验 → low / medium / high (P1)
    - 时间规划: deadline / estimated_duration / time_window (P1)

设计原则:
    - 调整只输出方案 (不修改执行状态, 不自动执行)
    - 纯规则 + 阈值: 禁止黑盒优化
    - 可解释: 每个建议带 reason
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List, Optional

from backend.embodied.planning.milestone import LongGoal, LongHorizonError
from backend.embodied.planning.progress_tracker import ProgressTracker

logger = logging.getLogger(__name__)


class AdjustmentError(Exception):
    """计划调整操作异常"""


# 调整触发条件 (可解释规则)
ADJUSTMENT_TRIGGERS: List[str] = [
    "failure_increase",   # 失败次数增加
    "resource_shortage",  # 资源不足
    "time_change",        # 时间变化
    "environment_change", # 环境变化
]

# 风险等级阈值 (规则)
RISK_LEVELS: List[str] = ["low", "medium", "high"]


class PlanAdjuster:
    """计划调整器 (规则驱动, 只输出方案)

    用法:
        adjuster = PlanAdjuster()
        result = adjuster.adjust_plan(goal, trigger="failure_increase", reason=...)
        risk = adjuster.predict_risk(goal, failure_history=...)
        timing = adjuster.time_plan(goal, now=...)
    """

    def __init__(
        self,
        progress_tracker: Optional[ProgressTracker] = None,
        risk_failure_threshold: int = 3,
        risk_blocked_threshold: int = 2,
        deadline_warning_hours: float = 24.0,
    ):
        self._lock = threading.RLock()
        self._tracker = progress_tracker or ProgressTracker()
        self._risk_failure_threshold = risk_failure_threshold
        self._risk_blocked_threshold = risk_blocked_threshold
        self._deadline_warning_hours = deadline_warning_hours

    # ── 计划调整 ──────────────────────────────────────────────────
    def adjust_plan(
        self,
        goal: LongGoal,
        trigger: str = "time_change",
        reason: str = "",
        resource_factor: float = 1.0,
    ) -> Dict[str, Any]:
        """计划调整: 新 milestone 顺序 / 优先级 / 建议

        Args:
            goal: 长期目标
            trigger: 触发条件 (failure_increase / resource_shortage /
                     time_change / environment_change)
            reason: 调整原因 (可解释)
            resource_factor: 资源缩减因子 (0.0~1.0, 资源不足时)

        Returns:
            {
                'goal_id', 'trigger', 'rule',
                'adjusted': bool,
                'suggested_order': [...],      # 新里程碑顺序
                'priority_adjustments': [...], # 优先级调整建议
                'suggestions': [...],          # 建议列表
                'permission_required': True,   # 执行必须经 Permission
            }
        """
        with self._lock:
            if trigger not in ADJUSTMENT_TRIGGERS:
                raise AdjustmentError(
                    f"非法调整触发条件: {trigger} (可选: {ADJUSTMENT_TRIGGERS})"
                )
            if goal is None:
                raise AdjustmentError("目标不能为空")
            blocked = self._tracker._graph.compute_blocked(goal)
            blocked_ids = set(blocked)
            done_ids = {m.milestone_id for m in goal.milestones
                        if m.status == "completed"}

            # 1. 新顺序: 完成优先, 阻塞后移, 其余按原顺序
            remaining = [
                m for m in sorted(goal.milestones, key=lambda x: x.order)
                if m.milestone_id not in done_ids
            ]
            ordered = []
            # 先排不阻塞的
            for m in remaining:
                if m.milestone_id not in blocked_ids:
                    ordered.append(m)
            # 再排阻塞的 (建议先解除依赖)
            for m in remaining:
                if m.milestone_id in blocked_ids:
                    ordered.append(m)

            suggested_order = [
                {"milestone_id": m.milestone_id, "title": m.title,
                 "order": i}
                for i, m in enumerate(ordered)
            ]

            # 2. 优先级调整 (资源不足 → 高优先级后移? 不, 高优先级保留)
            priority_adjustments: List[Dict[str, Any]] = []
            if trigger == "resource_shortage":
                # 资源不足: 保留高优先级, 低优先级延后 (可解释)
                low = [m for m in ordered
                       if m.milestone_id in self._low_priority_ids(goal)]
                priority_adjustments = [
                    {"milestone_id": m.milestone_id, "title": m.title,
                     "suggestion": "延后执行 (低优先级, 资源不足)"}
                    for m in low
                ]

            # 3. 建议 (可解释)
            suggestions: List[str] = [
                f"触发条件: {trigger} ({reason or '无原因说明'})"
            ]
            if trigger == "failure_increase":
                suggestions.append(
                    "失败次数增加: 建议先完成前置里程碑, 或降低失败里程碑优先级"
                )
            elif trigger == "resource_shortage":
                factor = max(0.1, min(1.0, resource_factor))
                suggestions.append(
                    f"资源不足 (因子 {factor}): 建议减少并行里程碑数量, "
                    f"集中完成高优先级"
                )
            elif trigger == "time_change":
                suggestions.append(
                    "时间变化: 建议优先完成 deadline 临近的里程碑"
                )
            elif trigger == "environment_change":
                suggestions.append(
                    "环境变化: 建议重新观察环境后调整里程碑内容"
                )

            return {
                "goal_id": goal.goal_id,
                "trigger": trigger,
                "rule": "失败/资源/时间/环境变化 → 重排顺序 + 优先级建议",
                "adjusted": True,
                "suggested_order": suggested_order,
                "priority_adjustments": priority_adjustments,
                "suggestions": suggestions,
                "permission_required": True,
                "blocked_milestones": blocked,
            }

    def _low_priority_ids(self, goal: LongGoal) -> List[str]:
        """低优先级里程碑 ID (供资源不足调整)"""
        # 简化规则: order 靠后的里程碑视为较低优先级
        sorted_m = sorted(goal.milestones, key=lambda x: x.order)
        half = len(sorted_m) // 2
        return [m.milestone_id for m in sorted_m[half:]]

    # ── 风险预测 (P1) ─────────────────────────────────────────────
    def predict_risk(
        self,
        goal: LongGoal,
        failure_history: Optional[Dict[str, int]] = None,
    ) -> Dict[str, Any]:
        """风险预测 (根据历史失败经验)

        规则 (可解释):
            - 历史失败次数 >= 阈值 → 对应里程碑风险 high
            - 被阻塞里程碑 → 风险 medium
            - 其余 → low
            - 整体风险 = 最高里程碑风险

        Args:
            goal: 长期目标
            failure_history: milestone_id → 失败次数 (来自 Experience Memory)

        Returns:
            {
                'goal_id', 'rule', 'overall': 'low|medium|high',
                'per_milestone': [
                    {'milestone_id', 'title', 'risk', 'reason'}, ...
                ],
            }
        """
        with self._lock:
            history = failure_history or {}
            blocked_ids = set(self._tracker._graph.compute_blocked(goal))
            per: List[Dict[str, Any]] = []
            for m in sorted(goal.milestones, key=lambda x: x.order):
                fails = history.get(m.milestone_id, 0)
                if fails >= self._risk_failure_threshold:
                    risk, why = "high", (
                        f"历史失败 {fails} 次 >= 阈值 {self._risk_failure_threshold}"
                    )
                elif m.milestone_id in blocked_ids:
                    risk, why = "medium", "被前置里程碑阻塞"
                else:
                    risk, why = "low", "无历史失败, 无阻塞"
                per.append({
                    "milestone_id": m.milestone_id,
                    "title": m.title,
                    "risk": risk,
                    "reason": why,
                })
            levels = {"low": 0, "medium": 1, "high": 2}
            overall = max(per, key=lambda x: levels[x["risk"]])["risk"] \
                if per else "low"
            return {
                "goal_id": goal.goal_id,
                "rule": "历史失败次数/阻塞 → 风险等级",
                "overall": overall,
                "per_milestone": per,
            }

    # ── 时间规划 (P1) ─────────────────────────────────────────────
    def time_plan(
        self,
        goal: LongGoal,
        now: Optional[float] = None,
    ) -> Dict[str, Any]:
        """时间规划: deadline / estimated_duration / time_window

        Returns:
            {
                'goal_id', 'deadline', 'now',
                'estimated_total_minutes': n,
                'time_window': {'start', 'end', 'remaining_hours'},
                'deadline_status': 'on_schedule'|'warning'|'overdue',
                'warning': bool,
            }
        """
        with self._lock:
            now = now if now is not None else time.time()
            total_min = sum(
                m.estimated_duration for m in goal.milestones
            )
            remaining_hours = 0.0
            deadline_status = "no_deadline"
            warning = False
            if goal.deadline > 0:
                remaining_hours = max(0.0, (goal.deadline - now) / 3600.0)
                if remaining_hours <= 0:
                    deadline_status = "overdue"
                elif remaining_hours <= self._deadline_warning_hours:
                    deadline_status = "warning"
                    warning = True
                else:
                    deadline_status = "on_schedule"
            return {
                "goal_id": goal.goal_id,
                "deadline": goal.deadline,
                "now": now,
                "estimated_total_minutes": total_min,
                "time_window": {
                    "start": goal.created_at,
                    "end": goal.deadline if goal.deadline > 0 else None,
                    "remaining_hours": round(remaining_hours, 2),
                },
                "deadline_status": deadline_status,
                "warning": warning,
            }


__all__ = [
    "ADJUSTMENT_TRIGGERS",
    "AdjustmentError",
    "PlanAdjuster",
    "RISK_LEVELS",
]
