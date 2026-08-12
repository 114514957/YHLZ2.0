"""
YHLZ Embodied AI V6.0 - 持久化层 (Persistence Layer)

架构:
    JSONLStorage      (统一 JSONL 存储: 原子写 + 校验 + 损坏跳过)
    CompanionSnapshot (全量快照: Version + State + Checksum)
    RestoreManager    (状态恢复: 校验链 + 失败不崩溃)
    PersistenceAudit  (持久化审计)

流程:
    Save: 收集状态 → Snapshot(Checksum) → JSONL
    Restore: Load → Checksum → Schema → Identity → Memory → Activate
"""
from backend.embodied.companion.persistence.persistence_audit import (
    PERSISTENCE_AUDIT_ACTIONS,
    PersistenceAudit,
    PersistenceAuditError,
)
from backend.embodied.companion.persistence.restore import (
    RESTORE_STEPS,
    RestoreError,
    RestoreManager,
)
from backend.embodied.companion.persistence.snapshot import (
    SNAPSHOT_DOMAINS,
    CompanionSnapshot,
    SnapshotError,
)
from backend.embodied.companion.persistence.storage import (
    JSONLStorage,
    REQUIRED_FIELDS,
    StorageError,
)

__all__ = [
    "CompanionSnapshot",
    "JSONLStorage",
    "PERSISTENCE_AUDIT_ACTIONS",
    "PersistenceAudit",
    "PersistenceAuditError",
    "REQUIRED_FIELDS",
    "RESTORE_STEPS",
    "RestoreError",
    "RestoreManager",
    "SNAPSHOT_DOMAINS",
    "SnapshotError",
    "StorageError",
]
