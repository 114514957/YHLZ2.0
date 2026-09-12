"""
YHLZ Embodied AI V5.8 - 反思审计 (Reflection Audit)

职责:
    - 审计每次反思/验证/建议操作
    - 追踪: 反思生成 / 模式发现 / 失败分析 / 建议审批

设计原则:
    - 独立审计 (所有成长可回溯)
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


class ReflectionAuditError(Exception):
    """反思审计操作异常"""


# 审计动作白名单
REFLECTION_AUDIT_ACTIONS: List[str] = [
    "reflect",        # 生成反思报告
    "pattern",        # 发现模式
    "failure",        # 失败分析
    "proposal",       # 创建改进建议
    "approve",        # 批准建议
    "reject",         # 拒绝建议
    "execute",        # 执行建议
    "verify",         # 验证经历
    "contradiction",  # 矛盾检测
]


class ReflectionAudit:
    """反思审计器

    用法:
        audit = ReflectionAudit()
        audit.record(action="reflect", detail="报告 ref_xxx")
        report = audit.report()
    """

    def __init__(self, max_records: int = 300):
        if max_records <= 0:
            raise ReflectionAuditError(
                f"max_records 必须 > 0, 当前: {max_records}"
            )
        self._lock = threading.RLock()
        self._records: List[Dict[str, Any]] = []
        self._max_records = int(max_records)

    def record(self, action: str, detail: str = "",
               ref_id: str = "") -> Dict[str, Any]:
        """记录一次反思/验证操作"""
        if action not in REFLECTION_AUDIT_ACTIONS:
            raise ReflectionAuditError(
                f"非法审计动作: {action} "
                f"(可选: {REFLECTION_AUDIT_ACTIONS})"
            )
        entry = {
            "audit_id": "refl_" + uuid.uuid4().hex[:8],
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
    "REFLECTION_AUDIT_ACTIONS",
    "ReflectionAudit",
    "ReflectionAuditError",
]
