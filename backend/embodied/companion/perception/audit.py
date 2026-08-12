"""
YHLZ Embodied AI V6.2 - 感知审计 (Perception Audit)

职责:
    - 审计所有感知行为: 接收 / 验证 / 拒绝 / OCR / 检测 / 写入

设计原则:
    - 独立审计 (感知全程可追踪)
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


class AuditError(Exception):
    """感知审计操作异常"""


# 审计动作白名单
PERCEPTION_AUDIT_ACTIONS: List[str] = [
    "receive",     # 接收感知
    "verify",      # 验证
    "approve",     # 通过
    "reject",      # 拒绝
    "ocr",         # OCR
    "detect",      # 检测
    "memory",      # 写入记忆候选
    "permission",  # 权限拒绝
]


class PerceptionAudit:
    """感知审计器

    用法:
        audit = PerceptionAudit()
        audit.record(action="receive", detail="pe_1")
        report = audit.report()
    """

    def __init__(self, max_records: int = 500,
                 enabled: bool = True):
        if max_records <= 0:
            raise AuditError(
                f"max_records 必须 > 0, 当前: {max_records}"
            )
        self._lock = threading.RLock()
        self._records: List[Dict[str, Any]] = []
        self._max_records = int(max_records)
        self._enabled = bool(enabled)

    def record(self, action: str, detail: str = "",
               ref_id: str = "") -> Dict[str, Any]:
        """记录一次感知操作 (审计关闭时返回空)"""
        if action not in PERCEPTION_AUDIT_ACTIONS:
            raise AuditError(
                f"非法审计动作: {action} "
                f"(可选: {PERCEPTION_AUDIT_ACTIONS})"
            )
        if not self._enabled:
            return {}
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
            "enabled": self._enabled,
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
    "AuditError",
    "PERCEPTION_AUDIT_ACTIONS",
    "PerceptionAudit",
]
