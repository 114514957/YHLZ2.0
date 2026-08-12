"""
YHLZ Embodied AI V9.5 - 认知记忆 (Cognition Memory)

职责:
    - 保存: 认知经验 / 错误案例 / 优化策略
    - 禁止: 未经验证的信息成为长期原则

设计原则:
    - 分类保存 (经验/错误/策略)
    - 验证通过才保存
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class CognitionMemoryError(Exception):
    """认知记忆操作异常"""


# 记忆分类 (可解释)
MEMORY_CATEGORIES: list = [
    "cognitive_experience",  # 认知经验
    "error_case",            # 错误案例
    "optimization_strategy", # 优化策略
]


class CognitionMemory:
    """认知记忆 (分类保存 + 验证过滤)

    用法:
        memory = CognitionMemory()
        memory.save("经验", "cognitive_experience",
                    validated=True)
    """

    def __init__(self, max_records: int = 1000):
        if max_records <= 0:
            raise CognitionMemoryError(
                f"max_records 必须 > 0, 当前: {max_records}"
            )
        self._lock = threading.RLock()
        self._max_records = int(max_records)
        self._records: list = []

    # ── 保存 ─────────────────────────────────────────────────────
    def save(
        self,
        content: str,
        category: str = "cognitive_experience",
        validated: bool = False,
        now: Optional[float] = None,
    ) -> Dict[str, Any]:
        """保存认知记忆 (必须经过验证)"""
        if category not in MEMORY_CATEGORIES:
            raise CognitionMemoryError(
                f"非法分类: {category} "
                f"(可选: {MEMORY_CATEGORIES})"
            )
        with self._lock:
            now = now if now is not None else time.time()
            if not validated:
                return {
                    "mode": "error_frame",
                    "ok": False,
                    "reason": "未验证, 拒绝保存 "
                              "(不能成为长期原则)",
                }
            entry = {
                "memory_id": "cog_" + uuid.uuid4().hex[:8],
                "content": str(content),
                "category": category,
                "validated": True,
                "created_at": now,
            }
            self._records.append(entry)
            if len(self._records) > self._max_records:
                self._records = self._records[-self._max_records:]
            return dict(entry)

    # ── 查询 ─────────────────────────────────────────────────────
    def by_category(self, category: str,
                    limit: int = 50) -> list:
        """按分类查询"""
        if category not in MEMORY_CATEGORIES:
            raise CognitionMemoryError(
                f"非法分类: {category}"
            )
        with self._lock:
            items = [
                dict(r) for r in self._records
                if r["category"] == category
            ]
            recent = list(reversed(items))
            if limit > 0:
                recent = recent[:limit]
            return recent

    def stats(self) -> Dict[str, Any]:
        """记忆统计"""
        with self._lock:
            by_category: Dict[str, int] = {}
            for r in self._records:
                by_category[r["category"]] = by_category.get(
                    r["category"], 0,
                ) + 1
            return {
                "mode": "rule_based",
                "record_count": len(self._records),
                "by_category": by_category,
            }

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = len(self._records)
            self._records.clear()
            return n


__all__ = [
    "CognitionMemory",
    "CognitionMemoryError",
    "MEMORY_CATEGORIES",
]
