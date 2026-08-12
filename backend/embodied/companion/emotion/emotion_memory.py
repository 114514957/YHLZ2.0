"""
YHLZ Embodied AI V6.1.1 - 情绪记忆 (Emotion Memory)

职责:
    - 情绪历史记录:
      {event, emotion_before, emotion_after, reason, impact}
    - 用途: Reflection / Growth Report / Relationship Analysis

设计原则:
    - 只记录元数据 (可回溯)
    - 纯规则, 无黑盒
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class MemoryError(Exception):
    """情绪记忆操作异常"""


class EmotionMemory:
    """情绪记忆器

    用法:
        mem = EmotionMemory()
        mem.record(event="success", before={...}, after={...},
                   reason="任务成功")
    """

    def __init__(self, max_records: int = 1000):
        if max_records <= 0:
            raise MemoryError(
                f"max_records 必须 > 0, 当前: {max_records}"
            )
        self._lock = threading.RLock()
        self._records: List[Dict[str, Any]] = []
        self._max = int(max_records)

    # ── 记录 ─────────────────────────────────────────────────────
    def record(
        self, event: str,
        before: Dict[str, Any],
        after: Dict[str, Any],
        reason: str = "",
        impact: Optional[Dict[str, float]] = None,
    ) -> Dict[str, Any]:
        """记录一次情绪变化"""
        with self._lock:
            entry = {
                "memory_id": "em_" + uuid.uuid4().hex[:8],
                "event": event,
                "emotion_before": dict(before),
                "emotion_after": dict(after),
                "reason": reason,
                "impact": dict(impact or {}),
                "timestamp": time.time(),
            }
            self._records.append(entry)
            if len(self._records) > self._max:
                self._records = self._records[-self._max:]
            return dict(entry)

    # ── 查询 ─────────────────────────────────────────────────────
    def history(self, limit: int = 50,
                event: Optional[str] = None) -> List[Dict[str, Any]]:
        """历史记录 (最新在前)"""
        with self._lock:
            hits = list(self._records)
            if event is not None:
                hits = [h for h in hits if h["event"] == event]
            hits.reverse()
            if limit > 0:
                hits = hits[:limit]
            return [dict(h) for h in hits]

    def by_event(self, event: str) -> List[Dict[str, Any]]:
        """按事件查询"""
        return self.history(limit=100000, event=event)

    def stats(self) -> Dict[str, Any]:
        """情绪记忆统计"""
        with self._lock:
            records = list(self._records)
        by_event: Dict[str, int] = {}
        for r in records:
            by_event[r["event"]] = by_event.get(r["event"], 0) + 1
        return {
            "mode": "rule_based",
            "total": len(records),
            "by_event": by_event,
        }

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = len(self._records)
            self._records.clear()
            return n


__all__ = [
    "EmotionMemory",
    "MemoryError",
]
