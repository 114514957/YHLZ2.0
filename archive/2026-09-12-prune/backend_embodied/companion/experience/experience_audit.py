"""
YHLZ Embodied AI V5.7 - 经历审计 (Experience Audit)

职责:
    - 审计每次经历操作: store / update / decay / forget / query
    - 记录: 操作类型 / 记录 ID / 触发 / 结果

设计原则:
    - 独立审计 (可追踪所有经历变化)
    - 只记录操作元数据 (不记录完整内容)
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
    """经历审计操作异常"""


# 审计动作白名单
AUDIT_ACTIONS_EXP: List[str] = [
    "store",      # 存储经历
    "retrieve",   # 检索经历
    "update",     # 更新经历
    "decay",      # 价值衰减
    "forget",     # 遗忘经历
    "query",      # 查询经历
    "extract",    # 抽取经验
]


class ExperienceAudit:
    """经历审计器

    用法:
        audit = ExperienceAudit(max_records=200)
        audit.record(action="store", record_id=..., trigger=...)
        report = audit.report()
    """

    def __init__(self, max_records: int = 200):
        if max_records <= 0:
            raise AuditError(f"max_records 必须 > 0, 当前: {max_records}")
        self._lock = threading.RLock()
        self._records: List[Dict[str, Any]] = []
        self._max_records = int(max_records)

    def record(
        self,
        action: str,
        record_id: str = "",
        trigger: str = "",
        detail: str = "",
    ) -> Dict[str, Any]:
        """记录一次经历操作"""
        if action not in AUDIT_ACTIONS_EXP:
            raise AuditError(
                f"非法审计动作: {action} (可选: {AUDIT_ACTIONS_EXP})"
            )
        entry = {
            "audit_id": "exp_aud_" + uuid.uuid4().hex[:8],
            "action": action,
            "record_id": record_id,
            "trigger": trigger,
            "detail": detail,
            "timestamp": time.time(),
        }
        with self._lock:
            self._records.append(entry)
            if len(self._records) > self._max_records:
                self._records = self._records[-self._max_records:]
        return entry

    def report(self, limit: int = 100) -> Dict[str, Any]:
        """审计报告 (操作统计 + 近期明细)"""
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
    "AUDIT_ACTIONS_EXP",
    "AuditError",
    "ExperienceAudit",
]
