"""
YHLZ Embodied AI V6.5 - 受控成长应用器 (Growth Applier)

职责:
    - 只有 approved=true 才允许应用
    - 流程: Proposal → Evaluation → Approval → Apply → Audit → Snapshot
    - 记录: Before / Change / Reason / After / Verification

原则 (成长不是自我修改):
    - 允许: 优化建议 / 总结规律 / 调整策略参数
    - 禁止: 修改核心人格 / 价值观 / 安全规则 / 权限

设计原则:
    - 应用必须经 Identity Guard (不可变字段拦截)
    - 每次应用记录 before/after (可追溯)
    - 纯规则 (无黑盒)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

from backend.embodied.companion.growth.growth_audit import (
    GrowthAudit,
)

logger = logging.getLogger(__name__)


class ApplierError(Exception):
    """成长应用操作异常"""


class GrowthApplier:
    """受控成长应用器

    用法:
        applier = GrowthApplier(guard_fn)
        result = applier.apply(proposal, evaluation,
                               change_fn, before_state)
    """

    def __init__(
        self,
        audit: Optional[GrowthAudit] = None,
        auto_apply: bool = False,
    ):
        self._lock = threading.RLock()
        self._audit = audit or GrowthAudit()
        self._auto_apply = bool(auto_apply)
        self._applied: List[Dict[str, Any]] = []

    # ── 应用主入口 ───────────────────────────────────────────────
    def apply(
        self,
        proposal: Dict[str, Any],
        evaluation: Dict[str, Any],
        before_state: Dict[str, Any],
        change_fn=None,
        guard_fn=None,
        now: Optional[float] = None,
    ) -> Dict[str, Any]:
        """受控应用 (仅 approved)

        Args:
            proposal: 成长建议
            evaluation: 评估结果 (approved 必须 True)
            before_state: 应用前状态 (Identity Guard 检查)
            change_fn: 变更回调 (应用具体调整)
            guard_fn: 身份守护回调 (可选, 二次确认)

        Returns:
            {
                'apply_id', 'status', 'reason', 'before',
                'after', 'verification', 'mode',
            }
        """
        with self._lock:
            now = now if now is not None else time.time()
            pid = proposal.get("id", "")
            # 1. 硬门槛: 必须 approved
            if not evaluation.get("approved", False):
                return self._finish(
                    pid, "blocked", "未经批准, 禁止应用",
                    before_state, before_state, now,
                )
            # 2. 默认禁止自动应用 (配置开启才自动)
            if not self._auto_apply and change_fn is None:
                return self._finish(
                    pid, "pending_confirm",
                    "默认禁止自动成长修改, 需人工确认",
                    before_state, before_state, now,
                )
            # 3. Identity Guard 二次确认 (可选回调)
            if guard_fn is not None:
                try:
                    guard_ok, guard_reason = guard_fn(proposal)
                except Exception as e:
                    guard_ok, guard_reason = False, str(e)
                if not guard_ok:
                    return self._finish(
                        pid, "blocked",
                        f"身份守护拦截: {guard_reason}",
                        before_state, before_state, now,
                    )
            # 4. 执行变更
            after_state = dict(before_state)
            if change_fn is not None:
                try:
                    result = change_fn(before_state, proposal)
                    if isinstance(result, dict):
                        after_state.update(result)
                except Exception as e:
                    logger.warning(f"[Growth] 变更执行失败: {e}")
                    return self._finish(
                        pid, "apply_failed", f"变更失败: {e}",
                        before_state, before_state, now,
                    )
            # 5. 验证 (不可变字段未变)
            verification = self._verify(before_state, after_state)
            status = "applied" if verification["ok"] else "rejected"
            result = self._finish(
                pid, status, verification["reason"],
                before_state, after_state, now,
                verification=verification,
            )
            # 6. 审计
            self._audit.record(
                proposal_id=pid,
                before=before_state,
                decision=status,
                after=after_state,
            )
            return result

    # ── 验证 (可解释) ───────────────────────────────────────────
    @staticmethod
    def _verify(before: Dict[str, Any],
                after: Dict[str, Any]) -> Dict[str, Any]:
        """验证: 不可变字段未变化"""
        changed_immutable = []
        for field in ("mission", "core_value", "base_personality",
                      "safety_rules", "permission"):
            if before.get(field) != after.get(field):
                changed_immutable.append(field)
        if changed_immutable:
            return {
                "ok": False,
                "reason": f"不可变字段被修改: {changed_immutable}",
            }
        return {"ok": True, "reason": "不可变字段未变化"}

    def _finish(self, pid, status, reason, before, after,
                now, verification=None) -> Dict[str, Any]:
        result = {
            "apply_id": "ga_" + uuid.uuid4().hex[:8],
            "proposal_id": pid,
            "status": status,
            "reason": reason,
            "before": dict(before),
            "after": dict(after),
            "verification": verification or {
                "ok": status == "applied",
                "reason": reason,
            },
            "mode": "rule_based",
            "applied_at": now,
        }
        self._applied.append(result)
        return dict(result)

    # ── 查询 ─────────────────────────────────────────────────────
    def stats(self) -> Dict[str, Any]:
        """应用统计"""
        with self._lock:
            applied = list(self._applied)
        by_status: Dict[str, int] = {}
        for a in applied:
            by_status[a["status"]] = by_status.get(
                a["status"], 0,
            ) + 1
        return {
            "mode": "rule_based",
            "apply_count": len(applied),
            "by_status": by_status,
            "applied_count": by_status.get("applied", 0),
            "blocked_count": by_status.get("blocked", 0),
        }

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = len(self._applied)
            self._applied.clear()
            self._audit.clear()
            return n


__all__ = [
    "ApplierError",
    "GrowthApplier",
]
