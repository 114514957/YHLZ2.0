"""
YHLZ Voice Identity System V1.1 - 数据库 Schema 定义

职责:
    - 集中管理 voice_identity.db 的 DDL (CREATE TABLE) 语句
    - 提供表名常量与 schema 版本号
    - 不含任何运行期逻辑, 仅供 database.py 调用

设计原则:
    - 仅使用 SQLite 原生 SQL (项目无 SQLAlchemy, 不引入新 ORM 体系)
    - 所有表 IF NOT EXISTS, 保证幂等初始化
    - 外键约束显式声明, 但 SQLite 默认关闭外键, 由 database.py 启用
"""
from __future__ import annotations

# Schema 版本号 (未来迁移用)
# v1: 初始三表 (voice_profiles / voice_models / voice_usage)
# v2: voice_profiles 增加 reference_audio / style(JSON) / metadata(JSON) 列 (V1.2)
SCHEMA_VERSION: int = 2

# ── 表名常量 ──
TABLE_VOICE_PROFILES: str = "voice_profiles"
TABLE_VOICE_MODELS: str = "voice_models"
TABLE_VOICE_USAGE: str = "voice_usage"


# ── DDL: voice_profiles (声音身份主表) ──
DDL_VOICE_PROFILES = f"""
CREATE TABLE IF NOT EXISTS {TABLE_VOICE_PROFILES} (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    voice_id        TEXT    NOT NULL UNIQUE,
    owner_id        TEXT    NOT NULL DEFAULT 'system',
    name            TEXT    NOT NULL,
    type            TEXT    NOT NULL DEFAULT 'character',
    language        TEXT    NOT NULL DEFAULT 'zh',
    status          TEXT    NOT NULL DEFAULT 'creating',
    engine          TEXT    NOT NULL DEFAULT 'qwen3',
    reference_audio TEXT,
    style           TEXT    NOT NULL DEFAULT '{{}}',
    metadata        TEXT    NOT NULL DEFAULT '{{}}',
    created_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now')),
    updated_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now'))
);
"""

# v1 → v2 迁移: 为旧库补列 (幂等, 由 database.py _migrate 调用)
# 每条 = (列名, 列定义)
MIGRATIONS_V2: list[tuple[str, str]] = [
    ("reference_audio", "TEXT"),
    ("style", "TEXT NOT NULL DEFAULT '{}'"),
    ("metadata", "TEXT NOT NULL DEFAULT '{}'"),
]

# ── DDL: voice_models (引擎模型/缓存路径登记) ──
DDL_VOICE_MODELS = f"""
CREATE TABLE IF NOT EXISTS {TABLE_VOICE_MODELS} (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    voice_id    TEXT    NOT NULL,
    engine      TEXT    NOT NULL,
    model_path  TEXT,
    cache_path  TEXT,
    hash        TEXT,
    loaded      INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now')),
    FOREIGN KEY (voice_id) REFERENCES {TABLE_VOICE_PROFILES}(voice_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_voice_models_voice_id ON {TABLE_VOICE_MODELS}(voice_id);
"""

# ── DDL: voice_usage (使用统计) ──
DDL_VOICE_USAGE = f"""
CREATE TABLE IF NOT EXISTS {TABLE_VOICE_USAGE} (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    voice_id     TEXT    NOT NULL UNIQUE,
    usage_count  INTEGER NOT NULL DEFAULT 0,
    last_used    TEXT,
    duration     REAL    NOT NULL DEFAULT 0.0,
    FOREIGN KEY (voice_id) REFERENCES {TABLE_VOICE_PROFILES}(voice_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_voice_usage_voice_id ON {TABLE_VOICE_USAGE}(voice_id);
"""

# 触发器: voice_profiles.updated_at 自动更新
TRG_PROFILES_UPDATED_AT = f"""
CREATE TRIGGER IF NOT EXISTS trg_voice_profiles_updated_at
AFTER UPDATE ON {TABLE_VOICE_PROFILES}
FOR EACH ROW
BEGIN
    UPDATE {TABLE_VOICE_PROFILES}
    SET updated_at = strftime('%Y-%m-%dT%H:%M:%S','now')
    WHERE id = OLD.id;
END;
"""

# 全部 DDL (按顺序执行)
ALL_DDL: list[str] = [
    DDL_VOICE_PROFILES,
    DDL_VOICE_MODELS,
    DDL_VOICE_USAGE,
    TRG_PROFILES_UPDATED_AT,
]


# ── 状态/类型枚举常量 (与 models.py 保持一致, 此处仅作 schema 层参考) ──
# status: profile 生命周期状态
STATUS_CREATING: str = "creating"
STATUS_READY: str = "ready"
STATUS_ACTIVE: str = "active"
STATUS_DISABLED: str = "disabled"
STATUS_DELETED: str = "deleted"
# V2.3-Phase4 生命周期归档
STATUS_INACTIVE: str = "inactive"
STATUS_ARCHIVED: str = "archived"

# type: 声音归属类型
TYPE_CHARACTER: str = "character"
TYPE_USER: str = "user"
TYPE_SYSTEM: str = "system"

# engine: 引擎类型 (对齐 TTS Adapter engine_type)
ENGINE_QWEN3: str = "qwen3"
ENGINE_GPT_SOVITS: str = "gpt_sovits"
ENGINE_EDGE: str = "edge"
