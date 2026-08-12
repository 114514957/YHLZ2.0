"""
YHLZ Embodied AI V9.0 - 研究审计 (Research Audit)

职责:
    - 记录: {time, question, source, method, result,
      validation}
    - 全过程可追踪

设计原则:
    - 独立审计 (可查询/可回放)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ResearchAuditError(Exception):
    """研究审计操作异常"""


class ResearchAudit:
    """研究审计器

    用法:
        audit = ResearchAudit()
        audit.record(question="...", source="local",
                     method="acquisition", result="...",
                     validation={"ok": True})
    """

    def __init__(self, max_records: int = 2000,
                 enabled: bool = True):
        if max_records <= 0:
            raise ResearchAuditError(
                f"max_records 必须 > 0, 当前: {max_records}"
            )
        self._lock = threading.RLock()
        self._records: List[Dict[str, Any]] = []
        self._max_records = int(max_records)
        self._enabled = bool(enabled)

    # ── 记录 ─────────────────────────────────────────────────────
    def record(
        self,
        question: str = "",
        source: str = "",
        method: str = "",
        result: str = "",
        validation: Optional[Dict[str, Any]] = None,
        now: Optional[float] = None,
    ) -> Dict[str, Any]:
        """记录一次研究行为"""
        if not self._enabled:
            return {}
        entry = {
            "audit_id": "ra_" + uuid.uuid4().hex[:8],
            "time": now if now is not None else time.time(),
            "question": str(question),
            "source": str(source),
            "method": str(method),
            "result": str(result),
            "validation": dict(validation or {}),
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
        by_source: Dict[str, int] = {}
        by_method: Dict[str, int] = {}
        for r in records:
            by_source[r["source"]] = by_source.get(
                r["source"], 0,
            ) + 1
            by_method[r["method"]] = by_method.get(
                r["method"], 0,
            ) + 1
        recent = list(reversed(records))
        if limit > 0:
            recent = recent[:limit]
        return {
            "mode": "rule_based",
            "total": len(records),
            "by_source": by_source,
            "by_method": by_method,
            "recent": recent,
        }

    def replay(self, limit: int = 100) -> Dict[str, Any]:
        """回放 (研究过程可追踪)"""
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
                        "question": r["question"],
                        "source": r["source"],
                        "method": r["method"],
                        "validation_ok": (
                            r["validation"].get("ok", None)
                            if r["validation"] else None
                        ),
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
    "ResearchAudit",
    "ResearchAuditError",
]
