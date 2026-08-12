"""
YHLZ Embodied AI V6.4 - 反思评估器 (Reflection Evaluator)

职责:
    - 感知后的深度评估 (Advisor, 非决策者)
    - 输入: Perception Candidate + 已有知识
    - 输出: {reflection_score, pattern, contradiction,
            value_hint, reason}

原则 (Reflection 不是决策者):
    - Reflection Evaluator 只能提供: 分析/评分/风险提示/价值建议
    - 不能直接写入 Memory (Memory Gate 是 Authority)

设计原则:
    - 纯规则 (无黑盒)
    - 评估可解释 (每维 reason)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

from backend.embodied.companion.perception.memory_gate.reflection.reflection_audit import (
    ReflectionAudit,
)
from backend.embodied.companion.perception.memory_gate.reflection.reflection_rules import (
    ReflectionRules,
)

logger = logging.getLogger(__name__)


class EvaluatorError(Exception):
    """反思评估操作异常"""


class ReflectionEvaluator:
    """反思评估器 (Advisor)

    用法:
        evaluator = ReflectionEvaluator()
        result = evaluator.evaluate(candidate, known_experiences)
    """

    def __init__(
        self,
        rules: Optional[ReflectionRules] = None,
        audit: Optional[ReflectionAudit] = None,
        enabled: bool = True,
    ):
        self._lock = threading.RLock()
        self._rules = rules or ReflectionRules()
        self._audit = audit or ReflectionAudit()
        self._enabled = bool(enabled)
        self._results: List[Dict[str, Any]] = []

    # ── 评估主入口 ───────────────────────────────────────────────
    def evaluate(
        self,
        candidate: Dict[str, Any],
        known_experiences: List[Dict[str, Any]] = None,
        now: Optional[float] = None,
    ) -> Dict[str, Any]:
        """深度评估候选 (Advisor 建议)

        Args:
            candidate: 感知候选
            known_experiences: 已有经历 (一致性/模式对比)

        Returns:
            {
                'evaluation_id', 'reflection_score', 'pattern',
                'contradiction', 'value_hint', 'reason',
                'recommendation', 'dimensions', 'mode',
            }
        """
        with self._lock:
            now = now if now is not None else time.time()
            if not self._enabled:
                return {
                    "evaluation_id": "refe_" + uuid.uuid4().hex[:8],
                    "reflection_score": 0.5,
                    "pattern": "评估停用",
                    "contradiction": "",
                    "value_hint": "",
                    "reason": "反思评估停用 (建议中性)",
                    "recommendation": "neutral",
                    "dimensions": [],
                    "mode": "rule_based",
                }
            if not candidate:
                raise EvaluatorError("候选无效")
            result = self._rules.evaluate(
                candidate, known_experiences,
            )
            # 建议: 评分 + 矛盾 + 风险
            recommendation = "approve"
            reasons: List[str] = []
            if result["contradiction"]:
                recommendation = "reject"
                reasons.append("存在矛盾")
            if float(result["reflection_score"]) < \
                    self._rules.threshold():
                recommendation = "reject"
                reasons.append("评分低于阈值")
            if "风险关键词" in result["reason"] and \
                    "无" not in result["reason"].split(
                        "风险关键词")[-1][:6]:
                recommendation = "reject"
                reasons.append("含风险信号")
            if recommendation == "approve":
                reasons.append("综合评估通过")
            eval_result = {
                "evaluation_id": "refe_" + uuid.uuid4().hex[:8],
                "reflection_score": result["reflection_score"],
                "pattern": result["pattern"],
                "contradiction": result["contradiction"],
                "value_hint": result["value_hint"],
                "reason": result["reason"],
                "recommendation": recommendation,
                "recommendation_reason": "; ".join(reasons),
                "dimensions": result["dimensions"],
                "mode": "rule_based",
                "evaluated_at": now,
            }
            self._results.append(eval_result)
            self._audit.record(
                action="evaluate", detail=recommendation,
                ref_id=eval_result["evaluation_id"],
            )
            return dict(eval_result)

    # ── 查询 ─────────────────────────────────────────────────────
    def stats(self) -> Dict[str, Any]:
        """评估统计"""
        with self._lock:
            results = list(self._results)
        by_rec: Dict[str, int] = {}
        for r in results:
            by_rec[r["recommendation"]] = by_rec.get(
                r["recommendation"], 0,
            ) + 1
        avg = (
            sum(r["reflection_score"] for r in results)
            / len(results) if results else 0.0
        )
        return {
            "mode": "rule_based",
            "evaluated_count": len(results),
            "by_recommendation": by_rec,
            "avg_reflection_score": round(avg, 4),
        }

    def audit_report(self, limit: int = 100) -> Dict[str, Any]:
        """反思审计"""
        return self._audit.report(limit=limit)

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = len(self._results)
            self._results.clear()
            n_audit = self._audit.clear()
            return n + n_audit


__all__ = [
    "EvaluatorError",
    "ReflectionEvaluator",
]
