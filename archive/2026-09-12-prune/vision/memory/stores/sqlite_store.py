"""
YHLZ Vision Memory V1.0 - SQLite 视觉记忆存储

职责:
    - 持久化视觉记忆 (表: vision_memories)
    - 与内存实现同一接口 (MemoryStore)
    - 线程安全 (RLock + 单连接 + autocommit)
    - 懒加载连接 (首次操作时初始化, 启动不阻塞)

设计原则:
    - 复用 Agent Memory 的 SQLite 模式 (单连接 + WAL + 索引)
    - JSON 列存储结构化字段 (subjects / tags / metadata)
    - 异常包装为 MemoryStoreError (不泄漏底层异常)
    - 检索: 按 created_at 倒序, 支持时间 / 场景 / 标签 / 关键词 / 重要程度过滤
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from typing import Any, List, Optional

from backend.vision.memory.interface import MemoryStore, MemoryStoreError
from backend.vision.memory.schema import MemoryQuery, VisualMemoryRecord

logger = logging.getLogger(__name__)


_DEFAULT_DB_PATH = os.path.join("backend", "data", "vision_memories.db")


_SCHEMA = """
CREATE TABLE IF NOT EXISTS vision_memories (
    id TEXT PRIMARY KEY,
    memory_type TEXT NOT NULL DEFAULT 'scene',
    source TEXT NOT NULL DEFAULT 'vlm',
    timestamp REAL NOT NULL,
    scene_type TEXT NOT NULL DEFAULT 'unknown',
    description TEXT NOT NULL DEFAULT '',
    subjects TEXT NOT NULL DEFAULT '[]',
    tags TEXT NOT NULL DEFAULT '[]',
    importance TEXT NOT NULL DEFAULT 'medium',
    confidence REAL NOT NULL DEFAULT 0.0,
    metadata TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_vision_mem_scene ON vision_memories(scene_type);
CREATE INDEX IF NOT EXISTS idx_vision_mem_time ON vision_memories(created_at);
CREATE INDEX IF NOT EXISTS idx_vision_mem_importance ON vision_memories(importance);
"""


class SQLiteMemoryStore(MemoryStore):
    """SQLite 视觉记忆存储

    用法:
        store = SQLiteMemoryStore("backend/data/vision_memories.db")
        store.save(record)
        records = store.query(MemoryQuery(keyword="代码"))
    """

    def __init__(self, db_path: Optional[str] = None):
        # 支持环境变量覆盖 (测试隔离)
        env_path = os.environ.get("YHLZ_VISION_MEMORY_DB")
        self._db_path = env_path or db_path or _DEFAULT_DB_PATH
        os.makedirs(os.path.dirname(os.path.abspath(self._db_path)), exist_ok=True)
        self._lock = threading.RLock()
        self._conn: Optional[sqlite3.Connection] = None

    def _connect(self) -> sqlite3.Connection:
        """懒加载连接"""
        if self._conn is None:
            self._conn = sqlite3.connect(
                self._db_path,
                check_same_thread=False,
                isolation_level=None,  # autocommit
            )
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(_SCHEMA)
        return self._conn

    @property
    def name(self) -> str:
        return "sqlite"

    def _row_to_record(self, row: sqlite3.Row) -> VisualMemoryRecord:
        return VisualMemoryRecord(
            id=row["id"],
            memory_type=row["memory_type"],
            source=row["source"],
            timestamp=row["timestamp"],
            scene_type=row["scene_type"],
            description=row["description"],
            subjects=json.loads(row["subjects"] or "[]"),
            tags=json.loads(row["tags"] or "[]"),
            importance=row["importance"],
            confidence=row["confidence"],
            metadata=json.loads(row["metadata"] or "{}"),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def save(self, record: VisualMemoryRecord) -> str:
        with self._lock:
            try:
                conn = self._connect()
                conn.execute(
                    """INSERT OR REPLACE INTO vision_memories
                       (id, memory_type, source, timestamp, scene_type, description,
                        subjects, tags, importance, confidence, metadata, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        record.id, record.memory_type, record.source,
                        record.timestamp, record.scene_type, record.description,
                        json.dumps(record.subjects, ensure_ascii=False),
                        json.dumps(record.tags, ensure_ascii=False),
                        record.importance, record.confidence,
                        json.dumps(record.metadata, ensure_ascii=False),
                        record.created_at, record.updated_at,
                    ),
                )
                return record.id
            except Exception as e:
                raise MemoryStoreError(f"SQLite 保存失败: {e}") from e

    def retrieve(self, memory_id: str) -> Optional[VisualMemoryRecord]:
        with self._lock:
            try:
                conn = self._connect()
                row = conn.execute(
                    "SELECT * FROM vision_memories WHERE id = ?",
                    (memory_id,),
                ).fetchone()
                return self._row_to_record(row) if row is not None else None
            except Exception as e:
                raise MemoryStoreError(f"SQLite 获取失败: {e}") from e

    def update(self, memory_id: str, **fields) -> bool:
        if not fields:
            return False
        allowed = {
            "memory_type", "source", "scene_type", "description",
            "subjects", "tags", "importance", "confidence",
            "metadata", "timestamp",
        }
        valid = {k: v for k, v in fields.items() if k in allowed}
        if not valid:
            return False
        json_keys = {"subjects", "tags", "metadata"}
        for key in json_keys:
            if key in valid:
                valid[key] = json.dumps(valid[key], ensure_ascii=False)
        set_clause = ", ".join(f"{k} = ?" for k in valid)
        params = list(valid.values()) + [time.time(), memory_id]
        with self._lock:
            try:
                conn = self._connect()
                cur = conn.execute(
                    f"UPDATE vision_memories SET {set_clause}, updated_at = ? WHERE id = ?",
                    params,
                )
                return cur.rowcount > 0
            except Exception as e:
                raise MemoryStoreError(f"SQLite 更新失败: {e}") from e

    def delete(self, memory_id: str) -> bool:
        with self._lock:
            try:
                conn = self._connect()
                cur = conn.execute(
                    "DELETE FROM vision_memories WHERE id = ?",
                    (memory_id,),
                )
                return cur.rowcount > 0
            except Exception as e:
                raise MemoryStoreError(f"SQLite 删除失败: {e}") from e

    def query(self, query: MemoryQuery) -> List[VisualMemoryRecord]:
        with self._lock:
            try:
                conn = self._connect()
                conditions: List[str] = []
                params: List[Any] = []
                if query.time_from is not None:
                    conditions.append("timestamp >= ?")
                    params.append(query.time_from)
                if query.time_to is not None:
                    conditions.append("timestamp <= ?")
                    params.append(query.time_to)
                if query.scene_type:
                    conditions.append("scene_type = ?")
                    params.append(query.scene_type)
                if query.importance:
                    conditions.append("importance = ?")
                    params.append(query.importance)
                if query.tag:
                    conditions.append("tags LIKE ?")
                    params.append(f'%"{query.tag}"%')
                if query.keyword:
                    conditions.append("description LIKE ?")
                    params.append(f"%{query.keyword}%")
                where = " WHERE " + " AND ".join(conditions) if conditions else ""
                params.append(query.limit)
                params.append(query.offset)
                rows = conn.execute(
                    f"SELECT * FROM vision_memories{where} "
                    f"ORDER BY created_at DESC LIMIT ? OFFSET ?",
                    params,
                ).fetchall()
                return [self._row_to_record(r) for r in rows]
            except Exception as e:
                raise MemoryStoreError(f"SQLite 检索失败: {e}") from e

    def count(self) -> int:
        with self._lock:
            try:
                conn = self._connect()
                row = conn.execute("SELECT COUNT(*) FROM vision_memories").fetchone()
                return int(row[0])
            except Exception as e:
                raise MemoryStoreError(f"SQLite 计数失败: {e}") from e

    def clear(self) -> int:
        with self._lock:
            try:
                conn = self._connect()
                cur = conn.execute("DELETE FROM vision_memories")
                return cur.rowcount
            except Exception as e:
                raise MemoryStoreError(f"SQLite 清空失败: {e}") from e

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None


__all__ = ["SQLiteMemoryStore"]
