"""
YHLZ Voice Identity System v1.0
Milestone V1.1 - 数据模型与数据库核心

模块结构:
    voice_identity/
    ├── __init__.py      ← 本文件: 统一导出 + 自动初始化入口
    ├── database.py      ← VoiceIdentityDB (sqlite3 + 锁 + CRUD)
    ├── models.py        ← VoiceProfile / VoiceModel / VoiceUsage (Pydantic)
    └── schema.py        ← DDL 与常量

设计要点:
    - 独立 db 文件 (voice_identity.db), 不影响 memories.db / 旧启动
    - 仅在显式调用 init_voice_identity() 或 get_db() 时初始化, 避免导入副作用
    - V1.1 不含 Profile/Registry/Manager/API, 仅为数据层

使用:
    from backend.voice_identity import get_db, VoiceProfile, init_voice_identity
    init_voice_identity()           # 幂等建表 (可选, get_db 会自动调)
    db = get_db()
    db.insert_profile(VoiceProfile(voice_id="yuanheng_default", name="元亨默认"))
"""
from __future__ import annotations

import logging

from backend.voice_identity.database import (
    DEFAULT_DB_PATH,
    VoiceIdentityDB,
    get_db,
    reset_db_instance,
)
from backend.voice_identity.models import (
    VALID_ENGINE,
    VALID_STATUS,
    VALID_TYPE,
    VoiceModel,
    VoiceProfile,
    VoiceUsage,
)
from backend.voice_identity.profile import VoiceProfileError, VoiceProfileStore
from backend.voice_identity.registry import VoiceRegistry, VoiceRegistryError
from backend.voice_identity.manager import VoiceManager, VoiceManagerError
from backend.voice_identity.cache_manager import VoiceCacheManager
from backend.voice_identity.service import VoiceIdentityService, VoiceIdentityServiceError
from backend.voice_identity.clone import (
    AudioInfo,
    CloneResult,
    Err,
    Ok,
    Result,
    VoiceClonePipeline,
    VoiceFeature,
    analyze_voice,
    validate_audio,
)
from backend.voice_identity.adapter import (
    GPTSoVITSAdapter,
    Qwen3TTSAdapter,
    build_adapter,
    list_adapters,
    register_adapter,
)
from backend.voice_identity.adapter.config import (
    VoiceCloneConfig,
    load_config,
    build_adapter_from_config,
)
from backend.voice_identity.batch import (
    BatchTaskError,
    CloneTask,
    TaskQueue,
    TaskStatus,
    TaskStore,
    get_task_queue,
    get_task_store,
    reset_task_queue,
    reset_task_store,
)
from backend.voice_identity.dedup import (
    DEFAULT_SIMILARITY_THRESHOLD,
    DuplicateResult,
    VoiceDeduplicator,
    compute_audio_hash,
    compute_feature_similarity,
)
from backend.voice_identity.audit import (
    AuditEntry,
    AuditLogger,
    PermissionError,
    VoicePermission,
    get_audit_logger,
    reset_audit_logger,
)
from backend.voice_identity.permission import (
    PermissionChecker,
    get_actor_id,
    get_permission_checker,
    reset_permission_checker,
)
from backend.voice_identity.voice_lifecycle import (
    CleanupReport,
    LifecycleResult,
    VoiceLifecycle,
    get_lifecycle,
    reset_lifecycle,
)
from backend.voice_identity.voice_security import (
    VoiceSecurityChecker,
    VoiceSecurityConfig,
    SecurityReport,
    SecurityViolation,
    check_audio_security,
    compute_file_hash,
    get_security_checker,
    reset_security_checker,
)
from backend.voice_identity.metrics import (
    MetricsCollector,
    get_metrics,
    record_clone,
    record_adapter_error,
    render_prometheus,
    reset_metrics,
)
from backend.voice_identity import schema

logger = logging.getLogger(__name__)

__all__ = [
    # 数据库
    "VoiceIdentityDB",
    "get_db",
    "reset_db_instance",
    "init_voice_identity",
    "DEFAULT_DB_PATH",
    # 模型
    "VoiceProfile",
    "VoiceModel",
    "VoiceUsage",
    # Profile 业务层 (V1.2)
    "VoiceProfileStore",
    "VoiceProfileError",
    # Registry 发现层 (V1.3)
    "VoiceRegistry",
    "VoiceRegistryError",
    # Manager 生命周期 (V1.4)
    "VoiceManager",
    "VoiceManagerError",
    # Cache 缓存管理 (V1.5)
    "VoiceCacheManager",
    # Service 统一入口 (V1.6)
    "VoiceIdentityService",
    "VoiceIdentityServiceError",
    # V2.1 克隆流水线
    "VoiceClonePipeline",
    "CloneResult",
    "AudioInfo",
    "VoiceFeature",
    "Result",
    "Ok",
    "Err",
    "validate_audio",
    "analyze_voice",
    # V2.2 TTS Adapter
    "TTSAdapter",
    "VoiceCacheInfo",
    "Qwen3TTSAdapter",
    "GPTSoVITSAdapter",
    "build_adapter",
    "list_adapters",
    "register_adapter",
    "VoiceCloneConfig",
    "load_config",
    "build_adapter_from_config",
    # Phase 3.1 批量克隆
    "CloneTask",
    "TaskQueue",
    "TaskStatus",
    "BatchTaskError",
    "get_task_queue",
    "reset_task_queue",
    # V2.3-Phase2 任务持久化
    "TaskStore",
    "get_task_store",
    "reset_task_store",
    # Phase 3.2 声音去重
    "DuplicateResult",
    "VoiceDeduplicator",
    "compute_audio_hash",
    "compute_feature_similarity",
    "DEFAULT_SIMILARITY_THRESHOLD",
    # Phase 3.3 安全与审计
    "AuditEntry",
    "AuditLogger",
    "VoicePermission",
    "PermissionError",
    "get_audit_logger",
    "reset_audit_logger",
    # V2.3-Phase3 API 权限校验
    "PermissionChecker",
    "get_actor_id",
    "get_permission_checker",
    "reset_permission_checker",
    # V2.3-Phase4 生命周期管理
    "VoiceLifecycle",
    "LifecycleResult",
    "CleanupReport",
    "get_lifecycle",
    "reset_lifecycle",
    # V2.3-Phase8 监控系统
    "MetricsCollector",
    "get_metrics",
    "record_clone",
    "record_adapter_error",
    "render_prometheus",
    "reset_metrics",
    # V2.3-Phase9 安全增强
    "VoiceSecurityChecker",
    "VoiceSecurityConfig",
    "SecurityReport",
    "SecurityViolation",
    "check_audio_security",
    "compute_file_hash",
    "get_security_checker",
    "reset_security_checker",
    # 枚举
    "VALID_STATUS",
    "VALID_TYPE",
    "VALID_ENGINE",
    # schema
    "schema",
]

__version__ = "2.3.0"


def init_voice_identity(db_path: str | None = None) -> VoiceIdentityDB:
    """显式初始化 Voice Identity 数据库 (幂等)

    - 首次调用: 建立连接 + 建表 + 写 schema 版本
    - 后续调用: 复用单例 (db_path 参数仅首次生效)
    - 安全: 不触碰任何 TTS 引擎 / memories.db / 启动流程
    """
    return get_db(db_path)


def health() -> dict:
    """便捷健康检查 (V1.7 审计用)"""
    try:
        return get_db().health()
    except Exception as e:
        return {"ok": False, "error": str(e)}
