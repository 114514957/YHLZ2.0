"""
YHLZ Embodied AI V6.1.1 - 情绪审计 (Emotion Audit)

职责:
    - 所有情绪变化必须记录: 时间 / 原因 / 输入事件 / 前状态 / 后状态
    - 禁止静默修改

设计原则:
    - 独立审计 (情绪全程可回溯)
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
    """情绪审计操作异常"""


# 审计动作白名单
EMOTION_AUDIT_ACTIONS: List[str] = [
    "update",    # 事件更新
    "decay",     # 自然衰减
    "reset",     # 重置
    "restore",   # 快照恢复
]


class EmotionAudit:
    """情绪审计器

    用法:
        audit = EmotionAudit()
        audit.record(action="update", detail="success",
                     ref_id="em_1")
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
        """记录一次情绪操作"""
        if action not in EMOTION_AUDIT_ACTIONS:
            raise AuditError(
                f"非法审计动作: {action} "
                f"(可选: {EMOTION_AUDIT_ACTIONS})"
            )
        entry = {
            "audit_id": "ema_" + uuid.uuid4().hex[:8],
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
    "EMOTION_AUDIT_ACTIONS",
    "EmotionAudit",
]
