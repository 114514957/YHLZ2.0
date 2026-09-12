"""
YHLZ Embodied AI V6.8 - 智能调用审计 (Inference Audit)

职责:
    - 记录所有智能调用 (可查询/可追踪/可回放)
    - 结构: {time, task, route, provider, reason, result,
      validation}

设计原则:
    - 独立审计 (全程可追溯)
    - 不可删除 (仅 clear 供测试隔离)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class AuditError(Exception):
    """智能调用审计操作异常"""


class InferenceAudit:
    """智能调用审计器

    用法:
        audit = InferenceAudit()
        audit.record(task="...", route="LOCAL", ...)
        report = audit.report()
    """

    def __init__(self, max_records: int = 2000,
                 enabled: bool = True):
        if max_records <= 0:
            raise AuditError(
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
        route: str = "",
        provider: str = "",
        reason: str = "",
        result: Optional[Dict[str, Any]] = None,
        validation: Optional[Dict[str, Any]] = None,
        now: Optional[float] = None,
    ) -> Dict[str, Any]:
        """记录一次智能调用"""
        if not self._enabled:
            return {}
        entry = {
            "audit_id": "ia_" + uuid.uuid4().hex[:8],
            "time": now if now is not None else time.time(),
            "task": str(task),
            "route": str(route),
            "provider": str(provider),
            "reason": str(reason),
            "result": dict(result or {}),
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
        by_route: Dict[str, int] = {}
        by_provider: Dict[str, int] = {}
        for r in records:
            by_route[r["route"]] = by_route.get(
                r["route"], 0,
            ) + 1
            by_provider[r["provider"]] = by_provider.get(
                r["provider"], 0,
            ) + 1
        recent = list(reversed(records))
        if limit > 0:
            recent = recent[:limit]
        return {
            "mode": "rule_based",
            "total": len(records),
            "by_route": by_route,
            "by_provider": by_provider,
            "recent": recent,
        }

    def replay(self, limit: int = 100) -> Dict[str, Any]:
        """回放记录 (可追踪调用序列)"""
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
                        "route": r["route"],
                        "provider": r["provider"],
                        "reason": r["reason"],
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
    "AuditError",
    "InferenceAudit",
]
