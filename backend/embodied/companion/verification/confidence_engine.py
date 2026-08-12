"""
YHLZ Embodied AI V5.8 - 置信度引擎 (Confidence Engine)

职责:
    - 计算经验置信度 (0.0~1.0)
    - 评估因素: 信息来源可靠度 / 重复出现次数 / 结果一致性 /
      是否存在反例 / 时间稳定性
    - 可解释: 每因素贡献说明

设计原则:
    - 纯规则计算 (禁止黑盒)
    - 置信度驱动状态机 (高置信度 → CONFIRMED)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ConfidenceError(Exception):
    """置信度计算操作异常"""


class ConfidenceEngine:
    """置信度引擎 (多因素加权)

    用法:
        engine = ConfidenceEngine()
        result = engine.compute(source_reliability=0.9,
                                occurrences=5, consistency=1.0,
                                contradictions=0, age_days=3)
    """

    def __init__(self):
        self._lock = threading.RLock()

    # ── 单因素评分 (可解释) ───────────────────────────────────────
    @staticmethod
    def _source_score(reliability: float) -> float:
        """信息来源可靠度 (0.0~1.0)"""
        return max(0.0, min(1.0, reliability))

    @staticmethod
    def _occurrence_score(occurrences: int) -> float:
        """重复出现次数 (0/1 → 低, >=5 → 高)"""
        return min(1.0, occurrences / 5.0)

    @staticmethod
    def _consistency_score(consistency: float) -> float:
        """结果一致性 (0.0~1.0)"""
        return max(0.0, min(1.0, consistency))

    @staticmethod
    def _contradiction_penalty(contradictions: int) -> float:
        """反例惩罚 (每个反例 -0.3, 下限 0)"""
        return max(0.0, 1.0 - 0.3 * contradictions)

    @staticmethod
    def _stability_score(age_days: float, half_life: float = 14.0) -> float:
        """时间稳定性 (越久越稳定, 半衰期 14 天)"""
        if age_days <= 0:
            return 0.2
        return min(1.0, 0.2 + 0.8 * (1 - 2 ** (-age_days / half_life)))

    # ── 综合计算 ──────────────────────────────────────────────────
    def compute(
        self,
        source_reliability: float = 0.5,
        occurrences: int = 1,
        consistency: float = 1.0,
        contradictions: int = 0,
        age_days: float = 0.0,
        weights: Optional[Dict[str, float]] = None,
    ) -> Dict[str, Any]:
        """计算置信度 (加权求和, 可解释)

        Args:
            source_reliability: 信息来源可靠度 (0.0~1.0)
            occurrences: 重复出现次数
            consistency: 结果一致性 (0.0~1.0)
            contradictions: 反例数
            age_days: 时间跨度 (天)
            weights: 自定义权重 (默认 source 0.3/occurrence 0.2/
                     consistency 0.2/contradiction 0.2/stability 0.1)

        Returns:
            {
                'confidence': 0.0~1.0,
                'factors': {'source': {...}, 'occurrences': {...}, ...},
                'rule': '加权求和 (可解释)',
            }
        """
        with self._lock:
            w = weights or {
                "source": 0.3, "occurrence": 0.2,
                "consistency": 0.2, "contradiction": 0.2,
                "stability": 0.1,
            }
            total_w = sum(w.values())
            if total_w <= 0:
                raise ConfidenceError(f"权重和必须 > 0, 当前: {total_w}")

            s_source = self._source_score(source_reliability)
            s_occur = self._occurrence_score(max(0, occurrences))
            s_consist = self._consistency_score(consistency)
            s_contra = self._contradiction_penalty(max(0, contradictions))
            s_stab = self._stability_score(max(0.0, age_days))

            factors = {
                "source": {"score": round(s_source, 4),
                           "weight": w["source"],
                           "reason": f"来源可靠度 {source_reliability}"},
                "occurrences": {"score": round(s_occur, 4),
                                "weight": w["occurrence"],
                                "reason": f"重复 {occurrences} 次"},
                "consistency": {"score": round(s_consist, 4),
                                "weight": w["consistency"],
                                "reason": f"一致性 {consistency}"},
                "contradiction": {"score": round(s_contra, 4),
                                  "weight": w["contradiction"],
                                  "reason": f"反例 {contradictions} 个"},
                "stability": {"score": round(s_stab, 4),
                              "weight": w["stability"],
                              "reason": f"时间 {age_days:.1f} 天"},
            }
            confidence = sum(
                f["score"] * f["weight"] for f in factors.values()
            ) / total_w
            return {
                "confidence": round(max(0.0, min(1.0, confidence)), 4),
                "factors": factors,
                "rule": "加权求和: source×0.3 + occurrence×0.2 + "
                        "consistency×0.2 + contradiction×0.2 + "
                        "stability×0.1",
            }

    # ── 置信度分级 ────────────────────────────────────────────────
    @staticmethod
    def level(confidence: float) -> str:
        """置信度分级 (可解释)"""
        if confidence >= 0.8:
            return "high"
        if confidence >= 0.5:
            return "medium"
        return "low"

    def suggest_status(self, confidence: float) -> str:
        """建议验证状态 (置信度驱动)"""
        if confidence >= 0.8:
            return "CONFIRMED"
        if confidence >= 0.5:
            return "PROBABLE"
        if confidence >= 0.3:
            return "PENDING"
        return "REJECTED"


__all__ = [
    "ConfidenceEngine",
    "ConfidenceError",
]
