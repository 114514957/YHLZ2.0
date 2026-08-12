"""
YHLZ Embodied AI V5.7 - 经历存储 (Experience Store)

职责:
    - 经历持久化: ExperienceRecord 存储 (内存 + JSONL 可选)
    - 生命周期: store / retrieve / update / decay / forget
    - 上限保护: 禁止无限记忆 (max_records, 低价值优先遗忘)

设计原则:
    - 高价值经验长期保存, 低价值逐渐衰减
    - 存储独立 (不写 Agent Memory)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any, Dict, List, Optional

from backend.embodied.companion.experience.experience_record import (
    ExperienceRecord,
)

logger = logging.getLogger(__name__)


class ExperienceStoreError(Exception):
    """经历存储操作异常"""


class ExperienceStore:
    """经历存储 (内存 + JSONL)

    用法:
        store = ExperienceStore(max_records=200)
        store.store(record)
        rec = store.retrieve(record_id)
        store.update(record_id, lesson=...)
        store.decay(days=30)
        store.forget(record_id)
    """

    def __init__(self, max_records: int = 200, path: str = ""):
        if max_records <= 0:
            raise ExperienceStoreError(
                f"max_records 必须 > 0, 当前: {max_records}"
            )
        self._lock = threading.RLock()
        self._records: Dict[str, ExperienceRecord] = {}
        self._max_records = int(max_records)
        self._path = path
        if path and os.path.isfile(path):
            self.load_from_file(path)

    # ── 生命周期 ──────────────────────────────────────────────────
    def store(self, record: ExperienceRecord) -> ExperienceRecord:
        """存储经历 (超出上限 → 低价值优先遗忘)"""
        with self._lock:
            self._records[record.id] = record
            if len(self._records) > self._max_records:
                self._evict_low_value()
            return record

    def retrieve(self, record_id: str) -> Optional[ExperienceRecord]:
        """按 ID 检索"""
        with self._lock:
            return self._records.get(record_id)

    def update(
        self,
        record_id: str,
        lesson: Optional[str] = None,
        value: Optional[float] = None,
        confidence: Optional[float] = None,
    ) -> Optional[ExperienceRecord]:
        """更新经历 (lesson/value/confidence)"""
        with self._lock:
            rec = self._records.get(record_id)
            if rec is None:
                return None
            if lesson is not None:
                rec.lesson = lesson
            if value is not None:
                if not (0.0 <= value <= 1.0):
                    raise ExperienceStoreError(
                        f"value 必须在 [0,1], 当前: {value}"
                    )
                rec.value = float(value)
            if confidence is not None:
                if not (0.0 <= confidence <= 1.0):
                    raise ExperienceStoreError(
                        f"confidence 必须在 [0,1], 当前: {confidence}"
                    )
                rec.confidence = float(confidence)
            return rec

    def decay(self, decay_rate: float = 0.1,
              min_value: float = 0.1) -> List[str]:
        """价值衰减 (低价值经验逐渐衰减, 低于阈值遗忘)

        Args:
            decay_rate: 每次衰减比例
            min_value: 遗忘阈值 (value < min_value → forget)

        Returns:
            被遗忘的记录 ID 列表
        """
        with self._lock:
            if not (0.0 <= decay_rate <= 1.0):
                raise ExperienceStoreError(
                    f"decay_rate 必须在 [0,1], 当前: {decay_rate}"
                )
            forgotten: List[str] = []
            for rid, rec in list(self._records.items()):
                rec.value = round(rec.value * (1 - decay_rate), 4)
                if rec.value < min_value:
                    self._records.pop(rid, None)
                    forgotten.append(rid)
            return forgotten

    def forget(self, record_id: str) -> bool:
        """遗忘 (删除)"""
        with self._lock:
            return self._records.pop(record_id, None) is not None

    def _evict_low_value(self) -> None:
        """超出上限 → 遗忘最低价值记录"""
        if len(self._records) <= self._max_records:
            return
        lowest = min(self._records.values(), key=lambda r: r.value)
        self._records.pop(lowest.id, None)
        logger.info(f"[ExperienceStore] 上限淘汰低价值: {lowest.id}")

    # ── 查询 ──────────────────────────────────────────────────────
    def all(self) -> List[ExperienceRecord]:
        """全部记录 (按时间倒序)"""
        with self._lock:
            records = sorted(
                self._records.values(), key=lambda r: -r.timestamp,
            )
            return records

    def count(self) -> int:
        with self._lock:
            return len(self._records)

    def stats(self) -> Dict[str, Any]:
        """存储统计 (数量/类型分布/平均价值)"""
        with self._lock:
            records = list(self._records.values())
        by_type: Dict[str, int] = {}
        for r in records:
            by_type[r.type] = by_type.get(r.type, 0) + 1
        avg_value = (
            round(sum(r.value for r in records) / len(records), 4)
            if records else 0.0
        )
        return {
            "mode": "rule_based",
            "total": len(records),
            "max_records": self._max_records,
            "by_type": by_type,
            "avg_value": avg_value,
        }

    # ── 持久化 (JSONL) ────────────────────────────────────────────
    def save_to_file(self, path: str) -> int:
        """保存到 JSONL"""
        with self._lock:
            records = list(self._records.values())
        with open(path, "w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r.to_dict(), ensure_ascii=False) + "\n")
        logger.info(f"[ExperienceStore] 已保存 {len(records)} 条到 {path}")
        return len(records)

    def load_from_file(self, path: str) -> int:
        """从 JSONL 加载"""
        if not os.path.isfile(path):
            return 0
        loaded = 0
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = ExperienceRecord.from_dict(json.loads(line))
                    with self._lock:
                        self._records[rec.id] = rec
                    loaded += 1
                except (json.JSONDecodeError, TypeError) as e:
                    logger.warning(f"[ExperienceStore] 跳过坏行: {e}")
        logger.info(f"[ExperienceStore] 已加载 {loaded} 条从 {path}")
        return loaded

    # ── 生命周期 ──────────────────────────────────────────────────
    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = len(self._records)
            self._records.clear()
            return n


__all__ = [
    "ExperienceStore",
    "ExperienceStoreError",
]
