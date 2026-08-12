"""
YHLZ Personality Engine V3.4 - SQLite 人格存储

职责:
    - 持久化人格档案 (表: personality_profiles, 独立存储)
    - 与内存实现同一接口 (PersonalityStore)
    - 线程安全 (RLock + 单连接 + autocommit + WAL)
    - 懒加载连接 (首次操作时初始化, 启动不阻塞)

设计原则:
    - 复用 Agent Memory / Vision Memory 的 SQLite 模式
    - JSON 列存储结构化字段 (traits / preferences / guidelines)
    - 人格数据独立表, 绝不写入 Agent Memory
    - 异常包装为 PersonalityStoreError (不泄漏底层异常)
    - 检索: 按 created_at 倒序, 支持关键词 / 维度 / 活跃过滤
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from typing import Any, List, Optional

from backend.personality.interface import PersonalityStore, PersonalityStoreError
from backend.personality.schema import PersonalityPreferences, PersonalityProfile, PersonalityQuery

logger = logging.getLogger(__name__)


_DEFAULT_DB_PATH = os.path.join("backend", "data", "personality_profiles.db")


_SCHEMA = """
CREATE TABLE IF NOT EXISTS personality_profiles (
    profile_id TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    traits TEXT NOT NULL DEFAULT '{}',
    tone TEXT NOT NULL DEFAULT '',
    preferences TEXT NOT NULL DEFAULT '{}',
    guidelines TEXT NOT NULL DEFAULT '[]',
    active INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_personality_active ON personality_profiles(active);
CREATE INDEX IF NOT EXISTS idx_personality_created ON personality_profiles(created_at);
"""


class SQLitePersonalityStore(PersonalityStore):
    """SQLite 人格存储

    用法:
        store = SQLitePersonalityStore("backend/data/personality_profiles.db")
        store.save(profile)
        profiles = store.query(PersonalityQuery(keyword="温暖"))
    """

    def __init__(self, db_path: Optional[str] = None):
        # 支持环境变量覆盖 (测试隔离)
        env_path = os.environ.get("YHLZ_PERSONALITY_DB")
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

    def _row_to_profile(self, row: sqlite3.Row) -> PersonalityProfile:
        traits = json.loads(row["traits"] or "{}")
        return PersonalityProfile(
            profile_id=row["profile_id"],
            name=row["name"],
            description=row["description"],
            traits=traits,
            tone=row["tone"],
            preferences=PersonalityPreferences.from_dict(json.loads(row["preferences"] or "{}")),
            guidelines=json.loads(row["guidelines"] or "[]"),
            active=bool(row["active"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def save(self, profile: PersonalityProfile) -> str:
        with self._lock:
            try:
                conn = self._connect()
                conn.execute(
                    """INSERT OR REPLACE INTO personality_profiles
                       (profile_id, name, description, traits, tone, preferences,
                        guidelines, active, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        profile.profile_id, profile.name, profile.description,
                        json.dumps(profile.traits, ensure_ascii=False),
                        profile.tone,
                        json.dumps(profile.preferences.to_dict(), ensure_ascii=False),
                        json.dumps(profile.guidelines, ensure_ascii=False),
                        int(profile.active), profile.created_at, profile.updated_at,
                    ),
                )
                return profile.profile_id
            except Exception as e:
                raise PersonalityStoreError(f"SQLite 保存失败: {e}") from e

    def retrieve(self, profile_id: str) -> Optional[PersonalityProfile]:
        with self._lock:
            try:
                conn = self._connect()
                row = conn.execute(
                    "SELECT * FROM personality_profiles WHERE profile_id = ?",
                    (profile_id,),
                ).fetchone()
                return self._row_to_profile(row) if row is not None else None
            except Exception as e:
                raise PersonalityStoreError(f"SQLite 获取失败: {e}") from e

    def update(self, profile_id: str, **fields) -> bool:
        if not fields:
            return False
        allowed = {
            "name", "description", "traits", "tone",
            "preferences", "guidelines", "active",
        }
        valid = {k: v for k, v in fields.items() if k in allowed}
        if not valid:
            return False
        if "traits" in valid:
            valid["traits"] = json.dumps(valid["traits"], ensure_ascii=False)
        if "preferences" in valid:
            prefs = valid["preferences"]
            valid["preferences"] = json.dumps(
                prefs.to_dict() if isinstance(prefs, PersonalityPreferences) else prefs,
                ensure_ascii=False,
            )
        if "guidelines" in valid:
            valid["guidelines"] = json.dumps(valid["guidelines"], ensure_ascii=False)
        if "active" in valid:
            valid["active"] = int(bool(valid["active"]))
        set_clause = ", ".join(f"{k} = ?" for k in valid)
        params = list(valid.values()) + [time.time(), profile_id]
        with self._lock:
            try:
                conn = self._connect()
                cur = conn.execute(
                    f"UPDATE personality_profiles SET {set_clause}, updated_at = ? WHERE profile_id = ?",
                    params,
                )
                return cur.rowcount > 0
            except Exception as e:
                raise PersonalityStoreError(f"SQLite 更新失败: {e}") from e

    def delete(self, profile_id: str) -> bool:
        with self._lock:
            try:
                conn = self._connect()
                cur = conn.execute(
                    "DELETE FROM personality_profiles WHERE profile_id = ?",
                    (profile_id,),
                )
                return cur.rowcount > 0
            except Exception as e:
                raise PersonalityStoreError(f"SQLite 删除失败: {e}") from e

    def query(self, query: PersonalityQuery) -> List[PersonalityProfile]:
        with self._lock:
            try:
                conn = self._connect()
                conditions: List[str] = []
                params: List[Any] = []
                if query.active_only:
                    conditions.append("active = 1")
                if query.keyword:
                    conditions.append("(name LIKE ? OR description LIKE ? OR tone LIKE ?)")
                    kw = f"%{query.keyword}%"
                    params += [kw, kw, kw]
                if query.trait_filter:
                    for trait, threshold in query.trait_filter.items():
                        conditions.append("traits LIKE ?")
                        params.append(f'%"{trait}"%')
                where = " WHERE " + " AND ".join(conditions) if conditions else ""
                params.append(query.limit)
                params.append(query.offset)
                rows = conn.execute(
                    f"SELECT * FROM personality_profiles{where} "
                    f"ORDER BY created_at DESC LIMIT ? OFFSET ?",
                    params,
                ).fetchall()
                profiles = [self._row_to_profile(r) for r in rows]
                # trait_filter 阈值在应用层精确校验 (JSON LIKE 只能粗筛)
                if query.trait_filter:
                    profiles = [
                        p for p in profiles
                        if all(p.traits.get(t, 0.0) >= th
                               for t, th in query.trait_filter.items())
                    ]
                return profiles
            except Exception as e:
                raise PersonalityStoreError(f"SQLite 检索失败: {e}") from e

    def count(self) -> int:
        with self._lock:
            try:
                conn = self._connect()
                row = conn.execute("SELECT COUNT(*) FROM personality_profiles").fetchone()
                return int(row[0])
            except Exception as e:
                raise PersonalityStoreError(f"SQLite 计数失败: {e}") from e

    def clear(self) -> int:
        with self._lock:
            try:
                conn = self._connect()
                cur = conn.execute("DELETE FROM personality_profiles")
                return cur.rowcount
            except Exception as e:
                raise PersonalityStoreError(f"SQLite 清空失败: {e}") from e

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None


__all__ = ["SQLitePersonalityStore"]
