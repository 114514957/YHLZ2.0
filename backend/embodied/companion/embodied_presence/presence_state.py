"""
YHLZ Embodied AI V7.0 - 存在表达状态 (Presence State)

职责:
    - 表达状态定义: expression / posture / intensity /
      interaction_mode / timestamp
    - 状态更新与钳制 (有限幅, 可解释)

原则 (形象 ≠ 身份):
    - PresenceState 是外部表达接口, 不是人格本身
    - 形象可以变化, 身份必须稳定
    - 表达状态不包含身份字段 (mission/core_value 等)

设计原则:
    - 纯规则状态 (无黑盒)
    - 每次变化可解释 (last_reason)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class PresenceStateError(Exception):
    """表达状态操作异常"""


# 表情 (可解释)
EXPRESSIONS: list = [
    "平静",     # 默认状态
    "高兴",     # 积极回应
    "关切",     # 支持关心
    "思考",     # 深度处理
    "疲惫",     # 高负荷
]

# 姿态 (可解释)
POSTURES: list = [
    "待机",     # 无互动
    "聆听",     # 倾听用户
    "回应",     # 正在回应
    "专注",     # 深入处理
]

# 互动模式 (可解释)
INTERACTION_MODES: list = [
    "neutral",      # 中性
    "supportive",   # 支持陪伴
    "playful",      # 轻松活泼
    "focused",      # 专注处理
]

# 默认状态 (可解释)
DEFAULT_PRESENCE: Dict[str, Any] = {
    "expression": "平静",
    "posture": "待机",
    "intensity": 0.3,
    "interaction_mode": "neutral",
}


class PresenceState:
    """表达状态 (外部表达接口)

    用法:
        state = PresenceState()
        state.update({"expression": "高兴"}, reason="任务成功")
    """

    def __init__(
        self,
        expression: str = "平静",
        posture: str = "待机",
        intensity: float = 0.3,
        interaction_mode: str = "neutral",
        floor: float = 0.0,
    ):
        self._lock = threading.RLock()
        self._floor = float(floor)
        self._last_reason = "初始化"
        self._timestamp = time.time()
        self._state: Dict[str, Any] = {}
        self._set(
            expression, posture, intensity,
            interaction_mode,
        )

    def _set(self, expression: str, posture: str,
             intensity: float,
             interaction_mode: str) -> None:
        """内部设置 (校验)"""
        if expression not in EXPRESSIONS:
            raise PresenceStateError(
                f"非法表情: {expression} "
                f"(可选: {EXPRESSIONS})"
            )
        if posture not in POSTURES:
            raise PresenceStateError(
                f"非法姿态: {posture} "
                f"(可选: {POSTURES})"
            )
        if interaction_mode not in INTERACTION_MODES:
            raise PresenceStateError(
                f"非法互动模式: {interaction_mode} "
                f"(可选: {INTERACTION_MODES})"
            )
        try:
            iv = float(intensity)
        except (TypeError, ValueError):
            raise PresenceStateError(
                f"非法强度: {intensity}"
            )
        self._state = {
            "expression": expression,
            "posture": posture,
            "intensity": round(min(1.0, max(
                self._floor, iv,
            )), 4),
            "interaction_mode": interaction_mode,
            "timestamp": time.time(),
        }

    # ── 更新 ─────────────────────────────────────────────────────
    def update(
        self,
        expression: Optional[str] = None,
        posture: Optional[str] = None,
        intensity: Optional[float] = None,
        interaction_mode: Optional[str] = None,
        reason: str = "状态更新",
        now: Optional[float] = None,
    ) -> Dict[str, Any]:
        """更新表达状态 (部分字段)

        Args:
            expression: 表情 (None=不变)
            posture: 姿态 (None=不变)
            intensity: 强度 (None=不变)
            interaction_mode: 互动模式 (None=不变)
            reason: 变化原因 (可解释)
            now: 当前时间

        Returns:
            更新后状态
        """
        with self._lock:
            target = dict(self._state)
            if expression is not None:
                if expression not in EXPRESSIONS:
                    raise PresenceStateError(
                        f"非法表情: {expression}"
                    )
                target["expression"] = expression
            if posture is not None:
                if posture not in POSTURES:
                    raise PresenceStateError(
                        f"非法姿态: {posture}"
                    )
                target["posture"] = posture
            if interaction_mode is not None:
                if interaction_mode not in INTERACTION_MODES:
                    raise PresenceStateError(
                        f"非法互动模式: {interaction_mode}"
                    )
                target["interaction_mode"] = \
                    interaction_mode
            if intensity is not None:
                try:
                    iv = float(intensity)
                except (TypeError, ValueError):
                    raise PresenceStateError(
                        f"非法强度: {intensity}"
                    )
                target["intensity"] = round(min(
                    1.0, max(self._floor, iv),
                ), 4)
            target["timestamp"] = now if now is not None \
                else time.time()
            self._last_reason = str(reason)
            self._state = target
            return dict(self._state)

    # ── 查询 ─────────────────────────────────────────────────────
    def to_dict(self) -> Dict[str, Any]:
        """状态字典"""
        with self._lock:
            out = dict(self._state)
            out["last_reason"] = self._last_reason
            return out

    def get(self, key: str) -> Any:
        """字段查询"""
        with self._lock:
            return self._state.get(key)

    def baseline(self) -> Dict[str, Any]:
        """基线状态"""
        return dict(DEFAULT_PRESENCE)

    def restore(self, state: Dict[str, Any],
                reason: str = "快照恢复") -> Dict[str, Any]:
        """恢复状态 (快照)"""
        with self._lock:
            self._set(
                str(state.get("expression", "平静")),
                str(state.get("posture", "待机")),
                float(state.get("intensity", 0.3)),
                str(state.get("interaction_mode", "neutral")),
            )
            self._last_reason = reason
            return dict(self._state)

    def reset(self) -> Dict[str, Any]:
        """重置 (测试隔离)"""
        with self._lock:
            self._set("平静", "待机", 0.3, "neutral")
            self._last_reason = "重置"
            return dict(self._state)


__all__ = [
    "DEFAULT_PRESENCE",
    "EXPRESSIONS",
    "INTERACTION_MODES",
    "POSTURES",
    "PresenceState",
    "PresenceStateError",
]
