"""
YHLZ Embodied AI V9.5 - 认知审计 (Cognition Audit)

职责:
    - 记录: {time, task, evaluation, error, adjustment}
    - 可查询 / 可回放 / 可审计

设计原则:
    - 独立审计 (全过程可追踪)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class CognitionAuditError(Exception):
    """认知审计操作异常"""


class CognitionAudit:
    """认知审计器

    用法:
        audit = CognitionAudit()
        audit.record(task="...", evaluation="...",
                     error="...", adjustment="...")
    """

    def __init__(self, max_records: int = 2000,
                 enabled: bool = True):
        if max_records <= 0:
            raise CognitionAuditError(
                f"max_records 必须 > 0, 当前: {max_records}"
            )
        self._lock = threading.RLock()
        self._records: List[Dict[str, Any]] = []
        self._max_records = int(max_records)
        self._enabled = bool(enabled)

    # ── 记录 ─────────────────────────────────────────────────────
    def record(
        self,
        task: str = "",
        evaluation: str = "",
        error: str = "",
        adjustment: str = "",
        now: Optional[float] = None,
    ) -> Dict[str, Any]:
        """记录一次认知行为"""
        if not self._enabled:
            return {}
        entry = {
            "audit_id": "mc_" + uuid.uuid4().hex[:8],
            "time": now if now is not None else time.time(),
            "task": str(task),
            "evaluation": str(evaluation),
            "error": str(error),
            "adjustment": str(adjustment),
        }
        with self._lock:
            self._records.append(entry)
            if len(self._records) > self._max_records:
                self._records = self._records[-self._max_records:]
        return dict(entry)

    # ── 查询 ─────────────────────────────────────────────────────
    def report(self, limit: int = 100) -> Dict[str, Any]:
        """审计报告"""
        with self._lock:
            records = list(self._records)
        by_error: Dict[str, int] = {}
        for r in records:
            if r["error"]:
                by_error[r["error"]] = by_error.get(
                    r["error"], 0,
                ) + 1
        recent = list(reversed(records))
        if limit > 0:
            recent = recent[:limit]
        return {
            "mode": "rule_based",
            "total": len(records),
            "by_error": by_error,
            "recent": recent,
        }

    def replay(self, limit: int = 100) -> Dict[str, Any]:
        """回放 (认知过程可追踪)"""
        with self._lock:
            records = list(reversed(self._records))
            if limit > 0:
                records = records[:limit]
            return {
                "mode": "rule_based",
                "replay_count": len(records),
                "sequence": [
                    {
                        "audit_id": r["audit_id"],
                        "time": r["time"],
                        "task": r["task"],
                        "evaluation": r["evaluation"],
                        "error": r["error"],
                        "adjustment": r["adjustment"],
                    }
                    for r in records
                ],
            }

    def stats(self) -> Dict[str, Any]:
        """审计统计"""
        with self._lock:
            return {
                "mode": "rule_based",
                "enabled": self._enabled,
                "record_count": len(self._records),
                "max_records": self._max_records,
            }

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = len(self._records)
            self._records.clear()
            return n


__all__ = [
    "CognitionAudit",
    "CognitionAuditError",
]
