"""
YHLZ Embodied AI V6.0 - 身份审计 (Identity Audit)

职责:
    - 审计所有身份操作: 快照记录/变化提出/审批/恢复/校验
    - 追踪: 身份变化轨迹 (谁提出/谁批准/何时)

设计原则:
    - 独立审计 (身份变化全程可回溯)
    - 只记录操作元数据
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class IdentityAuditError(Exception):
    """身份审计操作异常"""


# 审计动作白名单
IDENTITY_AUDIT_ACTIONS: List[str] = [
    "capture",     # 记录身份快照
    "propose",     # 提出变化
    "approve",     # 批准变化
    "reject",      # 拒绝变化
    "restore",     # 恢复身份
    "verify",      # 身份校验
]


class IdentityAudit:
    """身份审计器

    用法:
        audit = IdentityAudit()
        audit.record(action="propose", detail="idsnap_xxx",
                     ref_id="idsnap_xxx")
        report = audit.report()
    """

    def __init__(self, max_records: int = 300):
        if max_records <= 0:
            raise IdentityAuditError(
                f"max_records 必须 > 0, 当前: {max_records}"
            )
        self._lock = threading.RLock()
        self._records: List[Dict[str, Any]] = []
        self._max_records = int(max_records)

    def record(self, action: str, detail: str = "",
               ref_id: str = "") -> Dict[str, Any]:
        """记录一次身份操作"""
        if action not in IDENTITY_AUDIT_ACTIONS:
            raise IdentityAuditError(
                f"非法审计动作: {action} "
                f"(可选: {IDENTITY_AUDIT_ACTIONS})"
            )
        entry = {
            "audit_id": "ida_" + uuid.uuid4().hex[:8],
            "action": action,
            "detail": detail,
            "ref_id": ref_id,
            "timestamp": time.time(),
        }
        with self._lock:
            self._records.append(entry)
            if len(self._records) > self._max_records:
                self._records = self._records[-self._max_records:]
        return entry

    def report(self, limit: int = 100) -> Dict[str, Any]:
        """审计报告"""
        with self._lock:
            records = list(self._records)
        by_action: Dict[str, int] = {}
        for r in records:
            by_action[r["action"]] = by_action.get(r["action"], 0) + 1
        recent = list(reversed(records))
        if limit > 0:
            recent = recent[:limit]
        return {
            "mode": "rule_based",
            "total": len(records),
            "by_action": by_action,
            "recent": recent,
        }

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = len(self._records)
            self._records.clear()
            return n


__all__ = [
    "IDENTITY_AUDIT_ACTIONS",
    "IdentityAudit",
    "IdentityAuditError",
]
