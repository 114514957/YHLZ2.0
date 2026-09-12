"""
YHLZ Embodied AI V6.2 - 表达审计 (Expression Audit)

职责:
    - 审计所有表达建议生成 (可回溯)

设计原则:
    - 独立审计 (表达全程可追踪)
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
    """表达审计操作异常"""


# 审计动作白名单
EXPRESSION_AUDIT_ACTIONS: List[str] = [
    "generate",  # 生成表达建议
    "status",    # 状态查询
]


class ExpressionAudit:
    """表达审计器

    用法:
        audit = ExpressionAudit()
        audit.record(action="generate", detail="more_positive")
        report = audit.report()
    """

    def __init__(self, max_records: int = 500):
        if max_records <= 0:
            raise AuditError(
                f"max_records 必须 > 0, 当前: {max_records}"
            )
        self._lock = threading.RLock()
        self._records: List[Dict[str, Any]] = []
        self._max_records = int(max_records)

    def record(self, action: str, detail: str = "",
               ref_id: str = "") -> Dict[str, Any]:
        """记录一次表达操作"""
        if action not in EXPRESSION_AUDIT_ACTIONS:
            raise AuditError(
                f"非法审计动作: {action} "
                f"(可选: {EXPRESSION_AUDIT_ACTIONS})"
            )
        entry = {
            "audit_id": "exa_" + uuid.uuid4().hex[:8],
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
    "AuditError",
    "EXPRESSION_AUDIT_ACTIONS",
    "ExpressionAudit",
]
