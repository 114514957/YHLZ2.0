"""
YHLZ Embodied AI V8.0 - 成长策略 (Growth Policy)

职责:
    - 成长建议宪法审查 (Governed Growth)
    - 三检查: 身份 / 安全 / 价值
    - 禁止: 自动修改最高原则

流程:
    Growth Proposal → Constitution Review → Approve/Reject → Apply

设计原则:
    - 纯规则审查 (可解释)
    - 审查不改变审批流程 (Growth Evaluator 仍为执行层)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class GrowthPolicyError(Exception):
    """成长策略操作异常"""


# 宪法不可变信号 (可解释, 禁止自动修改最高原则)
CONSTITUTION_IMMUTABLE_SIGNALS: list = [
    "修改原则", "修改宪法", "自动修改最高原则",
    "修改治理规则", "change principle", "modify constitution",
    "自动应用成长", "无需审批",
]


class GrowthPolicy:
    """成长策略 (建议 → 宪法审查)

    用法:
        policy = GrowthPolicy()
        r = policy.review(growth_proposal)
    """

    def __init__(self, enabled: bool = True):
        self._lock = threading.RLock()
        self._enabled = bool(enabled)
        self._review_count = 0
        self._reject_count = 0

    # ── 审查主入口 ───────────────────────────────────────────────
    def review(
        self,
        proposal: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """成长建议宪法审查

        Args:
            proposal: 成长建议
                {type, description, expected_gain, risk,
                 confidence}

        Returns:
            {
                'ok', 'reason', 'checks', 'mode',
            }
        """
        with self._lock:
            self._review_count += 1
            proposal = proposal or {}
            text = " ".join([
                str(proposal.get("type", "")),
                str(proposal.get("description", "")),
                str(proposal.get("expected_gain", "")),
            ])
            checks: list = []
            # 1. 宪法不可变检查
            constitution_ok = True
            constitution_reason = "不涉及最高原则修改"
            for signal in CONSTITUTION_IMMUTABLE_SIGNALS:
                if signal in text:
                    constitution_ok = False
                    constitution_reason = (
                        f"禁止自动修改最高原则: '{signal}'"
                    )
                    break
            checks.append({
                "name": "constitution",
                "passed": constitution_ok,
                "reason": constitution_reason,
            })
            # 2. 身份检查
            identity_ok = True
            identity_reason = "不涉及身份字段"
            for field in ("mission", "core_value",
                          "base_personality", "safety_rules",
                          "permission", "使命", "价值观",
                          "人格", "安全规则", "权限"):
                if field in text and (
                    "修改" in text or "更改" in text or
                    "change" in text or "modify" in text
                ):
                    identity_ok = False
                    identity_reason = f"涉及身份字段 '{field}'"
                    break
            checks.append({
                "name": "identity",
                "passed": identity_ok,
                "reason": identity_reason,
            })
            # 3. 安全检查
            safety_ok = True
            safety_reason = "不违反安全规则"
            for kw in ("绕过", "关闭权限", "泄露", "自我修改",
                       "非法"):
                if kw in text:
                    safety_ok = False
                    safety_reason = f"涉及安全敏感词 '{kw}'"
                    break
            checks.append({
                "name": "safety",
                "passed": safety_ok,
                "reason": safety_reason,
            })
            # 4. 价值检查 (风险等级)
            risk = str(proposal.get("risk", "low"))
            value_ok = risk in ("low", "medium")
            checks.append({
                "name": "value",
                "passed": value_ok,
                "reason": f"风险等级 '{risk}' "
                          f"{'允许' if value_ok else '拒绝'}",
            })
            ok = all(c["passed"] for c in checks)
            if not ok:
                self._reject_count += 1
            return {
                "mode": "rule_based",
                "ok": ok,
                "reason": (
                    "成长建议通过宪法审查"
                    if ok else
                    "成长建议被宪法审查拒绝"
                ),
                "checks": checks,
            }

    # ── 查询 ─────────────────────────────────────────────────────
    def stats(self) -> Dict[str, Any]:
        """成长策略统计"""
        with self._lock:
            return {
                "mode": "rule_based",
                "enabled": self._enabled,
                "review_count": self._review_count,
                "reject_count": self._reject_count,
            }

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            self._review_count = 0
            self._reject_count = 0
            return 0


__all__ = [
    "CONSTITUTION_IMMUTABLE_SIGNALS",
    "GrowthPolicy",
    "GrowthPolicyError",
]
