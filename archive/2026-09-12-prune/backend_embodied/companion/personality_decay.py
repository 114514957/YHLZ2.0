"""
YHLZ Embodied AI V5.6 - 人格稳定系统 (Personality Decay & Stability)

职责:
    - 时间衰减: 长时间无互动 → 表现人格维度向基础值平滑回归
    - 基础人格回归: 衰减后维度回到基础值 (核心人格不变)
    - 平滑变化: 按时间比例衰减, 不突变

数据模型:
    PersonalityDecayPolicy:
    {
        dimension, base_value, current_value, decay_rate, last_update,
    }

设计原则:
    - 平滑可解释: 衰减量 = (current - base) * decay_rate * elapsed_days
    - 不突变: 每次计算基于 elapsed 时间, 非跳跃
    - 只衰减表现维度, 核心人格 (base) 不变
    - 禁止黑盒模型 (纯线性回归公式)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List, Optional

from backend.embodied.companion.personality_rules import (
    BASE_DIMENSIONS,
    PERSONALITY_DIMENSIONS,
)

logger = logging.getLogger(__name__)


class DecayError(Exception):
    """人格衰减操作异常"""


class PersonalityDecayPolicy:
    """人格衰减策略 (时间衰减 → 基础回归)

    用法:
        decay = PersonalityDecayPolicy(rate=0.05)
        result = decay.apply(dimensions, now=...)
        report = decay.stability(dimensions)
    """

    def __init__(
        self,
        rate: float = 0.05,
        enabled: bool = True,
        base: Optional[Dict[str, float]] = None,
    ):
        if rate < 0:
            raise DecayError(f"rate 必须 >= 0, 当前: {rate}")
        self._lock = threading.RLock()
        self._rate = float(rate)
        self._enabled = bool(enabled)
        self._base = dict(base or BASE_DIMENSIONS)
        # dimension → 最近衰减时间 (用于计算 elapsed)
        self._last_decay: Dict[str, float] = {}

    @property
    def rate(self) -> float:
        with self._lock:
            return self._rate

    @property
    def enabled(self) -> bool:
        with self._lock:
            return self._enabled

    def set_enabled(self, enabled: bool) -> None:
        with self._lock:
            self._enabled = bool(enabled)

    # ── 单维度衰减计算 (可解释) ───────────────────────────────────
    def _decay_value(
        self,
        dimension: str,
        current: float,
        elapsed_days: float,
    ) -> float:
        """单维度衰减: current → base (平滑, 按时间比例)"""
        base = self._base.get(dimension, 0.5)
        offset = current - base
        if offset == 0 or elapsed_days <= 0:
            return current
        # 衰减量 = 偏移量 × 衰减率 × 天数 (有上限: 不超过偏移量)
        decay = offset * self._rate * elapsed_days
        if abs(decay) > abs(offset):
            decay = offset  # 完全回归
        return round(current - decay, 4)

    # ── 应用衰减 ──────────────────────────────────────────────────
    def apply(
        self,
        dimensions: Dict[str, float],
        now: Optional[float] = None,
    ) -> Dict[str, Any]:
        """应用时间衰减 → 更新维度

        Args:
            dimensions: 当前表现维度
            now: 当前时间 (None=time.time())

        Returns:
            {
                'applied': bool, 'decayed': [...],
                'dimensions': {...},   # 衰减后维度 (新 dict)
                'reasons': [...],      # 每维度可解释
            }
        """
        now = now if now is not None else time.time()
        with self._lock:
            if not self._enabled:
                return {
                    "applied": False, "decayed": [],
                    "dimensions": dict(dimensions), "reasons": [],
                }
            updated = dict(dimensions)
            decayed: List[str] = []
            reasons: List[str] = []
            for dim in PERSONALITY_DIMENSIONS:
                current = updated.get(dim, self._base.get(dim, 0.5))
                last = self._last_decay.get(dim, now)
                elapsed_days = max(0.0, (now - last) / 86400.0)
                new_value = self._decay_value(dim, current, elapsed_days)
                if new_value != current:
                    decayed.append(dim)
                    reasons.append(
                        f"{dim}: {current} → {new_value} "
                        f"(距上次 {elapsed_days:.1f} 天, 向基础 "
                        f"{self._base.get(dim, 0.5)} 回归)"
                    )
                    updated[dim] = new_value
                self._last_decay[dim] = now
            return {
                "applied": bool(decayed),
                "decayed": decayed,
                "dimensions": updated,
                "reasons": reasons,
            }

    # ── 稳定状态分析 ──────────────────────────────────────────────
    def stability(
        self,
        dimensions: Dict[str, float],
    ) -> Dict[str, Any]:
        """人格稳定状态 (当前/基础/偏移量/回归次数)"""
        with self._lock:
            total_offset = 0.0
            per_dim: List[Dict[str, Any]] = []
            for dim in PERSONALITY_DIMENSIONS:
                current = dimensions.get(dim, self._base.get(dim, 0.5))
                base = self._base.get(dim, 0.5)
                offset = round(current - base, 4)
                total_offset += abs(offset)
                per_dim.append({
                    "dimension": dim,
                    "base_value": base,
                    "current_value": current,
                    "offset": offset,
                })
            return {
                "mode": "rule_based",
                "enabled": self._enabled,
                "decay_rate": self._rate,
                "base": dict(self._base),
                "current": dict(dimensions),
                "total_offset": round(total_offset, 4),
                "per_dimension": per_dim,
                "stable": total_offset < 0.1,
            }

    # ── 重置 ──────────────────────────────────────────────────────
    def reset(self) -> None:
        """重置衰减状态 (测试隔离)"""
        with self._lock:
            self._last_decay.clear()


__all__ = [
    "DecayError",
    "PersonalityDecayPolicy",
]
