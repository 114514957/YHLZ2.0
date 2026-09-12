"""
YHLZ Vision Memory V1.0 - 内存视觉记忆存储

职责:
    - 测试用 / 轻量场景的内存实现
    - 与 SQLite 实现同一接口 (MemoryStore)
    - 容量上限 (超过删除最旧)

设计原则:
    - 线程安全 (RLock)
    - 无持久化 (进程内)
    - 查询结果按 created_at 倒序
"""
from __future__ import annotations

import logging
import threading
from typing import Dict, List, Optional

from backend.vision.memory.interface import MemoryStore, MemoryStoreError
from backend.vision.memory.schema import MemoryQuery, VisualMemoryRecord

logger = logging.getLogger(__name__)


class InMemoryMemoryStore(MemoryStore):
    """内存视觉记忆存储

    用法:
        store = InMemoryMemoryStore(max_entries=1000)
        store.save(record)
        records = store.query(MemoryQuery(keyword="代码"))
    """

    def __init__(self, max_entries: int = 1000):
        self._lock = threading.RLock()
        self._max_entries = max_entries
        self._records: Dict[str, VisualMemoryRecord] = {}
        self._seq: Dict[str, int] = {}  # id → 插入序号 (同时间戳时稳定排序)
        self._counter = 0

    @property
    def name(self) -> str:
        return "memory"

    def save(self, record: VisualMemoryRecord) -> str:
        with self._lock:
            try:
                self._counter += 1
                if record.id not in self._records:
                    self._seq[record.id] = self._counter
                self._records[record.id] = record
                # 容量控制: 超过上限删除最旧
                if len(self._records) > self._max_entries:
                    overflow = len(self._records) - self._max_entries
                    oldest = sorted(
                        self._records.values(),
                        key=lambda r: (r.created_at, self._seq.get(r.id, 0)),
                    )[:overflow]
                    for r in oldest:
                        self._records.pop(r.id, None)
                        self._seq.pop(r.id, None)
                return record.id
            except Exception as e:
                raise MemoryStoreError(f"内存保存失败: {e}") from e

    def retrieve(self, memory_id: str) -> Optional[VisualMemoryRecord]:
        with self._lock:
            try:
                return self._records.get(memory_id)
            except Exception as e:
                raise MemoryStoreError(f"内存获取失败: {e}") from e

    def update(self, memory_id: str, **fields) -> bool:
        with self._lock:
            try:
                record = self._records.get(memory_id)
                if record is None:
                    return False
                allowed = {
                    "memory_type", "source", "scene_type", "description",
                    "subjects", "tags", "importance", "confidence",
                    "metadata", "timestamp",
                }
                valid = {k: v for k, v in fields.items() if k in allowed}
                if not valid:
                    return False
                for key, value in valid.items():
                    setattr(record, key, value)
                record.updated_at = __import__("time").time()
                return True
            except Exception as e:
                raise MemoryStoreError(f"内存更新失败: {e}") from e

    def delete(self, memory_id: str) -> bool:
        with self._lock:
            try:
                removed = self._records.pop(memory_id, None) is not None
                if removed:
                    self._seq.pop(memory_id, None)
                return removed
            except Exception as e:
                raise MemoryStoreError(f"内存删除失败: {e}") from e

    def query(self, query: MemoryQuery) -> List[VisualMemoryRecord]:
        with self._lock:
            try:
                records = list(self._records.values())
            except Exception as e:
                raise MemoryStoreError(f"内存读取失败: {e}") from e
        # 过滤 (在锁外执行, 防止长查询阻塞写入)
        results = self._filter(records, query)
        # 排序: created_at 倒序, 同时间戳按插入顺序倒序 (最新在前)
        results.sort(
            key=lambda r: (r.created_at, self._seq.get(r.id, 0)),
            reverse=True,
        )
        return results[query.offset:query.offset + query.limit]

    def _filter(
        self,
        records: List[VisualMemoryRecord],
        query: MemoryQuery,
    ) -> List[VisualMemoryRecord]:
        results = []
        for r in records:
            if query.time_from is not None and r.timestamp < query.time_from:
                continue
            if query.time_to is not None and r.timestamp > query.time_to:
                continue
            if query.scene_type and r.scene_type != query.scene_type:
                continue
            if query.importance and r.importance != query.importance:
                continue
            if query.tag and query.tag not in r.tags:
                continue
            if query.keyword and query.keyword not in r.description:
                continue
            results.append(r)
        return results

    def count(self) -> int:
        with self._lock:
            try:
                return len(self._records)
            except Exception as e:
                raise MemoryStoreError(f"内存计数失败: {e}") from e

    def clear(self) -> int:
        with self._lock:
            try:
                n = len(self._records)
                self._records.clear()
                self._seq.clear()
                return n
            except Exception as e:
                raise MemoryStoreError(f"内存清空失败: {e}") from e

    def close(self) -> None:
        with self._lock:
            self._records.clear()
            self._seq.clear()


__all__ = ["InMemoryMemoryStore"]
