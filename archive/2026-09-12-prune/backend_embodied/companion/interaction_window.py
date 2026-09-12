"""
YHLZ Embodied AI V5.6 - 时间窗口统计 (Interaction Window Statistics)

职责:
    - 窗口内互动统计: recent_success_rate / recent_failure_rate /
      recent_interaction_count
    - 支持 7 天 / 30 天窗口

设计原则:
    - 只存统计数字 (禁止保存原始聊天内容)
    - 按时间戳记录, 窗口过滤 (滑动窗口)
    - 不写 Agent Memory
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class WindowError(Exception):
    """窗口统计操作异常"""


# 默认窗口 (天)
DEFAULT_WINDOW_DAYS: int = 30


class InteractionWindow:
    """时间窗口统计器

    用法:
        window = InteractionWindow()
        window.record(success=True)
        stats = window.stats(days=7)
    """

    def __init__(self, max_records: int = 1000):
        if max_records <= 0:
            raise WindowError(f"max_records 必须 > 0, 当前: {max_records}")
        self._lock = threading.RLock()
        # [(timestamp, success), ...] 只存统计所需数字
        self._records: List[tuple] = []
        self._max_records = int(max_records)

    # ── 记录 (只存时间戳+结果) ────────────────────────────────────
    def record(
        self,
        success: bool,
        timestamp: Optional[float] = None,
    ) -> Dict[str, Any]:
        """记录一次互动 (只存时间戳 + 成功标记)"""
        ts = timestamp if timestamp is not None else time.time()
        with self._lock:
            self._records.append((ts, bool(success)))
            if len(self._records) > self._max_records:
                self._records = self._records[-self._max_records:]
            return {"recorded": True, "success": bool(success)}

    # ── 窗口统计 ──────────────────────────────────────────────────
    def stats(
        self,
        days: int = DEFAULT_WINDOW_DAYS,
        now: Optional[float] = None,
    ) -> Dict[str, Any]:
        """窗口内统计

        Args:
            days: 窗口天数 (7 / 30 等)
            now: 当前时间 (None=time.time())

        Returns:
            {
                'window_days': n,
                'recent_interaction_count': n,
                'recent_success_count': n,
                'recent_failure_count': n,
                'recent_success_rate': 0.0~1.0,
                'recent_failure_rate': 0.0~1.0,
                'mode': 'rule_based',
            }
        """
        if days <= 0:
            raise WindowError(f"days 必须 > 0, 当前: {days}")
        now = now if now is not None else time.time()
        cutoff = now - days * 86400.0
        with self._lock:
            recent = [
                (ts, ok) for ts, ok in self._records if ts >= cutoff
            ]
        total = len(recent)
        success = sum(1 for _, ok in recent if ok)
        failure = total - success
        return {
            "window_days": days,
            "recent_interaction_count": total,
            "recent_success_count": success,
            "recent_failure_count": failure,
            "recent_success_rate": round(success / total, 4) if total else 0.0,
            "recent_failure_rate": round(failure / total, 4) if total else 0.0,
            "mode": "rule_based",
        }

    # ── 生命周期 ──────────────────────────────────────────────────
    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = len(self._records)
            self._records.clear()
            return n

    @property
    def count(self) -> int:
        with self._lock:
            return len(self._records)


__all__ = [
    "DEFAULT_WINDOW_DAYS",
    "InteractionWindow",
    "WindowError",
]
