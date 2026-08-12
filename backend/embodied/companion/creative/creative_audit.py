"""
YHLZ Embodied AI V5.9 - 创造审计 (Creative Audit)

职责:
    - 审计所有创造行为: 来源经验 / 推理过程 / 决策过程 / 执行结果
    - 追踪: 机会检测 / 价值评估 / 推理 / 方案生成 / 模拟 / 审批 / 执行
    - 为未来 Reflection 提供完整记录

设计原则:
    - 独立审计 (所有创造可回溯)
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


class CreativeAuditError(Exception):
    """创造审计操作异常"""


# 审计动作白名单
CREATIVE_AUDIT_ACTIONS: List[str] = [
    "detect",       # 机会检测
    "evaluate",     # 价值评估
    "reason",       # 创造推理
    "propose",      # 方案生成
    "simulate",     # 执行前模拟
    "approve",      # 批准方案
    "reject",       # 拒绝方案
    "execute",      # 执行方案
    "result",       # 记录结果 (形成经验)
    "persist",      # 持久化
]


class CreativeAudit:
    """创造审计器

    用法:
        audit = CreativeAudit()
        audit.record(action="detect", detail="机会 opp_xxx",
                     ref_id="opp_xxx")
        report = audit.report()
    """

    def __init__(self, max_records: int = 500):
        if max_records <= 0:
            raise CreativeAuditError(
                f"max_records 必须 > 0, 当前: {max_records}"
            )
        self._lock = threading.RLock()
        self._records: List[Dict[str, Any]] = []
        self._max_records = int(max_records)

    def record(self, action: str, detail: str = "",
               ref_id: str = "") -> Dict[str, Any]:
        """记录一次创造操作"""
        if action not in CREATIVE_AUDIT_ACTIONS:
            raise CreativeAuditError(
                f"非法审计动作: {action} "
                f"(可选: {CREATIVE_AUDIT_ACTIONS})"
            )
        entry = {
            "audit_id": "cr_" + uuid.uuid4().hex[:8],
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

    def by_action(self, action: str) -> List[Dict[str, Any]]:
        """按动作查询"""
        if action not in CREATIVE_AUDIT_ACTIONS:
            raise CreativeAuditError(
                f"非法审计动作: {action} "
                f"(可选: {CREATIVE_AUDIT_ACTIONS})"
            )
        with self._lock:
            return [
                dict(r) for r in self._records
                if r["action"] == action
            ]

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = len(self._records)
            self._records.clear()
            return n


__all__ = [
    "CREATIVE_AUDIT_ACTIONS",
    "CreativeAudit",
    "CreativeAuditError",
]
