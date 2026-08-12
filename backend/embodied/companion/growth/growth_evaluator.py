"""
YHLZ Embodied AI V6.5 - 成长评估器 (Growth Evaluator)

职责:
    - 判断建议是否安全 (Safety Evaluation)
    - 检查: Identity (是否影响核心身份) / Safety (是否违反规则) /
      Value (是否长期有益)
    - 输出: {approved, reason, score}

原则:
    - 未经批准不能修改
    - 核心身份不可自动修改

设计原则:
    - 纯规则评估 (无黑盒)
    - 三检查可解释
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class EvaluatorError(Exception):
    """成长评估操作异常"""


# 不可变字段 (Identity Guard 核心) (可解释)
IMMUTABLE_FIELDS: List[str] = [
    "mission",            # 使命
    "core_value",         # 核心价值
    "base_personality",   # 基础人格
    "safety_rules",       # 安全规则
    "permission",         # 权限
]

# 安全敏感关键词 (可解释)
SAFETY_KEYWORDS: List[str] = [
    "修改人格", "修改价值观", "修改安全规则", "修改权限",
    "绕过", "关闭权限", "自我修改",
]


class GrowthEvaluator:
    """成长评估器 (建议 → 安全判断)

    用法:
        evaluator = GrowthEvaluator()
        result = evaluator.evaluate(proposal, identity_state)
    """

    def __init__(self, approve_threshold: float = 0.6):
        if not (0.0 <= approve_threshold <= 1.0):
            raise EvaluatorError(
                f"approve_threshold 必须在 [0,1], 当前: "
                f"{approve_threshold}"
            )
        self._lock = threading.RLock()
        self._threshold = float(approve_threshold)
        self._results: List[Dict[str, Any]] = []

    # ── 评估主入口 ───────────────────────────────────────────────
    def evaluate(
        self,
        proposal: Dict[str, Any],
        identity_state: Optional[Dict[str, Any]] = None,
        now: Optional[float] = None,
    ) -> Dict[str, Any]:
        """评估建议安全性

        Args:
            proposal: 成长建议
            identity_state: 身份状态 (不可变字段)

        Returns:
            {
                'evaluation_id', 'approved', 'reason', 'score',
                'checks': [...], 'mode',
            }
        """
        with self._lock:
            now = now if now is not None else time.time()
            identity = identity_state or {}
            checks = {
                "identity": self._check_identity(
                    proposal, identity,
                ),
                "safety": self._check_safety(proposal),
                "value": self._check_value(proposal),
            }
            # 身份检查失败 → 直接拒绝 (硬约束)
            if not checks["identity"]["ok"]:
                approved = False
                reason = checks["identity"]["reason"]
                score = 0.0
            else:
                score = round(sum(
                    c["score"] for c in checks.values()
                ) / 3.0, 4)
                approved = score >= self._threshold and \
                    checks["safety"]["ok"] and \
                    checks["value"]["ok"]
                if not approved and not checks["value"]["ok"]:
                    reason = checks["value"]["reason"]
                elif not checks["safety"]["ok"]:
                    reason = checks["safety"]["reason"]
                else:
                    reason = (
                        f"综合安全评分 {score} "
                        f"{'≥' if approved else '<'} "
                        f"阈值 {self._threshold}"
                    )
            result = {
                "evaluation_id": "ge_" + uuid.uuid4().hex[:8],
                "approved": approved,
                "reason": reason,
                "score": score,
                "checks": [
                    {"name": k, "ok": v["ok"],
                     "score": v["score"],
                     "reason": v["reason"]}
                    for k, v in checks.items()
                ],
                "mode": "rule_based",
                "evaluated_at": now,
            }
            self._results.append(result)
            return dict(result)

    # ── 三检查 (可解释) ─────────────────────────────────────────
    @staticmethod
    def _check_identity(proposal: Dict[str, Any],
                        identity: Dict[str, Any]) -> Dict[str, Any]:
        """身份检查: 建议是否影响核心身份"""
        text = " ".join([
            str(proposal.get("type", "")),
            str(proposal.get("description", "")),
        ])
        # 中文字段名映射 (可解释)
        field_names = {
            "mission": "使命",
            "core_value": "价值观",
            "base_personality": "人格",
            "safety_rules": "安全规则",
            "permission": "权限",
        }
        for field in IMMUTABLE_FIELDS:
            name = field_names.get(field, field)
            if name in text or field in text or \
                    f"修改{name}" in text:
                return {
                    "ok": False, "score": 0.0,
                    "reason": f"建议涉及不可变字段 '{name}'",
                }
        # 建议引用身份字段值 → 需谨慎
        for field in ("mission", "core_value"):
            value = identity.get(field)
            if value and str(value) in text:
                return {
                    "ok": False, "score": 0.0,
                    "reason": f"建议引用核心身份 '{field}'",
                }
        return {
            "ok": True, "score": 0.9,
            "reason": "不影响核心身份",
        }

    @staticmethod
    def _check_safety(proposal: Dict[str, Any]) -> Dict[str, Any]:
        """安全检查: 是否违反规则"""
        text = " ".join([
            str(proposal.get("type", "")),
            str(proposal.get("description", "")),
        ])
        for kw in SAFETY_KEYWORDS:
            if kw in text:
                return {
                    "ok": False, "score": 0.0,
                    "reason": f"涉及安全敏感词 '{kw}'",
                }
        return {
            "ok": True, "score": 0.9,
            "reason": "不违反安全规则",
        }

    @staticmethod
    def _check_value(proposal: Dict[str, Any]) -> Dict[str, Any]:
        """价值检查: 是否长期有益"""
        risk = proposal.get("risk", "low")
        gain = str(proposal.get("expected_gain", ""))
        base = 0.9 if risk == "low" else (
            0.6 if risk == "medium" else 0.3
        )
        if gain:
            base = min(1.0, base + 0.05)
        return {
            "ok": base >= 0.5,
            "score": round(base, 4),
            "reason": f"风险 '{risk}', 预期收益 '{gain[:20]}'",
        }

    # ── 查询 ─────────────────────────────────────────────────────
    def stats(self) -> Dict[str, Any]:
        """评估统计"""
        with self._lock:
            results = list(self._results)
        approved = sum(1 for r in results if r["approved"])
        return {
            "mode": "rule_based",
            "evaluation_count": len(results),
            "approved_count": approved,
            "rejected_count": len(results) - approved,
        }

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = len(self._results)
            self._results.clear()
            return n


__all__ = [
    "EvaluatorError",
    "GrowthEvaluator",
    "IMMUTABLE_FIELDS",
    "SAFETY_KEYWORDS",
]
