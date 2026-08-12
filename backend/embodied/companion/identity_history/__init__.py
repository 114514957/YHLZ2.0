"""
YHLZ Embodied AI V6.0 - 身份历史层 (Identity History Layer)

架构:
    IdentitySnapshot  (身份快照: 成长轨迹 + 变化审批)
    IdentityDiff      (身份差异: 字段级分析)
    IdentityAudit     (身份审计: 全程可回溯)

规则:
    - 人格变化必须"提出" (propose), 不能自动修改
    - 使命/核心价值/基础人格为不可变字段
"""
from backend.embodied.companion.identity_history.identity_audit import (
    IDENTITY_AUDIT_ACTIONS,
    IdentityAudit,
    IdentityAuditError,
)
from backend.embodied.companion.identity_history.identity_diff import (
    DiffError,
    IdentityDiff,
    NOISE_FIELDS,
)
from backend.embodied.companion.identity_history.identity_snapshot import (
    APPROVAL_STATUSES,
    IMMUTABLE_FIELDS,
    IdentitySnapshot,
    IdentitySnapshotError,
)

__all__ = [
    "APPROVAL_STATUSES",
    "DiffError",
    "IDENTITY_AUDIT_ACTIONS",
    "IMMUTABLE_FIELDS",
    "IdentityAudit",
    "IdentityAuditError",
    "IdentityDiff",
    "IdentitySnapshot",
    "IdentitySnapshotError",
    "NOISE_FIELDS",
]
