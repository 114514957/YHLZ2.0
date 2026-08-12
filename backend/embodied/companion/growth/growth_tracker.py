"""
YHLZ Embodied AI V6.0 - 成长追踪器 (Growth Tracker)

职责:
    - 采集成长指标: 经验 / 反思 / 创造 / 关系 / 验证
    - 记录成长事件 (时间窗内)
    - 输出指标快照

指标 (可解释):
    - experience_added / experience_confirmed / verification_rejected
    - reflection_created
    - creative_proposal / creative_completed
    - relationship_change
    - identity_change

设计原则:
    - 只统计数字与事件 (不存敏感数据)
    - 纯规则, 无黑盒
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List, Optional

from backend.embodied.companion.growth.growth_meaning import (
    GROWTH_EVENT_TYPES,
)

logger = logging.getLogger(__name__)


class TrackerError(Exception):
    """成长追踪操作异常"""


class GrowthTracker:
    """成长追踪器

    用法:
        tracker = GrowthTracker()
        tracker.record("experience_confirmed", detail="exp_1")
        metrics = tracker.metrics()
    """

    def __init__(self, max_events: int = 5000,
                 window_days: int = 30):
        if max_events <= 0:
            raise TrackerError(
                f"max_events 必须 > 0, 当前: {max_events}"
            )
        self._lock = threading.RLock()
        self._events: List[Dict[str, Any]] = []
        self._max = int(max_events)
        self._window_days = int(window_days)

    # ── 记录 ─────────────────────────────────────────────────────
    def record(self, event_type: str, detail: str = "",
               meta: Optional[Dict[str, Any]] = None,
               now: Optional[float] = None) -> Dict[str, Any]:
        """记录成长事件"""
        with self._lock:
            if event_type not in GROWTH_EVENT_TYPES:
                raise TrackerError(
                    f"非法事件类型: {event_type} "
                    f"(可选: {GROWTH_EVENT_TYPES})"
                )
            event = {
                "event_id": "grow_" +
                __import__("uuid").uuid4().hex[:8],
                "type": event_type,
                "detail": detail,
                "meta": dict(meta or {}),
                "timestamp": now if now is not None else time.time(),
            }
            self._events.append(event)
            if len(self._events) > self._max:
                self._events = self._events[-self._max:]
            return dict(event)

    # ── 指标 ─────────────────────────────────────────────────────
    def metrics(self, now: Optional[float] = None) -> Dict[str, Any]:
        """指标快照 (窗口内)"""
        with self._lock:
            now = now if now is not None else time.time()
            window_start = now - self._window_days * 86400
            window_events = [
                e for e in self._events
                if e["timestamp"] >= window_start
            ]
            counts: Dict[str, int] = {}
            for e in window_events:
                counts[e["type"]] = counts.get(e["type"], 0) + 1
            return {
                "mode": "rule_based",
                "window_days": self._window_days,
                "event_count": len(window_events),
                "by_type": counts,
                "experience_count": (
                    counts.get("experience_added", 0)
                ),
                "confirmed_count": counts.get(
                    "experience_confirmed", 0,
                ),
                "reflection_count": counts.get(
                    "reflection_created", 0,
                ),
                "creative_count": (
                    counts.get("creative_proposal", 0)
                    + counts.get("creative_completed", 0)
                ),
                "relationship_change_count": counts.get(
                    "relationship_change", 0,
                ),
            }

    def events(self, limit: int = 100,
               event_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """查询事件 (最新在前)"""
        with self._lock:
            if event_type is not None and \
                    event_type not in GROWTH_EVENT_TYPES:
                raise TrackerError(
                    f"非法事件类型: {event_type} "
                    f"(可选: {GROWTH_EVENT_TYPES})"
                )
            hits = list(self._events)
            if event_type:
                hits = [e for e in hits if e["type"] == event_type]
            hits.reverse()
            if limit > 0:
                hits = hits[:limit]
            return [dict(e) for e in hits]

    def stats(self) -> Dict[str, Any]:
        """追踪统计"""
        with self._lock:
            events = list(self._events)
        total: Dict[str, int] = {}
        for e in events:
            total[e["type"]] = total.get(e["type"], 0) + 1
        return {
            "mode": "rule_based",
            "total_events": len(events),
            "by_type": total,
        }

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = len(self._events)
            self._events.clear()
            return n


__all__ = [
    "GrowthTracker",
    "TrackerError",
]
