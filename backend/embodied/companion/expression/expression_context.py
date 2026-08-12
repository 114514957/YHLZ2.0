"""
YHLZ Embodied AI V6.2 - 表达上下文 (Expression Context)

职责:
    - 聚合表达输入: Emotion State / Relationship State /
      Task Context / Conversation Context → 统一上下文
    - 输入缺失时提供安全默认值

设计原则:
    - 只读聚合 (不修改任何输入源)
    - 输入缺失 → 中性默认 (不崩溃)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class ContextError(Exception):
    """表达上下文操作异常"""


class ExpressionContext:
    """表达上下文聚合器

    用法:
        ctx = ExpressionContext()
        context = ctx.build(emotion=..., relationship=...,
                            task=..., conversation=...)
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._built: Dict[str, Any] = {}

    # ── 聚合 ─────────────────────────────────────────────────────
    def build(
        self,
        emotion: Optional[Dict[str, Any]] = None,
        relationship: Optional[Dict[str, Any]] = None,
        task: Optional[Dict[str, Any]] = None,
        conversation: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """构建统一表达上下文

        Args:
            emotion: 情绪状态 (可空)
            relationship: 关系状态 (可空)
            task: 任务上下文 (可空)
            conversation: 对话上下文 (可空)

        Returns:
            {
                'emotion': {...}, 'relationship': {...},
                'task': {...}, 'conversation': {...},
                'built_at',
            }
        """
        with self._lock:
            context = {
                "emotion": dict(emotion or {}),
                "relationship": dict(relationship or {}),
                "task": dict(task or {}),
                "conversation": dict(conversation or {}),
                "built_at": time.time(),
            }
            self._built = dict(context)
            return context

    # ── 缺失处理 ─────────────────────────────────────────────────
    @staticmethod
    def neutral() -> Dict[str, Any]:
        """中性上下文 (无任何输入时)"""
        return {
            "emotion": {},
            "relationship": {},
            "task": {},
            "conversation": {},
        }

    def latest(self) -> Dict[str, Any]:
        """最近构建的上下文 (无则中性)"""
        with self._lock:
            return dict(self._built) if self._built \
                else self.neutral()

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = 1 if self._built else 0
            self._built = {}
            return n


__all__ = [
    "ContextError",
    "ExpressionContext",
]
