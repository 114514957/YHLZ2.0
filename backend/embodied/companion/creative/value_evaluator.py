"""
YHLZ Embodied AI V5.9 - 价值评估器 (Value Evaluator)

职责:
    - 判断机会是否值得投入创造资源
    - 评价维度 (可解释): Impact / Frequency / User Benefit /
      Feasibility / Risk
    - 输出:
      {value_score, impact, benefit, risk, decision, dimensions[]}

决策规则 (可解释):
    - value_score >= create_threshold → create (值得创造)
    - value_score >= defer_threshold → defer (暂缓观察)
    - 其余 → reject (不值得投入)

设计原则:
    - 发现机会 ≠ 值得创造 (必须经过价值判断)
    - 纯规则评估 (禁止黑盒)
    - 每个维度附 reason (可回溯)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class EvaluationError(Exception):
    """价值评估操作异常"""


# 决策白名单 (可解释)
DECISIONS: List[str] = ["create", "defer", "reject"]

# 权重 (可解释, 和为 1.0)
VALUE_WEIGHTS: Dict[str, float] = {
    "impact": 0.25,       # 影响价值
    "frequency": 0.20,    # 出现频率
    "benefit": 0.20,      # 用户收益
    "feasibility": 0.20,  # 实现可能性
    "risk": 0.15,         # 潜在风险 (1 - risk 参与)
}

# 来源类型 → 影响加成 (可解释)
SOURCE_IMPACT_BONUS: Dict[str, float] = {
    "failure": 0.15,       # 反复失败影响最高
    "repetition": 0.10,    # 重复需求节省成本
    "improvement": 0.05,   # 改进升级
    "pattern": 0.05,       # 规律固化
    "relationship": 0.05,  # 关系个性化
}


class ValueEvaluator:
    """价值评估器 (机会 → 价值评分 + 决策)

    用法:
        evaluator = ValueEvaluator()
        result = evaluator.evaluate(opportunity, relationship)
    """

    def __init__(self, create_threshold: float = 0.6,
                 defer_threshold: float = 0.35):
        if not (0.0 <= create_threshold <= 1.0):
            raise EvaluationError(
                f"create_threshold 必须在 [0,1], 当前: {create_threshold}"
            )
        if not (0.0 <= defer_threshold <= 1.0):
            raise EvaluationError(
                f"defer_threshold 必须在 [0,1], 当前: {defer_threshold}"
            )
        if defer_threshold >= create_threshold:
            raise EvaluationError(
                f"defer_threshold({defer_threshold}) 必须小于 "
                f"create_threshold({create_threshold})"
            )
        self._lock = threading.RLock()
        self._create_threshold = float(create_threshold)
        self._defer_threshold = float(defer_threshold)
        self._results: List[Dict[str, Any]] = []

    # ── 评估主入口 ────────────────────────────────────────────────
    def evaluate(
        self,
        opportunity: Dict[str, Any],
        confirmed_experiences: Optional[List[Dict[str, Any]]] = None,
        relationship: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """评估机会价值 (规则驱动, 可解释)

        Args:
            opportunity: Opportunity Candidate
            confirmed_experiences: 全部 CONFIRMED 经历 (供成功率统计)
            relationship: 关系上下文 (可空, 含 trust)

        Returns:
            {
                'evaluation_id', 'opportunity_id', 'value_score',
                'impact', 'frequency', 'benefit', 'feasibility',
                'risk', 'dimensions': [...], 'decision',
                'decision_reason', 'mode', 'evaluated_at',
            }
        """
        with self._lock:
            if not opportunity or not opportunity.get("opportunity_id"):
                raise EvaluationError("机会候选无效: 缺 opportunity_id")
            experiences = confirmed_experiences or []
            dims = {
                "impact": self._score_impact(opportunity),
                "frequency": self._score_frequency(opportunity),
                "benefit": self._score_benefit(
                    opportunity, relationship,
                ),
                "feasibility": self._score_feasibility(
                    opportunity, experiences,
                ),
                "risk": self._score_risk(opportunity, experiences),
            }
            score = self._value_score(dims)
            decision, reason = self._decide(score, dims)
            result = {
                "evaluation_id": "eval_" + uuid.uuid4().hex[:8],
                "opportunity_id": opportunity["opportunity_id"],
                "value_score": round(score, 4),
                "impact": dims["impact"]["level"],
                "frequency": dims["frequency"]["level"],
                "benefit": dims["benefit"]["level"],
                "feasibility": dims["feasibility"]["level"],
                "risk": dims["risk"]["level"],
                "dimensions": [
                    {"name": k, "level": v["level"],
                     "score": round(v["score"], 4),
                     "reason": v["reason"]}
                    for k, v in dims.items()
                ],
                "decision": decision,
                "decision_reason": reason,
                "mode": "rule_based",
                "evaluated_at": time.time(),
            }
            self._results.append(result)
            return dict(result)

    # ── 维度评分 (可解释) ────────────────────────────────────────
    @staticmethod
    def _score_impact(opportunity: Dict[str, Any]) -> Dict[str, Any]:
        """影响价值: 证据数量 + 来源类型加成"""
        n_evidence = len(opportunity.get("evidence", []) or [])
        bonus = SOURCE_IMPACT_BONUS.get(
            opportunity.get("source_type", ""), 0.0,
        )
        score = min(1.0, 0.35 + 0.15 * n_evidence + bonus)
        if score >= 0.75:
            level = "high"
        elif score >= 0.45:
            level = "medium"
        else:
            level = "low"
        return {
            "score": round(score, 4),
            "level": level,
            "reason": (
                f"{n_evidence} 条证据, 来源 '{opportunity.get('source_type')}' "
                f"加成 {bonus}"
            ),
        }

    @staticmethod
    def _score_frequency(opportunity: Dict[str, Any]) -> Dict[str, Any]:
        """出现频率: 证据数量分级"""
        n = len(opportunity.get("evidence", []) or [])
        if n >= 5:
            score, level = 1.0, "high"
        elif n >= 3:
            score, level = 0.6, "medium"
        else:
            score, level = 0.3, "low"
        return {
            "score": score,
            "level": level,
            "reason": f"证据 {n} 条 (≥5 high / ≥3 medium / 其他 low)",
        }

    @staticmethod
    def _score_benefit(
        opportunity: Dict[str, Any],
        relationship: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """用户收益: 关系信任度 + 来源类型"""
        trust = 0.5
        if relationship:
            trust = float(relationship.get("trust", 0.5))
        base = 0.2 + 0.6 * trust
        if opportunity.get("source_type") == "relationship":
            base = min(1.0, base + 0.1)
        score = round(min(1.0, base), 4)
        if score >= 0.7:
            level = "high"
        elif score >= 0.45:
            level = "medium"
        else:
            level = "low"
        return {
            "score": score,
            "level": level,
            "reason": f"关系信任 {trust}, 来源 '{opportunity.get('source_type')}'",
        }

    @staticmethod
    def _score_feasibility(
        opportunity: Dict[str, Any],
        experiences: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """实现可能性: CONFIRMED 经验成功率"""
        if not experiences:
            score, level, reason = 0.4, "medium", "无经验可参考, 保守评估"
        else:
            success = sum(
                1 for r in experiences
                if str(r.get("result", "")).find("成功") >= 0
                or r.get("type") in ("interaction", "improvement",
                                     "engineering")
            )
            rate = success / len(experiences)
            score = round(min(1.0, 0.3 + 0.7 * rate), 4)
            if score >= 0.7:
                level = "high"
            elif score >= 0.45:
                level = "medium"
            else:
                level = "low"
            reason = f"同类经验成功率 {rate:.0%} ({success}/{len(experiences)})"
        return {"score": score, "level": level, "reason": reason}

    @staticmethod
    def _score_risk(
        opportunity: Dict[str, Any],
        experiences: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """潜在风险: 失败经验比例 (分数越大风险越高)"""
        if not experiences:
            score, level, reason = 0.3, "low", "无经验可参考, 风险保守估计"
        else:
            failures = sum(
                1 for r in experiences if r.get("type") == "failure"
            )
            ratio = failures / len(experiences)
            score = round(min(1.0, ratio), 4)
            if score >= 0.5:
                level = "high"
            elif score >= 0.25:
                level = "medium"
            else:
                level = "low"
            reason = f"失败经验占比 {ratio:.0%} ({failures}/{len(experiences)})"
        return {"score": score, "level": level, "reason": reason}

    # ── 综合评分与决策 (可解释) ──────────────────────────────────
    @staticmethod
    def _value_score(dims: Dict[str, Dict[str, Any]]) -> float:
        """加权价值分: risk 维度按 (1 - risk) 参与"""
        total = 0.0
        for name, weight in VALUE_WEIGHTS.items():
            d = dims[name]
            value = d["score"]
            if name == "risk":
                value = 1.0 - value
            total += weight * value
        return round(min(1.0, total), 4)

    def _decide(
        self, score: float, dims: Dict[str, Dict[str, Any]],
    ) -> tuple:
        """决策规则 (可解释)"""
        if score >= self._create_threshold:
            return "create", (
                f"价值分 {score} ≥ 创造阈值 {self._create_threshold}, "
                f"值得投入创造资源"
            )
        if score >= self._defer_threshold:
            return "defer", (
                f"价值分 {score} 介于 "
                f"[{self._defer_threshold}, {self._create_threshold}), "
                f"暂缓观察"
            )
        return "reject", f"价值分 {score} < 暂缓阈值 {self._defer_threshold}, 不值得投入"

    # ── 查询 ──────────────────────────────────────────────────────
    def get(self, evaluation_id: str) -> Optional[Dict[str, Any]]:
        """查询评估结果"""
        with self._lock:
            for r in self._results:
                if r["evaluation_id"] == evaluation_id:
                    return dict(r)
            return None

    def by_opportunity(
        self, opportunity_id: str,
    ) -> List[Dict[str, Any]]:
        """按机会查询评估"""
        with self._lock:
            return [
                dict(r) for r in self._results
                if r["opportunity_id"] == opportunity_id
            ]

    def stats(self) -> Dict[str, Any]:
        """评估统计"""
        with self._lock:
            results = list(self._results)
        by_decision: Dict[str, int] = {}
        by_risk: Dict[str, int] = {}
        for r in results:
            by_decision[r["decision"]] = by_decision.get(
                r["decision"], 0,
            ) + 1
            by_risk[r["risk"]] = by_risk.get(r["risk"], 0) + 1
        avg = (
            sum(r["value_score"] for r in results) / len(results)
            if results else 0.0
        )
        return {
            "mode": "rule_based",
            "evaluation_count": len(results),
            "avg_value_score": round(avg, 4),
            "by_decision": by_decision,
            "by_risk": by_risk,
            "create_count": by_decision.get("create", 0),
            "defer_count": by_decision.get("defer", 0),
            "reject_count": by_decision.get("reject", 0),
        }

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = len(self._results)
            self._results.clear()
            return n


__all__ = [
    "DECISIONS",
    "SOURCE_IMPACT_BONUS",
    "VALUE_WEIGHTS",
    "ValueEvaluator",
    "EvaluationError",
]
