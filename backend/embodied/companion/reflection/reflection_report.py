"""
YHLZ Embodied AI V6.5 - 反思报告 (Reflection Report)

职责:
    - 认知反思总结报告 (结构化)
    - Reflection Memory:
      Experience = 发生了什么; Reflection = 理解了什么
    - 结构: {experience_id, reflection, pattern, growth_value}

设计原则:
    - 反思报告只读 (不修改经历)
    - 可解释 (含依据)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ReportError(Exception):
    """反思报告操作异常"""


class ReflectionReport:
    """反思报告器 (认知总结 + Reflection Memory)

    用法:
        report = ReflectionReport()
        entry = report.record(experience_id, reflection,
                              pattern, growth_value)
    """

    def __init__(self, max_records: int = 500):
        if max_records <= 0:
            raise ReportError(
                f"max_records 必须 > 0, 当前: {max_records}"
            )
        self._lock = threading.RLock()
        self._records: List[Dict[str, Any]] = []
        self._max = int(max_records)

    # ── 记录 (Reflection Memory) ─────────────────────────────────
    def record(
        self,
        experience_id: str,
        reflection: str,
        pattern: str = "",
        growth_value: str = "",
    ) -> Dict[str, Any]:
        """记录一条反思记忆

        Args:
            experience_id: 关联经历 ID
            reflection: 理解内容
            pattern: 模式
            growth_value: 成长价值

        Returns:
            Reflection Memory 条目
        """
        with self._lock:
            if not experience_id:
                raise ReportError("experience_id 不能为空")
            entry = {
                "memory_id": "rme_" + uuid.uuid4().hex[:8],
                "experience_id": experience_id,
                "reflection": reflection,
                "pattern": pattern,
                "growth_value": growth_value,
                "timestamp": time.time(),
            }
            self._records.append(entry)
            if len(self._records) > self._max:
                self._records = self._records[-self._max:]
            return dict(entry)

    # ── 查询 ─────────────────────────────────────────────────────
    def by_experience(
        self, experience_id: str,
    ) -> List[Dict[str, Any]]:
        """按经历查询反思"""
        with self._lock:
            return [
                dict(r) for r in self._records
                if r["experience_id"] == experience_id
            ]

    def history(self, limit: int = 50) -> List[Dict[str, Any]]:
        """反思记忆历史 (最新在前)"""
        with self._lock:
            recent = list(reversed(self._records))
            if limit > 0:
                recent = recent[:limit]
            return [dict(r) for r in recent]

    def stats(self) -> Dict[str, Any]:
        """反思记忆统计"""
        with self._lock:
            records = list(self._records)
        with_pattern = sum(1 for r in records if r["pattern"])
        with_value = sum(1 for r in records if r["growth_value"])
        return {
            "mode": "rule_based",
            "memory_count": len(records),
            "with_pattern": with_pattern,
            "with_growth_value": with_value,
        }

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = len(self._records)
            self._records.clear()
            return n


__all__ = [
    "ReflectionReport",
    "ReportError",
]
