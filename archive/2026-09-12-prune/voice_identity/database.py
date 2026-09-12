"""
YHLZ Voice Identity System V1.1 - 数据库连接与 CRUD 核心

职责:
    - 管理 voice_identity.db 连接 (sqlite3, 线程安全锁)
    - 自动初始化表结构 (幂等)
    - 提供三张表的 CRUD 原语 (供上层 Profile/Registry/Manager 调用)

设计原则:
    - 仅用 stdlib sqlite3 + threading.Lock, 不引入新依赖/ORM
    - 连接复用 (单连接 + 锁); Voice Identity 操作低频, 不在音频热路径
    - 独立 db 文件 voice_identity.db, 不污染 memories.db, 旧启动零影响
    - 模块导入即自动初始化 (init_db 幂等), 但不强制全局副作用 (由 __init__ 控制)
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from pathlib import Path
from typing import Any, List, Optional

from backend.voice_identity.models import VoiceModel, VoiceProfile, VoiceUsage
from backend.voice_identity import schema

logger = logging.getLogger(__name__)


def _json_dumps(obj: Any) -> str:
    """dict → JSON 字符串 (None/非法 → '{}')"""
    try:
        return json.dumps(obj, ensure_ascii=False) if obj is not None else "{}"
    except (TypeError, ValueError):
        return "{}"

# 数据库文件位置: backend/data/voice_identity.db (与 personality.json / memories.db 同目录)
# 支持环境变量 YHLZ_VOICE_IDENTITY_DB 覆盖路径 (用于测试隔离)
_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_DATA_DIR.mkdir(parents=True, exist_ok=True)
DEFAULT_DB_PATH: str = os.environ.get(
    "YHLZ_VOICE_IDENTITY_DB",
    str(_DATA_DIR / "voice_identity.db"),
)


class VoiceIdentityDB:
    """Voice Identity 数据库 (sqlite3 + 锁)

    线程安全: 所有公开方法持有 _lock, 避免多线程并发写入冲突。
    连接以 check_same_thread=False 打开, 仅在锁内使用。
    """

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self._db_path = db_path
        self._lock = threading.RLock()
        self._conn: Optional[sqlite3.Connection] = None
        self._connect()
        self.init_db()

    # ------------------------------------------------------------------
    # 连接管理
    # ------------------------------------------------------------------

    def _connect(self) -> None:
        """建立连接并启用外键 + Row 工厂"""
        self._conn = sqlite3.connect(
            self._db_path,
            check_same_thread=False,
            isolation_level=None,  # autocommit; 由我们显式 BEGIN/COMMIT 控制
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON;")
        self._conn.execute("PRAGMA journal_mode = WAL;")
        logger.debug(f"VoiceIdentityDB 已连接: {self._db_path}")

    def init_db(self) -> None:
        """幂等初始化: 执行全部 DDL + 运行迁移"""
        with self._lock:
            assert self._conn is not None
            cur = self._conn.cursor()
            for ddl in schema.ALL_DDL:
                # executescript 支持单条/多条语句, 适配 CREATE TABLE + CREATE INDEX 组合
                cur.executescript(ddl)
            # v1 → v2 迁移: 为旧库补列 (幂等)
            self._migrate(cur)
            # 记录 schema 版本 (元信息表)
            cur.execute(
                "CREATE TABLE IF NOT EXISTS schema_meta "
                "(key TEXT PRIMARY KEY, value TEXT);"
            )
            cur.execute(
                "INSERT OR REPLACE INTO schema_meta(key, value) VALUES (?, ?);",
                ("schema_version", str(schema.SCHEMA_VERSION)),
            )
            logger.info(
                f"VoiceIdentityDB 初始化完成 (schema v{schema.SCHEMA_VERSION}): {self._db_path}"
            )

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                except Exception as e:
                    logger.warning(f"关闭 VoiceIdentityDB 连接异常: {e}")
                self._conn = None

    def _migrate(self, cur) -> None:
        """幂等迁移: 检查 voice_profiles 列, 缺失则 ALTER ADD (V1.2 v1→v2)"""
        existing = {
            row["name"]
            for row in cur.execute(f"PRAGMA table_info({schema.TABLE_VOICE_PROFILES});").fetchall()
        }
        for col, col_def in schema.MIGRATIONS_V2:
            if col not in existing:
                cur.execute(
                    f"ALTER TABLE {schema.TABLE_VOICE_PROFILES} "
                    f"ADD COLUMN {col} {col_def};"
                )
                logger.info(f"迁移: voice_profiles +{col} {col_def}")

    # ------------------------------------------------------------------
    # 事务上下文
    # ------------------------------------------------------------------

    def _execute(
        self,
        sql: str,
        params: tuple = (),
        *,
        fetch: str = "none",
    ) -> Any:
        """统一执行入口 (锁内)

        fetch: none / one / many
        """
        with self._lock:
            assert self._conn is not None
            cur = self._conn.execute(sql, params)
            if fetch == "one":
                return cur.fetchone()
            if fetch == "many":
                return cur.fetchall()
            return cur.lastrowid

    def _executemany_fetch(self, sql: str, params: tuple) -> list:
        with self._lock:
            assert self._conn is not None
            cur = self._conn.execute(sql, params)
            return cur.fetchall()

    # ==================================================================
    # voice_profiles CRUD
    # ==================================================================

    def insert_profile(self, p: VoiceProfile) -> int:
        """插入 profile, 返回新行 id (voice_id 冲突抛 IntegrityError)"""
        sql = (
            "INSERT INTO voice_profiles "
            "(voice_id, owner_id, name, type, language, status, engine, "
            " reference_audio, style, metadata) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);"
        )
        return self._execute(
            sql,
            (
                p.voice_id, p.owner_id, p.name, p.type, p.language, p.status, p.engine,
                p.reference_audio,
                _json_dumps(p.style),
                _json_dumps(p.metadata),
            ),
        )

    def get_profile_by_id(self, voice_id: str) -> Optional[VoiceProfile]:
        row = self._execute(
            "SELECT * FROM voice_profiles WHERE voice_id = ?;",
            (voice_id,),
            fetch="one",
        )
        return VoiceProfile.from_row(row) if row else None

    def list_profiles(
        self,
        *,
        owner: Optional[str] = None,
        type_: Optional[str] = None,
        status: Optional[str] = None,
        engine: Optional[str] = None,
    ) -> List[VoiceProfile]:
        """按可选条件筛选 profile 列表"""
        clauses: list[str] = []
        params: list[Any] = []
        if owner is not None:
            clauses.append("owner_id = ?")
            params.append(owner)
        if type_ is not None:
            clauses.append("type = ?")
            params.append(type_)
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        if engine is not None:
            clauses.append("engine = ?")
            params.append(engine)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = self._executemany_fetch(
            f"SELECT * FROM voice_profiles{where} ORDER BY id ASC;",
            tuple(params),
        )
        return [VoiceProfile.from_row(r) for r in rows]

    def update_profile(self, voice_id: str, fields: dict) -> int:
        """更新指定字段 (允许 name/type/language/status/engine/owner_id/
        reference_audio/style/metadata); 返回受影响行数。
        style/metadata 自动 JSON 序列化。updated_at 由触发器自动刷新。
        """
        allowed = {
            "name", "type", "language", "status", "engine", "owner_id",
            "reference_audio", "style", "metadata",
        }
        updates: dict = {}
        for k, v in fields.items():
            if k not in allowed:
                continue
            if k in ("style", "metadata"):
                updates[k] = _json_dumps(v if v is not None else {})
            else:
                updates[k] = v
        if not updates:
            return 0
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        params = tuple(updates.values()) + (voice_id,)
        with self._lock:
            assert self._conn is not None
            cur = self._conn.execute(
                f"UPDATE voice_profiles SET {set_clause} WHERE voice_id = ?;",
                params,
            )
            return cur.rowcount

    def delete_profile(self, voice_id: str) -> int:
        """物理删除 profile (级联清理 voice_models / voice_usage via FK);
        返回受影响行数。业务层一般用 status=deleted 软删, 此处保留硬删能力。
        """
        with self._lock:
            assert self._conn is not None
            cur = self._conn.execute(
                "DELETE FROM voice_profiles WHERE voice_id = ?;",
                (voice_id,),
            )
            return cur.rowcount

    # ==================================================================
    # voice_models CRUD
    # ==================================================================

    def insert_model(self, m: VoiceModel) -> int:
        sql = (
            "INSERT INTO voice_models "
            "(voice_id, engine, model_path, cache_path, hash, loaded) "
            "VALUES (?, ?, ?, ?, ?, ?);"
        )
        return self._execute(
            sql,
            (m.voice_id, m.engine, m.model_path, m.cache_path, m.hash, int(m.loaded)),
        )

    def get_models_by_voice(self, voice_id: str) -> List[VoiceModel]:
        rows = self._executemany_fetch(
            "SELECT * FROM voice_models WHERE voice_id = ? ORDER BY id ASC;",
            (voice_id,),
        )
        return [VoiceModel.from_row(r) for r in rows]

    def update_model_loaded(self, model_id: int, loaded: bool) -> int:
        with self._lock:
            assert self._conn is not None
            cur = self._conn.execute(
                "UPDATE voice_models SET loaded = ? WHERE id = ?;",
                (int(loaded), model_id),
            )
            return cur.rowcount

    def delete_model(self, model_id: int) -> int:
        with self._lock:
            assert self._conn is not None
            cur = self._conn.execute("DELETE FROM voice_models WHERE id = ?;", (model_id,))
            return cur.rowcount

    def delete_models_by_voice(self, voice_id: str) -> int:
        with self._lock:
            assert self._conn is not None
            cur = self._conn.execute(
                "DELETE FROM voice_models WHERE voice_id = ?;", (voice_id,)
            )
            return cur.rowcount

    # ==================================================================
    # voice_usage CRUD
    # ==================================================================

    def upsert_usage(self, voice_id: str) -> int:
        """插入或递增使用计数 (首次插入 usage_count=1, 已存在则 +1)
        返回当前 usage_count
        """
        with self._lock:
            assert self._conn is not None
            self._conn.execute(
                "INSERT INTO voice_usage (voice_id, usage_count, last_used, duration) "
                "VALUES (?, 1, strftime('%Y-%m-%dT%H:%M:%S','now'), 0.0) "
                "ON CONFLICT(voice_id) DO UPDATE SET "
                "usage_count = usage_count + 1, "
                "last_used = strftime('%Y-%m-%dT%H:%M:%S','now');",
                (voice_id,),
            )
            row = self._conn.execute(
                "SELECT usage_count FROM voice_usage WHERE voice_id = ?;",
                (voice_id,),
            ).fetchone()
            return int(row["usage_count"]) if row else 0

    def add_usage_duration(self, voice_id: str, seconds: float) -> None:
        """累加使用时长"""
        with self._lock:
            assert self._conn is not None
            self._conn.execute(
                "UPDATE voice_usage SET duration = duration + ? "
                "WHERE voice_id = ?;",
                (float(seconds), voice_id),
            )

    def get_usage(self, voice_id: str) -> Optional[VoiceUsage]:
        row = self._execute(
            "SELECT * FROM voice_usage WHERE voice_id = ?;",
            (voice_id,),
            fetch="one",
        )
        return VoiceUsage.from_row(row) if row else None

    def list_all_usage(self) -> List[VoiceUsage]:
        """列出全部使用统计 (V2.3-Phase4 生命周期清理用)"""
        rows = self._executemany_fetch(
            "SELECT * FROM voice_usage ORDER BY last_used ASC;",
            (),
        )
        return [VoiceUsage.from_row(r) for r in rows]

    def delete_usage(self, voice_id: str) -> int:
        with self._lock:
            assert self._conn is not None
            cur = self._conn.execute(
                "DELETE FROM voice_usage WHERE voice_id = ?;", (voice_id,)
            )
            return cur.rowcount

    # ==================================================================
    # schema_meta (键值元数据, V1.6 选中声音持久化等)
    # ==================================================================

    def get_meta(self, key: str) -> Optional[str]:
        """读取元数据键值"""
        row = self._execute(
            "SELECT value FROM schema_meta WHERE key = ?;",
            (key,),
            fetch="one",
        )
        return row["value"] if row else None

    def set_meta(self, key: str, value: str) -> None:
        """写入元数据键值 (UPSERT)"""
        with self._lock:
            assert self._conn is not None
            self._conn.execute(
                "INSERT INTO schema_meta(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value;",
                (key, value),
            )

    def delete_meta(self, key: str) -> int:
        with self._lock:
            assert self._conn is not None
            cur = self._conn.execute("DELETE FROM schema_meta WHERE key = ?;", (key,))
            return cur.rowcount

    # ==================================================================
    # 诊断
    # ==================================================================

    def health(self) -> dict:
        """数据库健康快照 (供 V1.7 审计/未来 API 使用)"""
        with self._lock:
            assert self._conn is not None
            try:
                n_profiles = self._conn.execute(
                    "SELECT COUNT(*) AS c FROM voice_profiles;"
                ).fetchone()["c"]
                n_models = self._conn.execute(
                    "SELECT COUNT(*) AS c FROM voice_models;"
                ).fetchone()["c"]
                n_usage = self._conn.execute(
                    "SELECT COUNT(*) AS c FROM voice_usage;"
                ).fetchone()["c"]
                return {
                    "ok": True,
                    "db_path": self._db_path,
                    "schema_version": schema.SCHEMA_VERSION,
                    "voice_profiles": n_profiles,
                    "voice_models": n_models,
                    "voice_usage": n_usage,
                }
            except Exception as e:
                return {"ok": False, "error": str(e), "db_path": self._db_path}


# ── 模块级单例 (懒加载, 避免导入即副作用; 由 __init__.py 统一暴露) ──
_db_instance: Optional[VoiceIdentityDB] = None
_db_lock = threading.Lock()


def get_db(db_path: Optional[str] = None) -> VoiceIdentityDB:
    """获取全局 VoiceIdentityDB 单例 (首次调用自动初始化)

    V2.3: 动态读取 YHLZ_VOICE_IDENTITY_DB 环境变量, 避免模块加载顺序导致
    测试 DB 隔离失效 (DEFAULT_DB_PATH 在模块加载时已固定)。
    """
    global _db_instance
    if _db_instance is None:
        with _db_lock:
            if _db_instance is None:
                # 优先级: 显式参数 > 环境变量 > DEFAULT_DB_PATH
                path = db_path or os.environ.get("YHLZ_VOICE_IDENTITY_DB") or DEFAULT_DB_PATH
                _db_instance = VoiceIdentityDB(path)
    return _db_instance


def reset_db_instance() -> None:
    """重置全局 DB 单例 (仅用于测试 teardown, 生产代码勿调用)

    关闭现有连接并清空单例, 下次 get_db() 会以当前 DEFAULT_DB_PATH 重建。
    """
    global _db_instance
    with _db_lock:
        if _db_instance is not None:
            try:
                _db_instance.close()
            except Exception:
                pass
            _db_instance = None
