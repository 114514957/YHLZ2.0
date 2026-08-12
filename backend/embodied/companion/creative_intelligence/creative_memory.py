"""
YHLZ Embodied AI V8.5 - 创造记忆 (Creative Memory)

职责:
    - 保存: 成功方案 / 失败方案 / 未完成想法 / 被证伪假设
    - 必须经过 Memory Filter (验证通过才入)

设计原则:
    - 记忆过滤: 验证 ok 才可保存
    - 分类可解释 (status)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class CreativeMemoryError(Exception):
    """创造记忆操作异常"""


# 记忆状态 (可解释)
MEMORY_STATUS: list = [
    "success",        # 成功方案
    "failure",        # 失败方案
    "incomplete",     # 未完成想法
    "falsified",      # 被证伪假设
]


class CreativeMemory:
    """创造记忆 (过滤保存 + 分类查询)

    用法:
        memory = CreativeMemory()
        memory.save(entry, status="success",
                    validated=True)
    """

    def __init__(self, max_records: int = 1000):
        if max_records <= 0:
            raise CreativeMemoryError(
                f"max_records 必须 > 0, 当前: {max_records}"
            )
        self._lock = threading.RLock()
        self._max_records = int(max_records)
        self._records: list = []

    # ── 保存 (经过滤) ───────────────────────────────────────────
    def save(
        self,
        content: str,
        status: str = "incomplete",
        validated: bool = False,
        validation_reason: str = "",
        now: Optional[float] = None,
    ) -> Dict[str, Any]:
        """保存创造记忆 (必须经过验证)"""
        if status not in MEMORY_STATUS:
            raise CreativeMemoryError(
                f"非法状态: {status} "
                f"(可选: {MEMORY_STATUS})"
            )
        with self._lock:
            now = now if now is not None else time.time()
            if not validated:
                return {
                    "mode": "error_frame",
                    "ok": False,
                    "reason": "未经验证, 拒绝入记忆 "
                              "(Memory Filter)",
                }
            entry = {
                "memory_id": "cm_" + uuid.uuid4().hex[:8],
                "content": str(content),
                "status": status,
                "validated": True,
                "validation_reason": str(
                    validation_reason,
                ),
                "created_at": now,
            }
            self._records.append(entry)
            if len(self._records) > self._max_records:
                self._records = self._records[-self._max_records:]
            return dict(entry)

    # ── 查询 ─────────────────────────────────────────────────────
    def by_status(self, status: str,
                  limit: int = 50) -> list:
        """按状态查询"""
        if status not in MEMORY_STATUS:
            raise CreativeMemoryError(
                f"非法状态: {status}"
            )
        with self._lock:
            items = [
                dict(r) for r in self._records
                if r["status"] == status
            ]
            recent = list(reversed(items))
            if limit > 0:
                recent = recent[:limit]
            return recent

    def stats(self) -> Dict[str, Any]:
        """记忆统计"""
        with self._lock:
            by_status: Dict[str, int] = {}
            for r in self._records:
                by_status[r["status"]] = by_status.get(
                    r["status"], 0,
                ) + 1
            return {
                "mode": "rule_based",
                "record_count": len(self._records),
                "by_status": by_status,
            }

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = len(self._records)
            self._records.clear()
            return n


__all__ = [
    "CreativeMemory",
    "CreativeMemoryError",
    "MEMORY_STATUS",
]
