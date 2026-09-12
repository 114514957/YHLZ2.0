"""
YHLZ 前端情绪状态管理器 (Emotion State Manager)

职责:
    - Runtime Event → Emotion State → Animation 链路
    - 管理当前情绪/动画状态
    - 可查询 / 可订阅变更

设计原则:
    - 情绪由运行时事件驱动, 不是表演模板
    - 只表达状态, 不干预后端
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional

from frontend.avatar.animation import (
    AnimationSpec,
    animation_for_event,
    animation_for_state,
)

logger = logging.getLogger(__name__)

# 情绪枚举 (可解释)
EMOTIONS: List[str] = [
    "neutral",    # 中性
    "happy",      # 开心
    "sad",        # 难过
    "angry",      # 生气
    "surprised",  # 惊讶
]


class EmotionStateError(Exception):
    """情绪状态异常"""


class EmotionState:
    """情绪状态 (可解释)"""

    def __init__(
        self,
        emotion: str = "neutral",
        reason: str = "",
        animation: Optional[AnimationSpec] = None,
    ):
        if emotion not in EMOTIONS:
            raise EmotionStateError(
                f"非法情绪: {emotion} (可选: {EMOTIONS})"
            )
        self.emotion = emotion
        self.reason = str(reason)
        self.animation = animation
        self.updated_at = time.time()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "emotion": self.emotion,
            "reason": self.reason,
            "animation": (
                self.animation.to_dict()
                if self.animation else None
            ),
            "updated_at": self.updated_at,
        }


class EmotionStateManager:
    """情绪状态管理器 (V10.1 Frontend)

    用法:
        esm = EmotionStateManager()
        r = esm.on_runtime_event("SYSTEM_READY")
        r = esm.on_companion_state("thinking")
        snap = esm.snapshot()
    """

    def __init__(self, enabled: bool = True):
        self._lock = threading.RLock()
        self._enabled = bool(enabled)
        self._current = EmotionState()
        self._listeners: List[Callable[[Dict[str, Any]], None]] = []
        self._event_count: Dict[str, int] = {}

    def on_runtime_event(self, event_type: str) -> Dict[str, Any]:
        """运行时事件 → 情绪/动画"""
        with self._lock:
            if not self._enabled:
                return {"mode": "error_frame", "ok": False,
                        "reason": "情绪管理器停用"}
            spec = animation_for_event(event_type)
            self._event_count[event_type] = self._event_count.get(
                event_type, 0,
            ) + 1
            if spec is None:
                return {
                    "mode": "rule_based", "ok": True,
                    "emotion": self._current.emotion,
                    "changed": False,
                    "reason": f"未知事件 {event_type}, 保持当前情绪",
                }
            self._current = EmotionState(
                emotion=spec.emotion,
                reason=spec.reason,
                animation=spec,
            )
            snapshot = self._current.to_dict()
            listeners = list(self._listeners)
        for fn in listeners:
            try:
                fn(snapshot)
            except Exception as e:  # noqa: BLE001 监听者隔离
                logger.error(f"[Emotion] 监听者失败: {e}")
        return {
            "mode": "rule_based", "ok": True,
            "changed": True, **snapshot,
        }

    def on_companion_state(self, state: str) -> Dict[str, Any]:
        """伙伴状态 → 情绪/动画"""
        with self._lock:
            if not self._enabled:
                return {"mode": "error_frame", "ok": False,
                        "reason": "情绪管理器停用"}
            spec = animation_for_state(state)
            if spec is None:
                return {
                    "mode": "rule_based", "ok": True,
                    "emotion": self._current.emotion,
                    "changed": False,
                    "reason": f"未知状态 {state}, 保持当前情绪",
                }
            self._current = EmotionState(
                emotion=spec.emotion,
                reason=spec.reason,
                animation=spec,
            )
            snapshot = self._current.to_dict()
            listeners = list(self._listeners)
        for fn in listeners:
            try:
                fn(snapshot)
            except Exception as e:  # noqa: BLE001
                logger.error(f"[Emotion] 监听者失败: {e}")
        return {
            "mode": "rule_based", "ok": True,
            "changed": True, **snapshot,
        }

    def on_change(self, listener: Callable[[Dict[str, Any]], None]) -> None:
        """订阅情绪变更"""
        with self._lock:
            if not callable(listener):
                raise EmotionStateError("监听者必须可调用")
            self._listeners.append(listener)

    def snapshot(self) -> Dict[str, Any]:
        """当前情绪快照"""
        with self._lock:
            return {
                "mode": "rule_based",
                "enabled": self._enabled,
                **self._current.to_dict(),
            }

    def stats(self) -> Dict[str, Any]:
        """统计"""
        with self._lock:
            return {
                "mode": "rule_based",
                "enabled": self._enabled,
                "current_emotion": self._current.emotion,
                "event_count": dict(self._event_count),
            }

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = len(self._listeners)
            self._listeners.clear()
            self._event_count.clear()
            self._current = EmotionState()
            return n


__all__ = [
    "EMOTIONS",
    "EmotionState",
    "EmotionStateError",
    "EmotionStateManager",
]
