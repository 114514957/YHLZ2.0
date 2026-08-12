"""
YHLZ Embodied AI V6.0 - 持久化审计 (Persistence Audit)

职责:
    - 审计所有持久化操作: 保存/加载/恢复/激活/跳过/校验/整理/回收
    - 追踪: 每个域保存/恢复状态, 损坏跳过, 版本不兼容

设计原则:
    - 独立审计 (所有持久化可回溯)
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


class PersistenceAuditError(Exception):
    """持久化审计操作异常"""


# 审计动作白名单
PERSISTENCE_AUDIT_ACTIONS: List[str] = [
    "save",         # 保存快照
    "load",         # 加载快照
    "restore",      # 恢复
    "activate",     # 激活域
    "skip",         # 跳过域/损坏行
    "error",        # 失败
    "verify",       # 校验
    "consolidate",  # 记忆整理
    "archive",      # 归档
    "recycle",      # 回收
]


class PersistenceAudit:
    """持久化审计器

    用法:
        audit = PersistenceAudit()
        audit.record(action="save", detail="snap_xxx",
                     ref_id="snap_xxx")
        report = audit.report()
    """

    def __init__(self, max_records: int = 500):
        if max_records <= 0:
            raise PersistenceAuditError(
                f"max_records 必须 > 0, 当前: {max_records}"
            )
        self._lock = threading.RLock()
        self._records: List[Dict[str, Any]] = []
        self._max_records = int(max_records)

    def record(self, action: str, detail: str = "",
               ref_id: str = "") -> Dict[str, Any]:
        """记录一次持久化操作"""
        if action not in PERSISTENCE_AUDIT_ACTIONS:
            raise PersistenceAuditError(
                f"非法审计动作: {action} "
                f"(可选: {PERSISTENCE_AUDIT_ACTIONS})"
            )
        entry = {
            "audit_id": "pa_" + uuid.uuid4().hex[:8],
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

    def by_action(self, action: str) -> List[Dict[str, Any]]:
        """按动作查询"""
        if action not in PERSISTENCE_AUDIT_ACTIONS:
            raise PersistenceAuditError(
                f"非法审计动作: {action} "
                f"(可选: {PERSISTENCE_AUDIT_ACTIONS})"
            )
        with self._lock:
            return [
                dict(r) for r in self._records
                if r["action"] == action
            ]

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = len(self._records)
            self._records.clear()
            return n


__all__ = [
    "PERSISTENCE_AUDIT_ACTIONS",
    "PersistenceAudit",
    "PersistenceAuditError",
]
