"""
YHLZ Embodied AI V10.1 - 记忆淘汰 (Memory Pruner)

职责:
    - 无价值数据清理: 低价值 + 超龄 + 未确认 → 淘汰候选
    - 只出候选 (proposal), 执行必须显式调用
    - 审计全程记录

设计原则:
    - 淘汰 = 候选 + 显式执行 (热机"禁止未验证写入"语义)
    - 保护: CONFIRMED 记忆 / 高价值记忆默认保留
    - 规则可解释 (reason 字段)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class PrunerError(Exception):
    """记忆淘汰异常"""


class MemoryPruner:
    """记忆淘汰器 (V10.1)

    用法:
        p = MemoryPruner(value_threshold=0.3, age_days=90)
        candidates = p.candidates(records, confirmed_ids)
        ok = p.execute(record_ids, store_forget)
    """

    def __init__(
        self,
        value_threshold: float = 0.3,
        age_days: int = 90,
        enabled: bool = True,
    ):
        if not (0.0 <= value_threshold <= 1.0):
            raise PrunerError(
                f"value_threshold 必须在 [0,1], 当前: {value_threshold}"
            )
        if age_days <= 0:
            raise PrunerError(
                f"age_days 必须 > 0, 当前: {age_days}"
            )
        self._lock = threading.RLock()
        self._value_threshold = float(value_threshold)
        self._age_days = int(age_days)
        self._enabled = bool(enabled)
        self._candidate_count = 0
        self._execute_count = 0

    def candidates(
        self,
        records: List[Dict[str, Any]],
        confirmed_ids: Optional[List[str]] = None,
        now: Optional[float] = None,
    ) -> Dict[str, Any]:
        """淘汰候选 (只出方案, 不执行)

        Args:
            records: 记忆记录 dict 列表
            confirmed_ids: CONFIRMED 记忆 ID 列表 (保护)
            now: 当前时间戳 (测试注入)

        Returns:
            {
                "mode", "enabled", "total",
                "candidates": [{
                    "record_id", "trigger", "value", "age_days",
                    "confirmed", "reasons",
                }],
                "protected": 保护保留 ID 列表,
            }
        """
        with self._lock:
            if not self._enabled:
                return {
                    "mode": "error_frame",
                    "ok": False,
                    "reason": "记忆淘汰停用",
                }
            confirmed = set(confirmed_ids or [])
            now_ts = now if now is not None else time.time()
            candidates: List[Dict[str, Any]] = []
            protected: List[str] = []

            for rec in records:
                rid = rec.get("id", "")
                value = self._to_float(rec.get("value"), 0.5)
                is_confirmed = rid in confirmed
                age_days = self._age_of(rec, now_ts)

                reasons: List[str] = []
                low_value = value < self._value_threshold
                over_age = age_days > self._age_days
                if low_value:
                    reasons.append(
                        f"低价值 {value} < 阈值 "
                        f"{self._value_threshold}"
                    )
                if over_age:
                    reasons.append(
                        f"超龄 {age_days} 天 > {self._age_days} 天"
                    )
                if not is_confirmed:
                    reasons.append("未确认 (非 CONFIRMED)")

                # 候选条件: 低价值 + 超龄 + 未确认 (严格 AND)
                # 保护: CONFIRMED 记忆永不淘汰 (仅 CONFIRMED 进长期参考)
                if low_value and over_age and not is_confirmed:
                    candidates.append({
                        "record_id": rid,
                        "trigger": rec.get("trigger", ""),
                        "value": value,
                        "age_days": age_days,
                        "confirmed": is_confirmed,
                        "reasons": reasons,
                    })
                else:
                    protected.append(rid)

            self._candidate_count += 1
            return {
                "mode": "rule_based",
                "enabled": self._enabled,
                "total": len(records),
                "candidates": candidates,
                "protected": protected,
            }

    def execute(
        self,
        record_ids: List[str],
        forget_fn,
        records: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """显式执行淘汰 (调用外部 forget 函数)

        Args:
            record_ids: 要淘汰的记录 ID 列表
            forget_fn: forget(record_id) -> bool 回调
            records: 原记录列表 (用于 reason 溯源)

        Returns:
            {
                "mode", "enabled", "requested", "removed",
                "not_found", "removed_ids",
            }
        """
        with self._lock:
            if not self._enabled:
                return {
                    "mode": "error_frame",
                    "ok": False,
                    "reason": "记忆淘汰停用",
                }
            rec_map = {r.get("id", ""): r for r in (records or [])}
            removed: List[str] = []
            not_found: List[str] = []
            for rid in record_ids:
                if callable(forget_fn) and forget_fn(rid):
                    removed.append(rid)
                elif rec_map.get(rid) is not None:
                    # 回调未删除但记录存在 → 未删除
                    not_found.append(rid)
                else:
                    not_found.append(rid)
            self._execute_count += 1
            return {
                "mode": "rule_based",
                "enabled": self._enabled,
                "requested": len(record_ids),
                "removed": len(removed),
                "not_found": len(not_found),
                "removed_ids": removed,
            }

    @staticmethod
    def _to_float(value: Any, default: float) -> float:
        try:
            v = float(value)
            return v if v == v else default
        except (TypeError, ValueError):
            return default

    def _age_of(self, record: Dict[str, Any],
                now: float) -> float:
        """记录年龄 (天)"""
        try:
            ts = float(record.get("timestamp", now))
        except (TypeError, ValueError):
            ts = now
        return round((now - ts) / 86400.0, 1) if now > ts else 0.0

    def stats(self) -> Dict[str, Any]:
        """淘汰统计"""
        with self._lock:
            return {
                "mode": "rule_based",
                "enabled": self._enabled,
                "value_threshold": self._value_threshold,
                "age_days": self._age_days,
                "candidate_runs": self._candidate_count,
                "execute_count": self._execute_count,
            }

    def clear(self) -> int:
        """清空计数 (测试隔离)"""
        with self._lock:
            n = self._candidate_count + self._execute_count
            self._candidate_count = 0
            self._execute_count = 0
            return n


__all__ = [
    "MemoryPruner",
    "PrunerError",
]
