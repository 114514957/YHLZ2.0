"""
YHLZ Embodied AI V8.0 - 演化建议 (Evolution Proposal)

职责:
    - 最高原则修改建议 (Constitution Evolution)
    - 禁止自动应用 (永远需人工审批)

原则 (成长 ≠ 自我修改):
    - AI 可以提出演化建议
    - 禁止自动修改最高原则
    - 建议必须经人工审批

设计原则:
    - 纯规则 (可解释)
    - 建议永不自动应用
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class EvolutionProposalError(Exception):
    """演化建议操作异常"""


# 建议状态 (可解释)
PROPOSAL_STATUS: list = [
    "pending_review",    # 待审批
    "approved",          # 已批准 (仅标记, 应用需人工)
    "rejected",          # 已拒绝
]


class EvolutionProposal:
    """演化建议器 (最高原则修改建议, 永不自动应用)

    用法:
        proposal = EvolutionProposal()
        p = proposal.propose("修改原则X", "理由", "user")
        r = proposal.decide(p["proposal_id"], "reject")
    """

    def __init__(self, enabled: bool = True,
                 max_records: int = 200):
        if max_records <= 0:
            raise EvolutionProposalError(
                f"max_records 必须 > 0, 当前: {max_records}"
            )
        self._lock = threading.RLock()
        self._enabled = bool(enabled)
        self._max_records = int(max_records)
        self._proposals: list = []

    # ── 提出建议 ─────────────────────────────────────────────────
    def propose(
        self,
        change: str,
        reason: str = "",
        operator: str = "system",
        now: Optional[float] = None,
    ) -> Dict[str, Any]:
        """提出演化建议 (永不自动应用)"""
        with self._lock:
            now = now if now is not None else time.time()
            if not self._enabled:
                return {
                    "mode": "error_frame",
                    "ok": False,
                    "reason": "演化建议停用",
                }
            proposal = {
                "proposal_id": "ep_" +
                uuid.uuid4().hex[:8],
                "change": str(change),
                "reason": str(reason),
                "operator": str(operator),
                "status": "pending_review",
                "created_at": now,
                "auto_applied": False,
            }
            self._proposals.append(proposal)
            if len(self._proposals) > self._max_records:
                self._proposals = \
                    self._proposals[-self._max_records:]
            return dict(proposal)

    # ── 审批决策 ─────────────────────────────────────────────────
    def decide(
        self,
        proposal_id: str,
        decision: str,
        reviewer: str = "human",
        now: Optional[float] = None,
    ) -> Dict[str, Any]:
        """审批决策 (批准仅标记, 应用永远需人工)"""
        if decision not in ("approve", "reject"):
            raise EvolutionProposalError(
                f"非法决策: {decision} "
                f"(可选: approve/reject)"
            )
        with self._lock:
            now = now if now is not None else time.time()
            for p in self._proposals:
                if p["proposal_id"] == proposal_id:
                    p["status"] = (
                        "approved" if decision == "approve"
                        else "rejected"
                    )
                    p["decided_at"] = now
                    p["reviewer"] = str(reviewer)
                    return {
                        "mode": "rule_based",
                        "proposal_id": proposal_id,
                        "decision": decision,
                        "auto_applied": False,
                        "reason": (
                            "批准仅标记, 最高原则修改仍需"
                            "人工执行" if decision == "approve"
                            else "已拒绝"
                        ),
                    }
            raise EvolutionProposalError(
                f"建议不存在: {proposal_id}"
            )

    # ── 查询 ─────────────────────────────────────────────────────
    def pending(self, limit: int = 50) -> Dict[str, Any]:
        """待审批建议"""
        with self._lock:
            items = [
                dict(p) for p in self._proposals
                if p["status"] == "pending_review"
            ]
            if limit > 0:
                items = items[:limit]
            return {
                "mode": "rule_based",
                "pending_count": len(items),
                "items": items,
            }

    def stats(self) -> Dict[str, Any]:
        """演化建议统计"""
        with self._lock:
            by_status: Dict[str, int] = {}
            for p in self._proposals:
                by_status[p["status"]] = by_status.get(
                    p["status"], 0,
                ) + 1
            return {
                "mode": "rule_based",
                "enabled": self._enabled,
                "proposal_count": len(self._proposals),
                "by_status": by_status,
            }

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = len(self._proposals)
            self._proposals.clear()
            return n


__all__ = [
    "PROPOSAL_STATUS",
    "EvolutionProposal",
    "EvolutionProposalError",
]
