"""
YHLZ Embodied AI V7.0 - 存在连续性记忆 (Presence Memory)

职责:
    - 保存存在表达的历史: 互动模式 / 表达偏好 / 沟通节奏
    - 支撑长期伙伴体验的一致性 (Continuity)

禁止:
    - 未经授权的敏感推断
    - 虚假的心理结论

设计原则:
    - 只存表达层统计 (禁止保存原始对话内容)
    - 统计可解释 (原因/频率)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class PresenceMemoryError(Exception):
    """存在连续性记忆操作异常"""


class PresenceMemory:
    """存在连续性记忆 (互动模式/表达偏好/沟通节奏)

    用法:
        memory = PresenceMemory()
        memory.record(context="success", expression="高兴")
        stats = memory.stats()
    """

    def __init__(self, max_records: int = 2000):
        if max_records <= 0:
            raise PresenceMemoryError(
                f"max_records 必须 > 0, 当前: {max_records}"
            )
        self._lock = threading.RLock()
        self._max_records = int(max_records)
        self._records: List[Dict[str, Any]] = []
        self._mode_count: Dict[str, int] = {}
        self._expression_count: Dict[str, int] = {}
        self._context_count: Dict[str, int] = {}

    # ── 记录 ─────────────────────────────────────────────────────
    def record(
        self,
        context: str = "",
        expression: str = "",
        interaction_mode: str = "",
        intensity: float = 0.0,
        now: Optional[float] = None,
    ) -> Dict[str, Any]:
        """记录一次表达"""
        entry = {
            "memory_id": "pm_" + uuid.uuid4().hex[:8],
            "time": now if now is not None else time.time(),
            "context": str(context),
            "expression": str(expression),
            "interaction_mode": str(interaction_mode),
            "intensity": round(float(intensity), 4),
        }
        with self._lock:
            self._records.append(entry)
            if len(self._records) > self._max_records:
                self._records = self._records[-self._max_records:]
            if interaction_mode:
                self._mode_count[interaction_mode] = \
                    self._mode_count.get(interaction_mode, 0) + 1
            if expression:
                self._expression_count[expression] = \
                    self._expression_count.get(expression, 0) + 1
            if context:
                self._context_count[context] = \
                    self._context_count.get(context, 0) + 1
        return dict(entry)

    # ── 连续性分析 ───────────────────────────────────────────────
    def continuity(
        self,
        window_days: int = 30,
        now: Optional[float] = None,
    ) -> Dict[str, Any]:
        """沟通节奏连续性 (可解释)

        Returns:
            {
                'mode', 'window_days', 'total', 'daily_avg',
                'rhythm_stability', 'preferred_mode',
                'preferred_expression', 'reason',
            }
        """
        with self._lock:
            now = now if now is not None else time.time()
            start = now - window_days * 86400
            recent = [
                r for r in self._records
                if r["time"] >= start
            ]
            daily_avg = round(
                len(recent) / window_days if window_days else 0.0,
                4,
            )
            # 节奏稳定性: 间隔变异度 (低 = 稳定)
            times = sorted(r["time"] for r in recent)
            gaps = [
                times[i + 1] - times[i]
                for i in range(len(times) - 1)
            ]
            if len(gaps) >= 2:
                mean_gap = sum(gaps) / len(gaps)
                variance = sum(
                    (g - mean_gap) ** 2 for g in gaps
                ) / len(gaps)
                rhythm_stability = round(
                    min(1.0, 1.0 / (1.0 + variance / 1e6)),
                    4,
                )
            else:
                rhythm_stability = 1.0
            # 偏好
            preferred_mode = max(
                self._mode_count.items(),
                key=lambda kv: kv[1],
            )[0] if self._mode_count else "neutral"
            preferred_expression = max(
                self._expression_count.items(),
                key=lambda kv: kv[1],
            )[0] if self._expression_count else "平静"
            return {
                "mode": "rule_based",
                "window_days": int(window_days),
                "total": len(recent),
                "daily_avg": daily_avg,
                "rhythm_stability": rhythm_stability,
                "preferred_mode": preferred_mode,
                "preferred_expression": preferred_expression,
                "reason": (
                    f"窗口内 {len(recent)} 次表达, "
                    f"节奏稳定性 {rhythm_stability}, "
                    f"偏好模式 '{preferred_mode}'"
                ),
            }

    # ── 查询 ─────────────────────────────────────────────────────
    def stats(self) -> Dict[str, Any]:
        """记忆统计"""
        with self._lock:
            return {
                "mode": "rule_based",
                "record_count": len(self._records),
                "max_records": self._max_records,
                "mode_distribution": dict(self._mode_count),
                "expression_distribution": dict(
                    self._expression_count,
                ),
                "context_distribution": dict(
                    self._context_count,
                ),
            }

    def history(self, limit: int = 50) -> List[Dict[str, Any]]:
        """历史记录"""
        with self._lock:
            recent = list(reversed(self._records))
            if limit > 0:
                recent = recent[:limit]
            return [dict(r) for r in recent]

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = len(self._records)
            self._records.clear()
            self._mode_count = {}
            self._expression_count = {}
            self._context_count = {}
            return n


__all__ = [
    "PresenceMemory",
    "PresenceMemoryError",
]
