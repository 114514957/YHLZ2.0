"""
YHLZ Embodied AI V6.0 - 成长趋势 (Growth Trend)

职责:
    - 成长趋势分析 (按天 / 周 / 月)
    - 输出时间序列与增长量
    - 支持: 经验/反思/创造/关系 各维度

设计原则:
    - 纯规则统计 (禁止黑盒)
    - 桶划分可解释 (day/week/month)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class TrendError(Exception):
    """成长趋势操作异常"""


# 桶类型白名单 (可解释)
TREND_BUCKETS: List[str] = ["day", "week", "month"]

# 桶秒数 (可解释)
BUCKET_SECONDS: Dict[str, float] = {
    "day": 86400.0,
    "week": 7 * 86400.0,
    "month": 30 * 86400.0,
}


class GrowthTrend:
    """成长趋势分析器

    用法:
        trend = GrowthTrend()
        series = trend.series(events, bucket="day")
        delta = trend.delta(events, window_days=30)
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._results: List[Dict[str, Any]] = []

    # ── 时间序列 ─────────────────────────────────────────────────
    def series(
        self, events: List[Dict[str, Any]],
        bucket: str = "day",
        now: Optional[float] = None,
    ) -> Dict[str, Any]:
        """按桶生成时间序列

        Args:
            events: 成长事件列表 (type/timestamp)
            bucket: 桶 (day/week/month)

        Returns:
            {
                'bucket', 'buckets': [{start, count, by_type}],
                'total', 'mode',
            }
        """
        with self._lock:
            if bucket not in TREND_BUCKETS:
                raise TrendError(
                    f"非法桶类型: {bucket} "
                    f"(可选: {TREND_BUCKETS})"
                )
            now = now if now is not None else time.time()
            span = BUCKET_SECONDS[bucket]
            buckets: Dict[int, Dict[str, Any]] = {}
            for e in events:
                ts = float(e.get("timestamp", now))
                key = int(ts // span) * int(span)
                entry = buckets.setdefault(key, {"start": key,
                                                 "count": 0,
                                                 "by_type": {}})
                entry["count"] += 1
                etype = e.get("type", "unknown")
                entry["by_type"][etype] = entry["by_type"].get(
                    etype, 0,
                ) + 1
            ordered = [
                buckets[k] for k in sorted(buckets.keys())
            ]
            result = {
                "bucket": bucket,
                "buckets": ordered,
                "total": len(events),
                "mode": "rule_based",
            }
            self._results.append(result)
            return dict(result)

    # ── 增长量 ───────────────────────────────────────────────────
    def delta(
        self, events: List[Dict[str, Any]],
        window_days: int = 30,
        now: Optional[float] = None,
    ) -> Dict[str, Any]:
        """窗口内增长量 (按类型)

        Args:
            events: 成长事件列表
            window_days: 统计窗口

        Returns:
            {
                'window_days', 'total', 'by_type', 'daily_avg',
                'mode',
            }
        """
        with self._lock:
            now = now if now is not None else time.time()
            start = now - window_days * 86400
            window_events = [
                e for e in events
                if float(e.get("timestamp", 0.0)) >= start
            ]
            by_type: Dict[str, int] = {}
            for e in window_events:
                etype = e.get("type", "unknown")
                by_type[etype] = by_type.get(etype, 0) + 1
            daily_avg = round(
                len(window_events) / max(1, window_days), 4,
            )
            return {
                "mode": "rule_based",
                "window_days": int(window_days),
                "total": len(window_events),
                "by_type": by_type,
                "daily_avg": daily_avg,
            }

    # ── 对比 ─────────────────────────────────────────────────────
    def compare(
        self, events: List[Dict[str, Any]],
        window_days: int = 30,
        now: Optional[float] = None,
    ) -> Dict[str, Any]:
        """前后两半窗口对比 (成长加速/减速)"""
        with self._lock:
            now = now if now is not None else time.time()
            half = window_days * 86400 / 2
            recent = [
                e for e in events
                if now - half <= float(e.get("timestamp", 0.0)) < now
            ]
            earlier = [
                e for e in events
                if now - window_days * 86400
                <= float(e.get("timestamp", 0.0)) < now - half
            ]
            trend = "stable"
            if len(recent) > len(earlier) * 1.2:
                trend = "accelerating"
            elif len(recent) * 1.2 < len(earlier):
                trend = "decelerating"
            return {
                "mode": "rule_based",
                "window_days": int(window_days),
                "earlier_count": len(earlier),
                "recent_count": len(recent),
                "trend": trend,
            }

    def stats(self) -> Dict[str, Any]:
        """趋势统计"""
        with self._lock:
            return {
                "mode": "rule_based",
                "analysis_count": len(self._results),
                "buckets": list(TREND_BUCKETS),
            }

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = len(self._results)
            self._results.clear()
            return n


__all__ = [
    "BUCKET_SECONDS",
    "TREND_BUCKETS",
    "GrowthTrend",
    "TrendError",
]
