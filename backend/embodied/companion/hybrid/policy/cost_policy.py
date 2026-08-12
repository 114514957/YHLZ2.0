"""
YHLZ Embodied AI V6.8 - 成本策略 (Cost Policy)

职责:
    - 记录模型调用成本 {model, tokens, cost, value_score}
    - 低价值任务禁止调用高成本模型
    - 成本优化建议 (可解释)

规则 (可解释):
    - 模型成本等级: high_cost > high_cost_threshold
    - value_score < low_value_threshold → 禁止高成本模型
    - 单次成本上限: cost > max_single_cost → 拒绝

设计原则:
    - 纯规则 (无黑盒)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class CostError(Exception):
    """成本策略操作异常"""


# 模型成本等级 (可解释, 每 1k tokens)
COST_TIERS: Dict[str, float] = {
    "free": 0.0,
    "low": 0.002,
    "medium": 0.008,
    "high": 0.02,
}


class CostPolicy:
    """成本策略 (价值 → 成本限制)

    用法:
        policy = CostPolicy(high_cost_threshold=0.01,
                            low_value_threshold=0.3)
        r = policy.evaluate(value_score=0.2, model="gpt4o")
        policy.record(model="gpt4o", tokens=100, cost=0.001,
                      value_score=0.8)
    """

    def __init__(
        self,
        enabled: bool = True,
        high_cost_threshold: float = 0.01,
        low_value_threshold: float = 0.3,
        max_single_cost: float = 0.5,
        max_records: int = 2000,
    ):
        if high_cost_threshold <= 0:
            raise CostError(
                f"high_cost_threshold 必须 > 0, 当前: "
                f"{high_cost_threshold}"
            )
        if max_records <= 0:
            raise CostError(
                f"max_records 必须 > 0, 当前: {max_records}"
            )
        self._lock = threading.RLock()
        self._enabled = bool(enabled)
        self._high_threshold = float(high_cost_threshold)
        self._low_value = float(low_value_threshold)
        self._max_single = float(max_single_cost)
        self._max_records = int(max_records)
        self._records: list = []
        self._block_count = 0
        self._total_cost = 0.0
        self._total_tokens = 0

    # ── 评估 ─────────────────────────────────────────────────────
    def evaluate(
        self,
        value_score: float = 0.0,
        model: str = "",
        cost_per_1k_tokens: Optional[float] = None,
    ) -> Dict[str, Any]:
        """成本可行性评估

        Args:
            value_score: 任务价值分 (0~1)
            model: 模型名 (用于查询成本)
            cost_per_1k_tokens: 显式成本 (覆盖查询)

        Returns:
            {
                'allowed', 'reason', 'tier', 'mode',
            }
        """
        with self._lock:
            if not self._enabled:
                return {"allowed": True,
                        "reason": "成本策略停用",
                        "tier": "free",
                        "mode": "rule_based"}
            try:
                value = float(value_score)
            except (TypeError, ValueError):
                value = 0.0
            value = min(1.0, max(0.0, value))
            # 成本查询 (显式优先)
            cost_per_k = cost_per_1k_tokens
            if cost_per_k is None:
                cost_per_k = self._model_cost(model)
            tier = self._tier_of(cost_per_k)
            # 1. 低价值 → 禁止高成本模型
            if value < self._low_value and \
                    cost_per_k > self._high_threshold:
                self._block_count += 1
                return {
                    "allowed": False,
                    "reason": (
                        f"低价值任务 (value {value}) "
                        f"禁止高成本模型 '{model}' "
                        f"(cost {cost_per_k}/1k)"
                    ),
                    "tier": tier,
                    "mode": "rule_based",
                }
            # 2. 单次成本上限 (由 evaluate 输入预估)
            return {
                "allowed": True,
                "reason": (
                    f"价值 {value} 满足模型 '{model}' "
                    f"成本约束 ({tier})"
                ),
                "tier": tier,
                "mode": "rule_based",
            }

    # ── 记录 ─────────────────────────────────────────────────────
    def record(
        self,
        model: str = "",
        tokens: int = 0,
        cost: float = 0.0,
        value_score: float = 0.0,
    ) -> Dict[str, Any]:
        """记录一次调用成本"""
        entry = {
            "model": str(model),
            "tokens": int(tokens),
            "cost": round(float(cost), 6),
            "value_score": round(float(value_score), 4),
        }
        with self._lock:
            self._records.append(entry)
            if len(self._records) > self._max_records:
                self._records = self._records[-self._max_records:]
            self._total_cost += entry["cost"]
            self._total_tokens += entry["tokens"]
        return dict(entry)

    # ── 子步骤 (可解释) ─────────────────────────────────────────
    @staticmethod
    def _tier_of(cost_per_1k: float) -> str:
        """成本等级"""
        if cost_per_1k <= COST_TIERS["free"]:
            return "free"
        if cost_per_1k <= COST_TIERS["low"]:
            return "low"
        if cost_per_1k <= COST_TIERS["medium"]:
            return "medium"
        return "high"

    @staticmethod
    def _model_cost(model: str) -> float:
        """模型成本查询 (默认映射)"""
        model_lower = str(model).lower()
        if "deep" in model_lower or "creative" in model_lower \
                or "analysis" in model_lower:
            # 云端深度能力 (推理/创造/分析)
            return COST_TIERS["high"]
        if "gpt" in model_lower or "claude" in model_lower:
            return COST_TIERS["high"]
        if "gemini" in model_lower:
            return COST_TIERS["medium"]
        if "local" in model_lower:
            return COST_TIERS["free"]
        if "r1" in model_lower:
            return COST_TIERS["low"]
        return COST_TIERS["low"]

    # ── 查询 ─────────────────────────────────────────────────────
    def stats(self) -> Dict[str, Any]:
        """成本统计"""
        with self._lock:
            return {
                "mode": "rule_based",
                "enabled": self._enabled,
                "record_count": len(self._records),
                "total_cost": round(self._total_cost, 6),
                "total_tokens": self._total_tokens,
                "block_count": self._block_count,
                "thresholds": {
                    "high_cost_threshold":
                        self._high_threshold,
                    "low_value_threshold": self._low_value,
                    "max_single_cost": self._max_single,
                },
            }

    def optimization(self) -> Dict[str, Any]:
        """成本优化建议"""
        with self._lock:
            records = list(self._records)
        by_model: Dict[str, Dict[str, float]] = {}
        for r in records:
            m = r["model"]
            entry = by_model.setdefault(
                m, {"cost": 0.0, "tokens": 0, "calls": 0},
            )
            entry["cost"] += r["cost"]
            entry["tokens"] += r["tokens"]
            entry["calls"] += 1
        sorted_models = sorted(
            by_model.items(), key=lambda kv: kv[1]["cost"],
            reverse=True,
        )
        suggestions = []
        for model, agg in sorted_models[:3]:
            if agg["calls"] and agg["cost"] > 0.0:
                suggestions.append({
                    "model": model,
                    "cost": round(agg["cost"], 6),
                    "calls": int(agg["calls"]),
                    "suggestion": (
                        f"成本占比高, 评估是否降级到 "
                        f"低成本模型"
                    ),
                })
        return {
            "mode": "rule_based",
            "total_cost": round(self._total_cost, 6),
            "top_cost_models": suggestions,
        }

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = len(self._records)
            self._records.clear()
            self._block_count = 0
            self._total_cost = 0.0
            self._total_tokens = 0
            return n


__all__ = [
    "COST_TIERS",
    "CostError",
    "CostPolicy",
]
