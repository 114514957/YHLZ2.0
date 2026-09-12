"""
YHLZ Embodied AI V6.5 - 成长审计 (Growth Audit)

职责:
    - 记录所有成长行为
    - 结构: {before, proposal, decision, after, time}

设计原则:
    - 独立审计 (成长全程可追溯)
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
    """成长审计操作异常"""


class GrowthAudit:
    """成长审计器

    用法:
        audit = GrowthAudit()
        audit.record(proposal_id="gp_1", before={},
                     decision="applied", after={})
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

    def record(
        self,
        proposal_id: str = "",
        before: Dict[str, Any] = None,
        decision: str = "",
        after: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        """记录一次成长行为"""
        if not self._enabled:
            return {}
        entry = {
            "audit_id": "ga_" + uuid.uuid4().hex[:8],
            "proposal_id": proposal_id,
            "before": dict(before or {}),
            "decision": decision,
            "after": dict(after or {}),
            "time": time.time(),
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
        by_decision: Dict[str, int] = {}
        for r in records:
            by_decision[r["decision"]] = by_decision.get(
                r["decision"], 0,
            ) + 1
        recent = list(reversed(records))
        if limit > 0:
            recent = recent[:limit]
        return {
            "mode": "rule_based",
            "total": len(records),
            "by_decision": by_decision,
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
    "GrowthAudit",
]
