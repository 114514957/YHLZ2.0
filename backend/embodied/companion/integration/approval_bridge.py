"""
YHLZ Embodied AI V5.9 - 审批桥接 (Approval Bridge)

职责:
    - 接入 V5.8 ImprovementProposalEngine 审批流
    - 创造方案 (Creative Proposal) 同样必须审批后才能执行
    - 提供: 审批镜像 / 执行资格检查 / 审批状态查询

设计原则:
    - Proposal ≠ Action: 禁止自动执行 (审批是硬门槛)
    - 创造模块禁止修改核心人格 / 目标
    - 只读查询 + 审批状态同步
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class ApprovalBridgeError(Exception):
    """审批桥接操作异常"""


class ApprovalBridge:
    """审批桥接 (创造方案 → V5.8 审批流)

    用法:
        bridge = ApprovalBridge(improvement_engine)
        mirror = bridge.submit(proposal)
        ok = bridge.can_execute(proposal_id)
    """

    def __init__(self, improvement_engine=None):
        self._lock = threading.RLock()
        self._engine = improvement_engine

    # ── 审批要求 ──────────────────────────────────────────────────
    def requires_approval(self) -> bool:
        """创造方案必须审批 (恒 True, 安全原则)"""
        return True

    # ── 提交审批镜像 ─────────────────────────────────────────────
    def submit(
        self, proposal: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """在 V5.8 改进建议引擎注册审批镜像

        Args:
            proposal: Creative Proposal dict

        Returns:
            V5.8 Improvement Proposal dict (或 None 未接入)
        """
        with self._lock:
            if self._engine is None:
                return None
            try:
                return self._engine.create(
                    trigger=str(proposal.get("title", ""))[:40],
                    suggestion=(
                        f"创造方案: {proposal.get('idea', '')[:80]}"
                    ),
                    basis=(
                        f"机会 {proposal.get('opportunity_id', '')}, "
                        f"证据 {len(proposal.get('evidence', []) or [])} 条"
                    ),
                    expected_impact=proposal.get("expected_value", ""),
                    risk=proposal.get("risk", "low"),
                )
            except Exception as e:
                logger.warning(f"[ApprovalBridge] 审批镜像提交失败: {e}")
                return None

    # ── 执行资格检查 ─────────────────────────────────────────────
    def can_execute(self, proposal_status: str) -> bool:
        """只有 APPROVED 方案可执行 (硬门槛)"""
        return proposal_status == "APPROVED"

    def approval_status(
        self, proposal: Dict[str, Any],
    ) -> Dict[str, Any]:
        """审批状态摘要"""
        status = proposal.get("status", "PENDING")
        return {
            "mode": "rule_based",
            "proposal_id": proposal.get("proposal_id", ""),
            "status": status,
            "requires_approval": self.requires_approval(),
            "can_execute": self.can_execute(status),
            "reason": (
                "只有 APPROVED 方案可执行, 禁止自动执行"
                if self.requires_approval() else ""
            ),
        }

    def stats(self) -> Dict[str, Any]:
        """桥接统计"""
        by_status: Dict[str, int] = {}
        if self._engine is not None:
            try:
                by_status = self._engine.stats().get("by_status", {})
            except Exception:
                by_status = {}
        return {
            "mode": "rule_based",
            "approval_connected": self._engine is not None,
            "requires_approval": self.requires_approval(),
            "improvement_by_status": by_status,
        }


__all__ = [
    "ApprovalBridge",
    "ApprovalBridgeError",
]
