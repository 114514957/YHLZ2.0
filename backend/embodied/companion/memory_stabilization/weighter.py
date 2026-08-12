"""
YHLZ Embodied AI V10.1 - 记忆权重评估 (Memory Weighter)

职责:
    - 动态重要度评估: 频率 / 确认状态 / 被引用 → 动态权重
    - 规则可解释: 每个评估输出 rule / reason
    - 不修改存储, 只输出评估结果

设计原则:
    - 权重 = 基础价值 + 动态加成 (频率 / 确认 / 引用)
    - 加成上限保护 (不超过 1.0)
    - 规则可解释 (rule/reason 字段)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class WeighterError(Exception):
    """记忆权重评估异常"""


# 权重加成系数 (可解释, 命名常量)
FREQUENCY_BONUS_MAX: float = 0.2      # 频率加成上限 (出现次数越多越高)
FREQUENCY_BONUS_STEP: float = 0.05    # 每次出现加成
CONFIRMED_BONUS: float = 0.15         # CONFIRMED 确认加成
REFERENCED_BONUS: float = 0.1         # 被引用加成
VALUE_CEILING: float = 1.0            # 权重上限


class MemoryWeighter:
    """记忆权重评估器 (V10.1)

    用法:
        w = MemoryWeighter()
        r = w.evaluate(record, {
            "frequency": 3, "confirmed": True,
            "referenced": True,
        })
    """

    def __init__(self, enabled: bool = True):
        self._lock = threading.RLock()
        self._enabled = bool(enabled)
        self._evaluate_count = 0

    def evaluate(
        self,
        record: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """评估记忆动态权重

        Args:
            record: 记忆记录 dict (需含 value/confidence/trigger 等)
            context:
                {
                    "frequency": 出现次数 (默认 1),
                    "confirmed": 是否 CONFIRMED (默认 False),
                    "referenced": 是否被引用 (默认 False),
                }

        Returns:
            {
                "mode", "record_id", "base_value", "weight",
                "frequency_bonus", "confirmed_bonus",
                "referenced_bonus", "rule", "reason",
            }
        """
        with self._lock:
            if not self._enabled:
                return {
                    "mode": "error_frame",
                    "ok": False,
                    "reason": "记忆权重评估停用",
                }
            ctx = dict(context or {})
            base_value = self._to_float(record.get("value"), 0.5)
            frequency = max(
                0, int(self._to_float(ctx.get("frequency"), 1)),
            )
            confirmed = bool(ctx.get("confirmed", False))
            referenced = bool(ctx.get("referenced", False))

            # 频率加成 (首次出现不加成, 额外出现按步进, ≤ 上限)
            extra = max(0, frequency - 1)
            freq_bonus = min(
                extra * FREQUENCY_BONUS_STEP,
                FREQUENCY_BONUS_MAX,
            ) if extra > 0 else 0.0
            # 确认加成
            conf_bonus = CONFIRMED_BONUS if confirmed else 0.0
            # 引用加成
            ref_bonus = REFERENCED_BONUS if referenced else 0.0

            weight = round(
                min(
                    base_value + freq_bonus + conf_bonus + ref_bonus,
                    VALUE_CEILING,
                ), 4,
            )

            reasons = [f"基础价值 {base_value}"]
            if freq_bonus > 0:
                reasons.append(f"频率 {frequency} 次加成 {freq_bonus}")
            if conf_bonus > 0:
                reasons.append("CONFIRMED 加成")
            if ref_bonus > 0:
                reasons.append("被引用加成")

            self._evaluate_count += 1
            return {
                "mode": "rule_based",
                "enabled": self._enabled,
                "record_id": record.get("id", ""),
                "trigger": record.get("trigger", ""),
                "base_value": base_value,
                "weight": weight,
                "frequency_bonus": round(freq_bonus, 4),
                "confirmed_bonus": conf_bonus,
                "referenced_bonus": ref_bonus,
                "rule": (
                    "weight = base + frequency_bonus + "
                    "confirmed_bonus + referenced_bonus, "
                    "上限 1.0"
                ),
                "reason": ", ".join(reasons),
            }

    def evaluate_many(
        self,
        records: List[Dict[str, Any]],
        context_map: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        """批量评估 (context_map: record_id → context)"""
        ctx_map = dict(context_map or {})
        out = []
        for rec in records:
            rid = rec.get("id", "")
            out.append(self.evaluate(
                rec, ctx_map.get(rid, {}),
            ))
        return out

    @staticmethod
    def _to_float(value: Any, default: float) -> float:
        """安全数值转换"""
        try:
            v = float(value)
            return v if v == v else default
        except (TypeError, ValueError):
            return default

    def stats(self) -> Dict[str, Any]:
        """评估统计"""
        with self._lock:
            return {
                "mode": "rule_based",
                "enabled": self._enabled,
                "evaluate_count": self._evaluate_count,
            }

    def clear(self) -> int:
        """清空计数 (测试隔离)"""
        with self._lock:
            n = self._evaluate_count
            self._evaluate_count = 0
            return n


__all__ = [
    "CONFIRMED_BONUS",
    "FREQUENCY_BONUS_MAX",
    "FREQUENCY_BONUS_STEP",
    "REFERENCED_BONUS",
    "VALUE_CEILING",
    "MemoryWeighter",
    "WeighterError",
]
