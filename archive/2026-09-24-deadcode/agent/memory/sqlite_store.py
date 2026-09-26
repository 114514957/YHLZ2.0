"""
YHLZ Agent Core V3.0 - SQLite 记忆存储实现

替代 V2.3 残留的 memories.db / memories_v2.db。
表: agent_memories
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from typing import Any, Dict, List, Optional

from backend.agent.memory.base import MemoryEntry, MemoryStore, MemoryStoreError

logger = logging.getLogger(__name__)


_DEFAULT_DB_PATH = os.path.join("backend", "data", "agent_memories.db")


_SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_memories (
    id TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'fact',
    source TEXT NOT NULL DEFAULT 'system',
    metadata TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL,
    last_accessed_at REAL NOT NULL,
    access_count INTEGER NOT NULL DEFAULT 0,
    weight REAL NOT NULL DEFAULT 1.0
);
CREATE INDEX IF NOT EXISTS idx_agent_mem_category ON agent_memories(category);
CREATE INDEX IF NOT EXISTS idx_agent_mem_created ON agent_memories(created_at);
CREATE INDEX IF NOT EXISTS idx_agent_mem_accessed ON agent_memories(last_accessed_at);
"""


class SQLiteMemoryStore(MemoryStore):
    """SQLite 持久化记忆存储

    用法:
        store = SQLiteMemoryStore("path/to/db")
        store.add(MemoryEntry.create("用户喜欢咖啡", "preference"))
        results = store.search("咖啡")
    """

    def __init__(self, db_path: Optional[str] = None):
        # 支持环境变量覆盖 (测试隔离)
        env_path = os.environ.get("YHLZ_AGENT_MEMORY_DB")
        self._db_path = env_path or db_path or _DEFAULT_DB_PATH
        os.makedirs(os.path.dirname(os.path.abspath(self._db_path)), exist_ok=True)
        self._lock = threading.RLock()
        self._conn: Optional[sqlite3.Connection] = None
        self._connect()

    def _connect(self) -> None:
        try:
            self._conn = sqlite3.connect(
                self._db_path,
                check_same_thread=False,
                isolation_level=None,  # autocommit
            )
            self._conn.row_factory = sqlite3.Row
            self._conn.executescript(_SCHEMA)
        except Exception as e:
            raise MemoryStoreError(f"连接记忆 DB 失败: {e}") from e

    def _row_to_entry(self, row: sqlite3.Row) -> MemoryEntry:
        return MemoryEntry(
            id=row["id"],
            content=row["content"],
            category=row["category"],
            source=row["source"],
            metadata=json.loads(row["metadata"] or "{}"),
            created_at=row["created_at"],
            last_accessed_at=row["last_accessed_at"],
            access_count=row["access_count"],
            weight=row["weight"],
        )

    def add(self, entry: MemoryEntry) -> str:
        with self._lock:
            try:
                self._conn.execute(
                    """INSERT OR REPLACE INTO agent_memories
                       (id, content, category, source, metadata, created_at, last_accessed_at, access_count, weight)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        entry.id, entry.content, entry.category, entry.source,
                        json.dumps(entry.metadata, ensure_ascii=False),
                        entry.created_at, entry.last_accessed_at,
                        entry.access_count, entry.weight,
                    ),
                )
                return entry.id
            except Exception as e:
                raise MemoryStoreError(f"添加记忆失败: {e}") from e

    def get(self, memory_id: str) -> Optional[MemoryEntry]:
        with self._lock:
            try:
                row = self._conn.execute(
                    "SELECT * FROM agent_memories WHERE id = ?",
                    (memory_id,),
                ).fetchone()
                if row is None:
                    return None
                entry = self._row_to_entry(row)
                # 更新访问时间
                self._conn.execute(
                    "UPDATE agent_memories SET last_accessed_at = ?, access_count = access_count + 1 WHERE id = ?",
                    (time.time(), memory_id),
                )
                return entry
            except Exception as e:
                raise MemoryStoreError(f"获取记忆失败: {e}") from e

    def update(self, memory_id: str, **fields) -> bool:
        if not fields:
            return False
        allowed = {"content", "category", "source", "metadata", "weight"}
        valid = {k: v for k, v in fields.items() if k in allowed}
        if not valid:
            return False
        if "metadata" in valid:
            valid["metadata"] = json.dumps(valid["metadata"], ensure_ascii=False)
        set_clause = ", ".join(f"{k} = ?" for k in valid)
        params = list(valid.values()) + [memory_id]
        with self._lock:
            try:
                cur = self._conn.execute(
                    f"UPDATE agent_memories SET {set_clause} WHERE id = ?",
                    params,
                )
                return cur.rowcount > 0
            except Exception as e:
                raise MemoryStoreError(f"更新记忆失败: {e}") from e

    def delete(self, memory_id: str) -> bool:
        with self._lock:
            try:
                cur = self._conn.execute(
                    "DELETE FROM agent_memories WHERE id = ?",
                    (memory_id,),
                )
                return cur.rowcount > 0
            except Exception as e:
                raise MemoryStoreError(f"删除记忆失败: {e}") from e

    def list_all(
        self,
        category: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[MemoryEntry]:
        with self._lock:
            try:
                if category:
                    rows = self._conn.execute(
                        "SELECT * FROM agent_memories WHERE category = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                        (category, limit, offset),
                    ).fetchall()
                else:
                    rows = self._conn.execute(
                        "SELECT * FROM agent_memories ORDER BY created_at DESC LIMIT ? OFFSET ?",
                        (limit, offset),
                    ).fetchall()
                return [self._row_to_entry(r) for r in rows]
            except Exception as e:
                raise MemoryStoreError(f"列出记忆失败: {e}") from e

    def search(
        self,
        query: str,
        limit: int = 5,
        category: Optional[str] = None,
    ) -> List[MemoryEntry]:
        """关键词搜索 (LIKE 匹配, V3.0 不引入向量库)"""
        if not query.strip():
            return []
        # 简单分词: 按空格切, 中文按 2 字滑窗
        keywords = self._extract_keywords(query)
        if not keywords:
            return []

        with self._lock:
            try:
                # 构建 OR LIKE 条件
                conditions = " OR ".join(["content LIKE ?"] * len(keywords))
                params = [f"%{kw}%" for kw in keywords]
                if category:
                    conditions = f"({conditions}) AND category = ?"
                    params.append(category)
                params.append(limit)
                sql = (
                    f"SELECT * FROM agent_memories WHERE {conditions} "
                    f"ORDER BY weight DESC, last_accessed_at DESC LIMIT ?"
                )
                rows = self._conn.execute(sql, params).fetchall()
                entries = [self._row_to_entry(r) for r in rows]
                # 更新访问时间
                for e in entries:
                    self._conn.execute(
                        "UPDATE agent_memories SET last_accessed_at = ?, access_count = access_count + 1 WHERE id = ?",
                        (time.time(), e.id),
                    )
                return entries
            except Exception as e:
                raise MemoryStoreError(f"搜索记忆失败: {e}") from e

    def _extract_keywords(self, query: str) -> List[str]:
        """提取关键词 (简单, 不引入 jieba)"""
        keywords: List[str] = []
        # 英文单词
        for w in query.split():
            w = w.strip(".,!?;:。，！？；：")
            if len(w) >= 2 and w.isascii():
                keywords.append(w)
        # 中文 2-3 字滑窗
        chinese = "".join(c for c in query if "\u4e00" <= c <= "\u9fff")
        if len(chinese) >= 2:
            for i in range(len(chinese) - 1):
                keywords.append(chinese[i:i+2])
            if len(chinese) >= 3:
                for i in range(len(chinese) - 2):
                    keywords.append(chinese[i:i+3])
        # 去重, 保留顺序
        seen = set()
        unique = []
        for k in keywords:
            if k not in seen:
                seen.add(k)
                unique.append(k)
        return unique[:10]  # 最多 10 个

    def count(self, category: Optional[str] = None) -> int:
        with self._lock:
            try:
                if category:
                    row = self._conn.execute(
                        "SELECT COUNT(*) FROM agent_memories WHERE category = ?",
                        (category,),
                    ).fetchone()
                else:
                    row = self._conn.execute("SELECT COUNT(*) FROM agent_memories").fetchone()
                return row[0]
            except Exception as e:
                raise MemoryStoreError(f"计数失败: {e}") from e

    def clear(self) -> int:
        with self._lock:
            try:
                cur = self._conn.execute("DELETE FROM agent_memories")
                return cur.rowcount
            except Exception as e:
                raise MemoryStoreError(f"清空记忆失败: {e}") from e

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None


__all__ = ["SQLiteMemoryStore"]
