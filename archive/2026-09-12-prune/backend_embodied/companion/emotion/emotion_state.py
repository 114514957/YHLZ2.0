"""
YHLZ Embodied AI V6.1.1 - 情绪状态 (Emotion State)

职责:
    - 可计算情绪状态: positivity (积极度) / energy (活跃程度) /
      warmth (关系温度)
    - 状态结构:
      {positivity, energy, warmth, last_reason, timestamp}
    - 范围: 0.0 ~ 1.0 (三维系)

设计原则:
    - 情绪不是意识 (可计算状态变量, 不模拟真实情感)
    - 情绪不是人格 (不触碰 Identity Layer)
    - 每次变化可解释 (last_reason)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class EmotionError(Exception):
    """情绪状态操作异常"""


# 情绪维度白名单 (可解释)
EMOTION_DIMENSIONS: list = ["positivity", "energy", "warmth"]

# 基线情绪 (回归目标, 可解释)
EMOTION_BASELINE: Dict[str, float] = {
    "positivity": 0.6,  # 积极度基线 (中性偏积极)
    "energy": 0.5,      # 活跃程度基线 (中性)
    "warmth": 0.6,      # 关系温度基线 (铁哥们基础温度)
}


class EmotionState:
    """情绪状态 (可计算三维系)

    用法:
        st = EmotionState()
        st.update({"positivity": 0.7}, reason="success")
        d = st.to_dict()
    """

    def __init__(
        self,
        positivity: Optional[float] = None,
        energy: Optional[float] = None,
        warmth: Optional[float] = None,
        baseline: Optional[Dict[str, float]] = None,
        floor: float = 0.0,
    ):
        if not (0.0 <= floor < 1.0):
            raise EmotionError(
                f"floor 必须在 [0,1), 当前: {floor}"
            )
        self._lock = threading.RLock()
        self._floor = float(floor)
        base = dict(EMOTION_BASELINE)
        if baseline:
            base.update(baseline)
        self._baseline = base
        self._state = {
            "positivity": self._clamp(
                positivity if positivity is not None else base["positivity"],
            ),
            "energy": self._clamp(
                energy if energy is not None else base["energy"],
            ),
            "warmth": self._clamp(
                warmth if warmth is not None else base["warmth"],
            ),
        }
        self._last_reason = "初始化"
        self._timestamp = time.time()

    # ── 读取 ─────────────────────────────────────────────────────
    def get(self, dimension: str) -> float:
        """查询单维 (0.0~1.0)"""
        with self._lock:
            if dimension not in EMOTION_DIMENSIONS:
                raise EmotionError(
                    f"非法维度: {dimension} "
                    f"(可选: {EMOTION_DIMENSIONS})"
                )
            return self._state[dimension]

    def to_dict(self) -> Dict[str, Any]:
        """当前状态 (含原因与时间戳)"""
        with self._lock:
            return {
                "positivity": round(self._state["positivity"], 4),
                "energy": round(self._state["energy"], 4),
                "warmth": round(self._state["warmth"], 4),
                "last_reason": self._last_reason,
                "timestamp": self._timestamp,
            }

    # ── 更新 (内部, 经引擎调用) ─────────────────────────────────
    def apply(self, deltas: Dict[str, float],
              reason: str) -> Dict[str, Any]:
        """应用维度变化 (clamp [floor,1])"""
        with self._lock:
            for dim, delta in deltas.items():
                if dim not in EMOTION_DIMENSIONS:
                    raise EmotionError(
                        f"非法维度: {dim} "
                        f"(可选: {EMOTION_DIMENSIONS})"
                    )
            values = {
                dim: self._state[dim] + deltas[dim]
                for dim in deltas
            }
            self._apply_dims(values)
            self._last_reason = reason
            self._timestamp = time.time()
            return self.to_dict()

    def set_state(self, state: Dict[str, Any],
                  reason: str = "恢复") -> Dict[str, Any]:
        """直接设置 (恢复用)"""
        with self._lock:
            self._apply_dims(state)
            self._last_reason = reason
            self._timestamp = time.time()
            return self.to_dict()

    # ── 基线 ─────────────────────────────────────────────────────
    def baseline(self) -> Dict[str, float]:
        """回归基线"""
        with self._lock:
            return dict(self._baseline)

    def distance_from_baseline(self) -> float:
        """距基线总距离 (衰减幅度依据)"""
        with self._lock:
            total = sum(
                abs(self._state[d] - self._baseline[d])
                for d in EMOTION_DIMENSIONS
            )
            return round(total, 4)

    @staticmethod
    def _clamp(value: float) -> float:
        """钳制到 [0,1]"""
        return max(0.0, min(1.0, value))

    def _clamp_floor(self, value: float) -> float:
        """钳制到 [floor,1] (防无限下降)"""
        return max(self._floor, min(1.0, value))

    def _apply_dims(self, values: Dict[str, float]) -> None:
        """应用维度值 (带下限)"""
        for dim in EMOTION_DIMENSIONS:
            if dim in values:
                self._state[dim] = self._clamp_floor(
                    float(values[dim]),
                )


__all__ = [
    "EMOTION_BASELINE",
    "EMOTION_DIMENSIONS",
    "EmotionError",
    "EmotionState",
]
