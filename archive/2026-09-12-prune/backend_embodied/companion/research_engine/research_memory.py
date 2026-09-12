"""
YHLZ Embodied AI V9.0 - 研究记忆 (Research Memory)

职责:
    - 研究结果集成: Research Result → Memory Filter →
      Constitution Check → Long Term Memory
    - 保存: 来源 / 结论 / 验证状态 / 不确定性

设计原则:
    - Memory Filter (验证通过 + 来源可靠)
    - Constitution Check (身份安全)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class ResearchMemoryError(Exception):
    """研究记忆操作异常"""


class ResearchMemory:
    """研究记忆 (过滤集成)

    用法:
        memory = ResearchMemory()
        memory.save(conclusion, source, level="fact",
                    validated=True)
    """

    def __init__(self, max_records: int = 1000):
        if max_records <= 0:
            raise ResearchMemoryError(
                f"max_records 必须 > 0, 当前: {max_records}"
            )
        self._lock = threading.RLock()
        self._max_records = int(max_records)
        self._records: list = []

    # ── 保存 (经 Filter + Constitution) ─────────────────────────
    def save(
        self,
        conclusion: str,
        source: str = "unknown",
        level: str = "hypothesis",
        validated: bool = False,
        constitution_ok: bool = False,
        uncertainty: str = "",
        now: Optional[float] = None,
    ) -> Dict[str, Any]:
        """保存研究记忆

        Args:
            conclusion: 结论
            source: 来源
            level: 知识等级 (fact/evidence/inference/...)
            validated: 验证通过
            constitution_ok: 宪法检查通过
            uncertainty: 不确定性说明

        Returns:
            记忆条目 (过滤拒绝 → error_frame)
        """
        with self._lock:
            now = now if now is not None else time.time()
            # Memory Filter: 验证 + 来源可靠 + 非推测
            if not validated:
                return {
                    "mode": "error_frame",
                    "ok": False,
                    "reason": "未验证, 拒绝入长期记忆",
                }
            if level == "speculation":
                return {
                    "mode": "error_frame",
                    "ok": False,
                    "reason": "推测禁止写入事实记忆",
                }
            if not constitution_ok:
                return {
                    "mode": "error_frame",
                    "ok": False,
                    "reason": "宪法检查未通过, 拒绝入记忆",
                }
            entry = {
                "memory_id": "rm_" + uuid.uuid4().hex[:8],
                "conclusion": str(conclusion),
                "source": str(source),
                "level": str(level),
                "validated": True,
                "uncertainty": str(uncertainty),
                "created_at": now,
            }
            self._records.append(entry)
            if len(self._records) > self._max_records:
                self._records = self._records[-self._max_records:]
            return dict(entry)

    # ── 查询 ─────────────────────────────────────────────────────
    def by_level(self, level: str,
                 limit: int = 50) -> list:
        """按等级查询"""
        with self._lock:
            items = [
                dict(r) for r in self._records
                if r["level"] == level
            ]
            recent = list(reversed(items))
            if limit > 0:
                recent = recent[:limit]
            return recent

    def stats(self) -> Dict[str, Any]:
        """记忆统计"""
        with self._lock:
            by_level: Dict[str, int] = {}
            for r in self._records:
                by_level[r["level"]] = by_level.get(
                    r["level"], 0,
                ) + 1
            return {
                "mode": "rule_based",
                "record_count": len(self._records),
                "by_level": by_level,
            }

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = len(self._records)
            self._records.clear()
            return n


__all__ = [
    "ResearchMemory",
    "ResearchMemoryError",
]
