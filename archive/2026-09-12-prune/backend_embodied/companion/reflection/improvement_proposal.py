"""
YHLZ Embodied AI V5.8 - 改进建议 (Improvement Proposal)

职责:
    - 生成改进建议 (Proposal ≠ Action)
    - 流程: Reflection → Proposal → Verification → Approval → Execution
    - 建议必须经验证与批准才能执行

设计原则:
    - Proposal 只提出, 不执行 (禁止自动行动)
    - 建议需 Approval (approve) 后才可进入执行
    - 可解释: 每建议含 依据/预期/风险
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ProposalError(Exception):
    """改进建议操作异常"""


class ImprovementProposalEngine:
    """改进建议引擎

    用法:
        engine = ImprovementProposalEngine()
        pid = engine.create(trigger="频繁失败", suggestion="调整策略",
                            basis="3 次失败经验")
        engine.approve(pid) / engine.reject(pid)
    """

    def __init__(self, max_proposals: int = 100):
        if max_proposals <= 0:
            raise ProposalError(
                f"max_proposals 必须 > 0, 当前: {max_proposals}"
            )
        self._lock = threading.RLock()
        self._proposals: Dict[str, Dict[str, Any]] = {}
        self._max_proposals = int(max_proposals)

    # ── 创建建议 ──────────────────────────────────────────────────
    def create(
        self,
        trigger: str,
        suggestion: str,
        basis: str = "",
        expected_impact: str = "",
        risk: str = "low",
    ) -> Dict[str, Any]:
        """创建改进建议 (状态: PENDING_APPROVAL)

        Args:
            trigger: 触发情境
            suggestion: 建议内容
            basis: 依据 (经验/模式)
            expected_impact: 预期影响
            risk: 风险 (low/medium/high)

        Returns:
            Proposal dict
        """
        with self._lock:
            if len(self._proposals) >= self._max_proposals:
                raise ProposalError("建议数已达上限")
            pid = "prop_" + uuid.uuid4().hex[:8]
            proposal = {
                "proposal_id": pid,
                "trigger": trigger,
                "suggestion": suggestion,
                "basis": basis,
                "expected_impact": expected_impact,
                "risk": risk,
                "status": "PENDING_APPROVAL",
                "created_at": time.time(),
                "approved_at": 0.0,
                "reason": "",
            }
            self._proposals[pid] = proposal
            return dict(proposal)

    # ── 审批 (Approval) ───────────────────────────────────────────
    def approve(self, proposal_id: str,
                approver: str = "system") -> Dict[str, Any]:
        """批准建议 (→ APPROVED, 可进入执行)"""
        with self._lock:
            p = self._proposals.get(proposal_id)
            if p is None:
                raise ProposalError(f"建议不存在: {proposal_id}")
            if p["status"] != "PENDING_APPROVAL":
                raise ProposalError(
                    f"建议状态 {p['status']} 不能批准"
                )
            p["status"] = "APPROVED"
            p["approved_at"] = time.time()
            p["approver"] = approver
            p["reason"] = f"经 {approver} 批准 (Proposal → Execution)"
            return dict(p)

    def reject(self, proposal_id: str,
               reason: str = "") -> Dict[str, Any]:
        """拒绝建议 (→ REJECTED)"""
        with self._lock:
            p = self._proposals.get(proposal_id)
            if p is None:
                raise ProposalError(f"建议不存在: {proposal_id}")
            p["status"] = "REJECTED"
            p["reason"] = reason or "人工/系统拒绝"
            return dict(p)

    def execute(self, proposal_id: str) -> Dict[str, Any]:
        """标记已执行 (仅 APPROVED 可执行)"""
        with self._lock:
            p = self._proposals.get(proposal_id)
            if p is None:
                raise ProposalError(f"建议不存在: {proposal_id}")
            if p["status"] != "APPROVED":
                raise ProposalError(
                    f"只有 APPROVED 建议可执行, 当前: {p['status']}"
                )
            p["status"] = "EXECUTED"
            p["executed_at"] = time.time()
            return dict(p)

    # ── 查询 ──────────────────────────────────────────────────────
    def get(self, proposal_id: str) -> Optional[Dict[str, Any]]:
        """查询建议"""
        with self._lock:
            p = self._proposals.get(proposal_id)
            return dict(p) if p else None

    def by_status(self, status: str) -> List[Dict[str, Any]]:
        """按状态查询"""
        with self._lock:
            return [
                dict(p) for p in self._proposals.values()
                if p["status"] == status
            ]

    def stats(self) -> Dict[str, Any]:
        """建议统计"""
        with self._lock:
            proposals = list(self._proposals.values())
        by_status: Dict[str, int] = {}
        for p in proposals:
            by_status[p["status"]] = by_status.get(p["status"], 0) + 1
        return {
            "mode": "rule_based",
            "total": len(proposals),
            "by_status": by_status,
            "approved": by_status.get("APPROVED", 0),
            "executed": by_status.get("EXECUTED", 0),
        }

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = len(self._proposals)
            self._proposals.clear()
            return n


__all__ = [
    "ImprovementProposalEngine",
    "ProposalError",
]
