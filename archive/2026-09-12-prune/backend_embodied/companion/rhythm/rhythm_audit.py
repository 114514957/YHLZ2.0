"""
YHLZ Embodied AI V6.1.1 - 节律审计 (Rhythm Audit)

职责:
    - 审计所有自动成长行为: 事件采集 / 自动整理 / 自动快照 / 反思触发 / 跳过

设计原则:
    - 独立审计 (自动行为全程可追踪)
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


class RhythmAuditError(Exception):
    """节律审计操作异常"""


# 审计动作白名单
RHYTHM_AUDIT_ACTIONS: List[str] = [
    "capture",       # 事件自动采集
    "consolidate",   # 自动整理
    "snapshot",      # 自动快照
    "reflection",    # 反思触发
    "skip",          # 条件未达跳过
    "error",         # 失败
]


class RhythmAudit:
    """节律审计器

    用法:
        audit = RhythmAudit()
        audit.record(action="capture", detail="experience_added")
        report = audit.report()
    """

    def __init__(self, max_records: int = 500):
        if max_records <= 0:
            raise RhythmAuditError(
                f"max_records 必须 > 0, 当前: {max_records}"
            )
        self._lock = threading.RLock()
        self._records: List[Dict[str, Any]] = []
        self._max_records = int(max_records)

    def record(self, action: str, detail: str = "",
               ref_id: str = "") -> Dict[str, Any]:
        """记录一次自动行为"""
        if action not in RHYTHM_AUDIT_ACTIONS:
            raise RhythmAuditError(
                f"非法审计动作: {action} "
                f"(可选: {RHYTHM_AUDIT_ACTIONS})"
            )
        entry = {
            "audit_id": "rh_" + uuid.uuid4().hex[:8],
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
    "RHYTHM_AUDIT_ACTIONS",
    "RhythmAudit",
    "RhythmAuditError",
]
