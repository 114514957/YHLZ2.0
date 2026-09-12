"""
YHLZ Embodied AI V6.1.1 - 整理调度器 (Consolidation Scheduler)

职责:
    - 自动记忆整理调度:
      条件1: 经验数量达到阈值 (经 GrowthTrigger)
      条件2: 距离上次整理超过 N 天
    - 触发后执行 Memory Consolidation
    - 记录上次整理时间 (防重复触发)

设计原则:
    - 自动行为必须审计 (可追踪)
    - 触发条件可解释
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List, Optional

from backend.embodied.companion.rhythm.growth_trigger import (
    GrowthTrigger,
)

logger = logging.getLogger(__name__)


class SchedulerError(Exception):
    """整理调度操作异常"""


class ConsolidationScheduler:
    """整理调度器

    用法:
        sched = ConsolidationScheduler(trigger)
        result = sched.tick(experience_count=25,
                            consolidate_fn=engine.consolidate)
    """

    def __init__(self, trigger: Optional[GrowthTrigger] = None,
                 default_days: int = 7):
        self._lock = threading.RLock()
        self._trigger = trigger or GrowthTrigger(
            consolidate_days=default_days,
        )
        self._last_run: float = 0.0
        self._run_count = 0
        self._history: List[Dict[str, Any]] = []

    # ── 调度 ─────────────────────────────────────────────────────
    def tick(
        self,
        experience_count: int = 0,
        consolidate_fn=None,
        now: Optional[float] = None,
    ) -> Dict[str, Any]:
        """执行一次调度检查

        Args:
            experience_count: 当前经验数量
            consolidate_fn: 整理回调 (可空, 仅判断不执行)
            now: 当前时间

        Returns:
            {
                'checked', 'triggered', 'reasons': [...],
                'consolidated', 'result', 'last_run_days',
                'mode',
            }
        """
        with self._lock:
            now = now if now is not None else time.time()
            last_days = (
                (now - self._last_run) / 86400.0
                if self._last_run > 0 else 999.0
            )
            reasons = self._trigger.check(
                experience_count=experience_count,
                last_consolidation_days=last_days,
                now=now,
            )
            triggered = any(r["triggered"] for r in reasons)
            result = None
            if triggered and consolidate_fn is not None:
                try:
                    result = consolidate_fn()
                    self._last_run = now
                    self._run_count += 1
                    self._history.append({
                        "scheduled_at": now,
                        "reasons": [
                            r["reason"] for r in reasons
                            if r["triggered"]
                        ],
                        "success": True,
                    })
                except Exception as e:
                    logger.warning(
                        f"[Rhythm] 自动整理失败: {e}",
                    )
                    self._history.append({
                        "scheduled_at": now,
                        "reasons": [
                            r["reason"] for r in reasons
                            if r["triggered"]
                        ],
                        "success": False,
                        "error": str(e),
                    })
            elif triggered:
                self._run_count += 1
                self._last_run = now
                self._history.append({
                    "scheduled_at": now,
                    "reasons": [
                        r["reason"] for r in reasons
                        if r["triggered"]
                    ],
                    "success": True,
                    "note": "仅判断 (无整理回调)",
                })
            return {
                "mode": "rule_based",
                "checked": True,
                "triggered": triggered,
                "reasons": reasons,
                "consolidated": result is not None,
                "result": result,
                "last_run_days": round(last_days, 2),
            }

    # ── 查询 ─────────────────────────────────────────────────────
    def stats(self) -> Dict[str, Any]:
        """调度统计"""
        with self._lock:
            return {
                "mode": "rule_based",
                "run_count": self._run_count,
                "last_run": self._last_run,
                "history": [dict(h) for h in self._history[-10:]],
                "thresholds": self._trigger.thresholds(),
            }

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = len(self._history)
            self._history.clear()
            self._last_run = 0.0
            self._run_count = 0
            return n


__all__ = [
    "ConsolidationScheduler",
    "SchedulerError",
]
