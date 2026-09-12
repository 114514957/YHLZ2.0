"""
YHLZ Embodied AI V6.1.1 - 情绪衰减 (Emotion Decay)

职责:
    - 自然衰减 (回归基线)
    - 公式:
      Current Emotion = Previous Emotion + Event Impact - Natural Decay
    - 防止永久高情绪 / 长期无事件逐渐恢复

规则 (可解释):
    - 衰减量 = decay_rate * 距基线距离 * 时间因子
    - 时间因子 = min(1.0, elapsed_days / decay_window_days)
    - 任何事件后的情绪经过 idle 逐渐回到基线

设计原则:
    - 配置驱动 (禁止魔法数字)
    - 纯规则, 无黑盒
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict

from backend.embodied.companion.emotion.emotion_state import (
    EMOTION_DIMENSIONS,
    EmotionState,
)

logger = logging.getLogger(__name__)


class DecayError(Exception):
    """情绪衰减操作异常"""


class EmotionDecay:
    """情绪衰减器 (向基线回归)

    用法:
        decay = EmotionDecay(rate=0.05, window_days=7)
        state = decay.decay(state, now)
    """

    def __init__(self, rate: float = 0.05,
                 window_days: float = 7.0):
        if not (0.0 <= rate <= 1.0):
            raise DecayError(
                f"rate 必须在 [0,1], 当前: {rate}"
            )
        if window_days <= 0:
            raise DecayError(
                f"window_days 必须 > 0, 当前: {window_days}"
            )
        self._lock = threading.RLock()
        self._rate = float(rate)
        self._window_days = float(window_days)

    # ── 衰减 ─────────────────────────────────────────────────────
    def decay(self, state: EmotionState,
              now: Optional[float] = None) -> Dict[str, Any]:
        """执行一次衰减 (向基线回归)

        Args:
            state: 情绪状态
            now: 当前时间

        Returns:
            衰减后的状态 dict
        """
        with self._lock:
            now = now if now is not None else time.time()
            current = state.to_dict()
            baseline = state.baseline()
            elapsed_days = max(
                0.0, (now - float(current["timestamp"])) / 86400.0,
            )
            time_factor = min(1.0, elapsed_days / self._window_days)
            deltas: Dict[str, float] = {}
            for dim in EMOTION_DIMENSIONS:
                gap = baseline[dim] - current[dim]
                delta = self._rate * gap * time_factor
                deltas[dim] = delta
            # 无变化 (已近基线或未超时间) → 直接返回
            if all(abs(d) < 1e-9 for d in deltas.values()):
                return state.to_dict()
            return state.apply(deltas, reason="自然衰减回归基线")

    # ── 查询 ─────────────────────────────────────────────────────
    def stats(self) -> Dict[str, Any]:
        """衰减配置统计"""
        with self._lock:
            return {
                "mode": "rule_based",
                "rate": self._rate,
                "window_days": self._window_days,
                "formula": (
                    "Current = Previous + Event Impact - Natural Decay"
                ),
            }


__all__ = [
    "DecayError",
    "EmotionDecay",
]
