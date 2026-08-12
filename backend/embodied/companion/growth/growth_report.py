"""
YHLZ Embodied AI V6.0 - 成长报告 (Growth Report)

职责:
    - 输出长期成长报告:
      经验成长 (数量/类型/价值)
      认知成长 (Reflection 数量/Pattern 变化)
      创造成长 (Proposal 数量/转化率)
      关系成长 (信任变化/互动趋势)
    - 结合成长意义 (发生了什么 → 意味着什么)

设计原则:
    - 报告全部来自可靠统计 (纯规则)
    - 各维度可解释 (含来源数据)
    - 只读 (不修改任何子系统状态)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ReportError(Exception):
    """成长报告操作异常"""


class GrowthReport:
    """成长报告生成器

    用法:
        report = GrowthReport()
        r = report.generate(inputs)
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._reports: List[Dict[str, Any]] = []

    # ── 生成主入口 ───────────────────────────────────────────────
    def generate(
        self,
        inputs: Dict[str, Any],
        now: Optional[float] = None,
    ) -> Dict[str, Any]:
        """生成长期成长报告

        Args:
            inputs: 各子系统统计输入 (可空字段):
                {
                    "experience_stats": {...},
                    "experience_by_type": [...],
                    "verification_stats": {...},
                    "reflection_stats": {...},
                    "creative_stats": {...},
                    "relationship": {...},
                    "growth_metrics": {...},
                    "meanings": [...],
                    "growth_trend_input": {...},  # V6.6 趋势输入
                }

        Returns:
            {
                'report_id', 'generated_at',
                'experience_growth', 'cognitive_growth',
                'creative_growth', 'relationship_growth',
                'growth_trend': {...},  # V6.6
                'growth_meanings': [...], 'summary',
                'mode',
            }
        """
        with self._lock:
            now = now if now is not None else time.time()
            exp = self._experience_growth(inputs)
            cog = self._cognitive_growth(inputs)
            cre = self._creative_growth(inputs)
            rel = self._relationship_growth(inputs)
            meanings = self._meaning_summary(inputs)
            trend = self._growth_trend(inputs)
            report = {
                "report_id": "grep_" +
                __import__("uuid").uuid4().hex[:8],
                "generated_at": now,
                "experience_growth": exp,
                "cognitive_growth": cog,
                "creative_growth": cre,
                "relationship_growth": rel,
                "growth_trend": trend,
                "growth_meanings": meanings,
                "summary": {
                    "experience_total": exp["total"],
                    "confirmed_total": exp["confirmed"],
                    "reflection_total": cog["reflection_count"],
                    "proposal_total": cre["proposal_count"],
                    "conversion_rate": cre["conversion_rate"],
                    "trust_level": rel["trust_level"],
                },
                "mode": "rule_based",
            }
            self._reports.append(report)
            return dict(report)

    # ── 维度构建 (可解释) ───────────────────────────────────────
    @staticmethod
    def _experience_growth(inputs: Dict[str, Any]) -> Dict[str, Any]:
        """经验成长: 数量/类型/价值"""
        exp_stats = inputs.get("experience_stats") or {}
        by_type = exp_stats.get("by_type", {})
        total = int(exp_stats.get("total", 0))
        confirmed = int(
            (inputs.get("verification_stats") or {})
            .get("confirmed", 0)
        )
        avg_value = float(exp_stats.get("avg_value", 0.0))
        return {
            "total": total,
            "by_type": by_type,
            "confirmed": confirmed,
            "avg_value": round(avg_value, 4),
            "source": "experience_stats + verification_stats",
        }

    @staticmethod
    def _cognitive_growth(inputs: Dict[str, Any]) -> Dict[str, Any]:
        """认知成长: Reflection/Pattern"""
        refl = inputs.get("reflection_stats") or {}
        return {
            "reflection_count": int(refl.get(
                "reflection_count", 0,
            )),
            "pattern_count": int(refl.get("pattern_count", 0)),
            "failure_analysis_count": int(refl.get(
                "failure_analysis_count", 0,
            )),
            "source": "reflection_stats",
        }

    @staticmethod
    def _creative_growth(inputs: Dict[str, Any]) -> Dict[str, Any]:
        """创造成长: Proposal/转化率"""
        cre = inputs.get("creative_stats") or {}
        memory = cre.get("memory", {})
        proposal_total = int(memory.get("total", 0))
        approved = int(memory.get("approved", 0))
        completed = int(memory.get("completed", 0))
        conversion = round(
            completed / proposal_total
            if proposal_total else 0.0, 4,
        )
        return {
            "proposal_count": proposal_total,
            "approved_count": approved,
            "completed_count": completed,
            "conversion_rate": conversion,
            "source": "creative_stats.memory",
        }

    @staticmethod
    def _relationship_growth(inputs: Dict[str, Any]) -> Dict[str, Any]:
        """关系成长: 信任/互动"""
        rel = inputs.get("relationship") or {}
        return {
            "trust_level": float(rel.get("trust_level", 0.0)),
            "familiarity": float(rel.get("familiarity", 0.0)),
            "interaction_count": int(rel.get("interaction_count", 0)),
            "stage": rel.get("relationship_stage", ""),
            "source": "relationship",
        }

    @staticmethod
    def _growth_trend(inputs: Dict[str, Any]) -> Dict[str, Any]:
        """成长趋势段 (V6.6: 建议数/通过率/应用数)"""
        data = inputs.get("growth_trend_input") or {}
        if not data:
            return {
                "available": False,
                "source": "growth_trend_input",
                "analysis": [],
            }
        analysis = []
        proposal_count = int(data.get("proposal_count", 0))
        evaluation_count = int(data.get("evaluation_count", 0))
        approved_count = int(data.get("approved_count", 0))
        applied_count = int(data.get("applied_count", 0))
        approval_rate = round(
            approved_count / evaluation_count
            if evaluation_count else 0.0, 4,
        )
        analysis.append({
            "metric": "proposal_count",
            "value": proposal_count,
        })
        analysis.append({
            "metric": "approval_rate",
            "value": approval_rate,
        })
        analysis.append({
            "metric": "applied_count",
            "value": applied_count,
        })
        return {
            "available": True,
            "source": "growth_trend_input",
            "period": str(data.get("period", "day")),
            "analysis": analysis,
            "growth_score": round(
                float(data.get("growth_score", 0.0)), 4,
            ),
        }

    @staticmethod
    def _meaning_summary(inputs: Dict[str, Any]) -> List[Dict[str, Any]]:
        """成长意义摘要 (最近 5 条)"""
        meanings = inputs.get("meanings") or []
        recent = list(reversed(meanings))[:5]
        return [
            {
                "event": m.get("event", ""),
                "meaning": m.get("meaning", ""),
                "detail": m.get("detail", ""),
            }
            for m in recent
        ]

    # ── 查询 ─────────────────────────────────────────────────────
    def latest(self) -> Optional[Dict[str, Any]]:
        """最新报告"""
        with self._lock:
            if not self._reports:
                return None
            return dict(self._reports[-1])

    def stats(self) -> Dict[str, Any]:
        """报告统计"""
        with self._lock:
            return {
                "mode": "rule_based",
                "report_count": len(self._reports),
            }

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = len(self._reports)
            self._reports.clear()
            return n


__all__ = [
    "GrowthReport",
    "ReportError",
]
