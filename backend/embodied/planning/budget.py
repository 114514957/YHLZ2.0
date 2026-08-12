"""
YHLZ Embodied AI V4.6 - 跨目标步骤预算分配 (Cross-Goal Budget Allocation)

职责:
    - 预算分配: 跨目标 max_steps 统筹 (策略质量 + 优先级 + 资源限制)
    - 可解释分配: 每个目标获得预算 + 原因 (规则 + 权重)
    - 预算冲突检测: 总需求 > 预算 → 输出降级建议 (P1)

核心规则 (可解释, 纯规则):
    - 基础预算: 每个目标按其计划动作序列长度 + max_steps 约束计算
    - 优先级加成: high > medium > low (默认权重 1.0 / 1.5 / 2.0)
    - 策略质量加成: 有高质量策略 (hit_rate >= 阈值) 的目标可获小幅加成
    - 共享节省: 组内共享步骤从总需求中扣除 (只执行一次)

预算冲突 (P1):
    - 总需求 > 总预算 → 冲突检测
    - 降级建议: 按优先级从低到高裁剪 (低优先级目标获得最小预算)
    - 全部输出可解释 (为什么该目标获得 X 步)

设计原则:
    - 纯函数式分配 (不修改任何状态)
    - 规则 + 权重 + 阈值: 禁止黑盒优化
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List, Optional

from backend.embodied.schema import EmbodiedGoal

logger = logging.getLogger(__name__)


class BudgetError(Exception):
    """预算分配操作异常"""


# 优先级权重 (可解释): 越高越优先获得预算
PRIORITY_WEIGHTS: Dict[str, float] = {
    "high": 2.0,
    "medium": 1.5,
    "low": 1.0,
}

# 目标基础步骤预算 (计划动作序列不足时按类型默认)
DEFAULT_STEPS_BY_ACTION: Dict[str, int] = {
    "scan": 2,
    "pick": 3,
    "place": 3,
    "move": 2,
    "inspect": 2,
    "explore": 3,
    "custom": 2,
}


class BudgetAllocator:
    """跨目标步骤预算分配器 (规则驱动, 可解释)

    用法:
        alloc = BudgetAllocator(max_budget=100)
        result = alloc.allocate(goals, groups=..., strategy_quality=...)
        conflict = alloc.detect_conflict(goals)
    """

    def __init__(
        self,
        max_budget: int = 100,
        priority_weight_high: float = 2.0,
        priority_weight_medium: float = 1.5,
        priority_weight_low: float = 1.0,
        min_steps_per_goal: int = 1,
        quality_bonus_threshold: float = 0.5,
    ):
        if max_budget <= 0:
            raise BudgetError(f"max_budget 必须 > 0, 当前: {max_budget}")
        if min_steps_per_goal <= 0:
            raise BudgetError(
                f"min_steps_per_goal 必须 > 0, 当前: {min_steps_per_goal}"
            )
        self._lock = threading.RLock()
        self._max_budget = int(max_budget)
        self._priority_weights = {
            "high": float(priority_weight_high),
            "medium": float(priority_weight_medium),
            "low": float(priority_weight_low),
        }
        self._min_steps = int(min_steps_per_goal)
        self._quality_bonus_threshold = float(quality_bonus_threshold)

    # ── 单目标基础需求 ────────────────────────────────────────────
    def _base_demand(self, goal: EmbodiedGoal, sequence_len: int) -> int:
        """单目标基础需求 (可解释):
            - 计划动作序列长度 (>= 1)
            - max_steps 约束 (若指定且更大)
        """
        if sequence_len <= 0:
            # 无动作序列 → 按意图关键词默认
            text = (goal.description + " " + goal.intent).lower()
            for kw, steps in DEFAULT_STEPS_BY_ACTION.items():
                if kw in text:
                    return steps
            return DEFAULT_STEPS_BY_ACTION["custom"]
        demand = max(1, sequence_len)
        try:
            max_steps = int(goal.constraints.get("max_steps", 0))
            if max_steps > demand:
                demand = max_steps
        except (TypeError, ValueError):
            pass
        return demand

    # ── 需求计算 (含共享节省) ─────────────────────────────────────
    def demands(
        self,
        goals: List[EmbodiedGoal],
        sequences: Optional[Dict[str, int]] = None,
        shared_saved: Optional[Dict[str, int]] = None,
    ) -> Dict[str, Any]:
        """目标需求计算: 基础需求 + 共享节省

        Args:
            goals: 目标列表
            sequences: goal_id → 计划动作序列长度 (None=自动按默认)
            shared_saved: goal_id → 共享步骤节省数 (来自 dependency.shared_steps)

        Returns:
            {
                'rule', 'per_goal': [{'goal_id', 'base_demand',
                                      'shared_saved', 'final_demand'}, ...],
                'total_demand': n, 'total_saved': n,
            }
        """
        with self._lock:
            per_goal: List[Dict[str, Any]] = []
            total = 0
            saved = 0
            for goal in goals:
                seq_len = (sequences or {}).get(goal.goal_id, 0)
                base = self._base_demand(goal, seq_len)
                shared = (shared_saved or {}).get(goal.goal_id, 0)
                final = max(self._min_steps, base - shared)
                per_goal.append({
                    "goal_id": goal.goal_id,
                    "base_demand": base,
                    "shared_saved": shared,
                    "final_demand": final,
                    "priority": goal.priority,
                })
                total += final
                saved += shared
            return {
                "rule": "基础需求 (计划长度/max_steps) - 共享节省 → 最终需求",
                "per_goal": per_goal,
                "total_demand": total,
                "total_saved": saved,
            }

    # ── 预算冲突检测 (P1) ─────────────────────────────────────────
    def detect_conflict(self, demands: Dict[str, Any]) -> Dict[str, Any]:
        """预算冲突检测: 总需求 > 预算 → 降级建议

        Returns:
            {
                'conflict': bool,
                'budget': n, 'total_demand': n, 'deficit': n,
                'rule': ...,
                'suggestions': [{'goal_id', 'priority', 'reason'}, ...],
            }
        """
        total = demands.get("total_demand", 0)
        deficit = total - self._max_budget
        suggestions: List[Dict[str, Any]] = []
        if deficit > 0:
            # 降级建议: 按优先级从低到高 (可解释)
            entries = sorted(
                demands.get("per_goal", []),
                key=lambda d: PRIORITY_WEIGHTS.get(d.get("priority", "medium"), 1.5),
            )
            for e in entries:
                suggestions.append({
                    "goal_id": e["goal_id"],
                    "priority": e.get("priority", "medium"),
                    "reason": (
                        f"预算不足 (缺 {deficit} 步): 建议降低优先级 "
                        f"{e.get('priority', 'medium')} 目标 {e['goal_id']} "
                        f"的步骤或延后执行"
                    ),
                })
        return {
            "conflict": deficit > 0,
            "budget": self._max_budget,
            "total_demand": total,
            "deficit": max(0, deficit),
            "rule": "总需求 > max_budget → 预算冲突, 低优先级目标降级",
            "suggestions": suggestions,
        }

    # ── 预算分配 (可解释) ─────────────────────────────────────────
    def allocate(
        self,
        goals: List[EmbodiedGoal],
        demands: Optional[Dict[str, Any]] = None,
        strategy_quality: Optional[Dict[str, float]] = None,
    ) -> Dict[str, Any]:
        """跨目标预算分配 (策略质量 + 优先级 + 资源限制, 可解释)

        Args:
            goals: 目标列表
            demands: 需求计算结果 (None=自动计算)
            strategy_quality: goal_id → 最优策略 hit_rate (0.0~1.0)

        Returns:
            {
                'mode': 'rule_based',
                'budget': n,
                'allocations': [
                    {
                        'goal_id', 'priority', 'priority_weight',
                        'quality_bonus': bool, 'base_alloc', 'allocated',
                        'reason': '为什么获得 X 步 (可解释)',
                    }, ...
                ],
                'total_allocated': n, 'conflict': {...},
                'saved_by_sharing': n,
            }
        """
        with self._lock:
            demand_result = demands or self.demands(goals)
            entries = demand_result["per_goal"]
            total_demand = demand_result["total_demand"]

            # 1. 权重计算: 优先级权重 × (1 + 质量加成)
            weighted: List[Dict[str, Any]] = []
            for e in entries:
                weight = self._priority_weights.get(
                    e.get("priority", "medium"),
                    self._priority_weights["medium"],
                )
                quality = (strategy_quality or {}).get(e["goal_id"], 0.0)
                bonus = quality >= self._quality_bonus_threshold
                effective = weight * (1.2 if bonus else 1.0)
                weighted.append({
                    **e,
                    "priority_weight": round(weight, 2),
                    "quality_bonus": bonus,
                    "effective_weight": round(effective, 4),
                })

            # 2. 分配策略 (可解释):
            #    - 总需求 <= 预算 → 按需分配 (每人 final_demand)
            #    - 总需求 > 预算 → 按权重比例分配 (预算紧张, 高优先级优先)
            allocations: List[Dict[str, Any]] = []
            if total_demand <= self._max_budget:
                for w in weighted:
                    demand = max(self._min_steps, w["final_demand"])
                    allocations.append({
                        "goal_id": w["goal_id"],
                        "priority": w["priority"],
                        "priority_weight": w["priority_weight"],
                        "quality_bonus": w["quality_bonus"],
                        "base_alloc": demand,
                        "allocated": demand,
                        "reason": (
                            f"需求 {demand} 步在预算内 "
                            f"(总需求 {total_demand} <= 预算 {self._max_budget}), "
                            f"按需分配"
                        ),
                    })
            else:
                total_weight = sum(w["effective_weight"] for w in weighted) or 1.0
                for w in weighted:
                    share = int(
                        self._max_budget * w["effective_weight"] / total_weight
                    )
                    share = max(self._min_steps, share)
                    allocations.append({
                        "goal_id": w["goal_id"],
                        "priority": w["priority"],
                        "priority_weight": w["priority_weight"],
                        "quality_bonus": w["quality_bonus"],
                        "base_alloc": share,
                        "allocated": share,
                        "reason": (
                            f"预算不足 (总需求 {total_demand} > 预算 "
                            f"{self._max_budget}): 优先级 {w['priority']} "
                            f"(权重 {w['priority_weight']})"
                            + (f", 策略质量 {quality:.2f} 达标加成"
                               if w["quality_bonus"] else "")
                            + f" → 分配 {share} 步"
                        ),
                    })

            conflict = self.detect_conflict(demand_result)
            return {
                "mode": "rule_based",
                "budget": self._max_budget,
                "allocations": allocations,
                "total_allocated": sum(a["allocated"] for a in allocations),
                "conflict": conflict,
                "saved_by_sharing": demand_result.get("total_saved", 0),
            }

    # ── 状态 ──────────────────────────────────────────────────────
    def thresholds(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "max_budget": self._max_budget,
                "min_steps_per_goal": self._min_steps,
                "quality_bonus_threshold": self._quality_bonus_threshold,
                "priority_weights": dict(self._priority_weights),
            }


__all__ = [
    "BudgetAllocator",
    "BudgetError",
    "DEFAULT_STEPS_BY_ACTION",
    "PRIORITY_WEIGHTS",
]
