"""
YHLZ Embodied AI V6.6 - 成长趋势分析 (Growth Trend Analysis)

职责:
    - 分析长期成长趋势 (反思/成长/身份/记忆 四类指标)
    - 输出: {period, growth_score, trend, analysis}

指标 (可解释):
    Reflection Metrics:  reflection_count / reflection_frequency
    Growth Metrics:      proposal_count / approval_rate / applied_count
    Identity Metrics:    identity_change_attempt / identity_guard_block
    Memory Metrics:      experience_growth / memory_quality

成长分 (growth_score):
    - 反思活跃 20% (反思频率)
    - 成长质量 40% (通过率 25% + 应用数 15%)
    - 身份安全 10% (守护拦截为安全行为, 不扣分)
    - 记忆成长 30% (经历增长 15% + 记忆质量 15%)

趋势判定 (可解释):
    - growth_score ≥ 0.75 → accelerating
    - growth_score ≤ 0.40 → decelerating
    - 其余 → stable

设计原则:
    - 纯规则统计 (无黑盒)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class TrendAnalysisError(Exception):
    """成长趋势分析操作异常"""


# 分析周期 (可解释)
ANALYSIS_PERIODS: List[str] = [
    "day",                # 按天
    "week",               # 按周
    "month",              # 按月
]

# 趋势档位 (可解释)
TREND_LEVELS: List[str] = [
    "accelerating",       # 加速成长
    "stable",             # 平稳成长
    "decelerating",       # 减速成长
]

# 成长分权重 (可解释)
GROWTH_WEIGHTS: Dict[str, float] = {
    "reflection": 0.2,    # 反思活跃
    "approval_rate": 0.25,  # 建议通过率
    "applied": 0.15,      # 应用数
    "identity": 0.1,      # 身份安全
    "experience": 0.15,   # 经历增长
    "memory_quality": 0.15,  # 记忆质量
}


class GrowthTrendAnalysis:
    """成长趋势分析器 (反思/成长/身份/记忆)

    用法:
        analysis = GrowthTrendAnalysis()
        result = analysis.analyze(stats_input, period="day")
    """

    def __init__(self, enabled: bool = True):
        self._lock = threading.RLock()
        self._enabled = bool(enabled)
        self._results: List[Dict[str, Any]] = []

    # ── 主入口 ───────────────────────────────────────────────────
    def analyze(
        self,
        stats_input: Dict[str, Any],
        period: str = "day",
        now: Optional[float] = None,
    ) -> Dict[str, Any]:
        """成长趋势分析

        Args:
            stats_input: 各子系统统计 (可空字段):
                {
                    "reflection": {"reflection_count": N},
                    "proposal": {"proposal_count": N},
                    "evaluator": {"evaluation_count": N,
                                  "approved_count": N},
                    "applier": {"applied_count": N,
                                "apply_count": N},
                    "identity_guard": {"intercept_count": N},
                    "experience": {"total": N, "confirmed": N},
                    "verification": {"confirmed": N,
                                     "rejected": N},
                    "period_days": N,
                }
            period: 分析周期 (day/week/month)

        Returns:
            {
                'analysis_id', 'period', 'growth_score',
                'trend', 'analysis': [...], 'mode',
            }
        """
        with self._lock:
            now = now if now is not None else time.time()
            stats_input = stats_input or {}
            if period not in ANALYSIS_PERIODS:
                raise TrendAnalysisError(
                    f"非法分析周期: {period} "
                    f"(可选: {ANALYSIS_PERIODS})"
                )
            if not self._enabled:
                return {
                    "analysis_id": "ta_" + uuid.uuid4().hex[:8],
                    "period": period,
                    "growth_score": 0.0,
                    "trend": "stable",
                    "analysis": [],
                    "mode": "rule_based",
                    "generated_at": now,
                }
            # 1. 四类指标
            analysis: List[Dict[str, Any]] = []
            self._reflection_metrics(stats_input, analysis)
            self._growth_metrics(stats_input, analysis)
            self._identity_metrics(stats_input, analysis)
            self._memory_metrics(stats_input, analysis)
            # 2. 成长分 (加权)
            growth_score = self._growth_score(stats_input)
            # 3. 趋势
            trend = self._trend(growth_score)
            result = {
                "analysis_id": "ta_" + uuid.uuid4().hex[:8],
                "period": period,
                "growth_score": round(growth_score, 4),
                "trend": trend,
                "analysis": analysis,
                "mode": "rule_based",
                "generated_at": now,
            }
            self._results.append(result)
            return dict(result)

    # ── 指标构建 (可解释) ───────────────────────────────────────
    @staticmethod
    def _reflection_metrics(
        stats_input: Dict[str, Any],
        out: List[Dict[str, Any]],
    ) -> None:
        """反思指标: 次数 + 频率"""
        refl = stats_input.get("reflection") or {}
        period_days = float(stats_input.get("period_days", 30))
        count = int(refl.get("reflection_count", 0))
        frequency = round(
            count / period_days if period_days > 0 else 0.0, 4,
        )
        out.append({
            "metric": "reflection_count",
            "category": "Reflection",
            "value": count,
            "unit": "次",
            "reason": "反思次数 (认知活跃度)",
        })
        out.append({
            "metric": "reflection_frequency",
            "category": "Reflection",
            "value": frequency,
            "unit": "次/天",
            "reason": f"反思频率 (窗口 {period_days:.0f} 天)",
        })

    @staticmethod
    def _growth_metrics(
        stats_input: Dict[str, Any],
        out: List[Dict[str, Any]],
    ) -> None:
        """成长指标: 建议数 + 通过率 + 应用数"""
        proposal = stats_input.get("proposal") or {}
        evaluator = stats_input.get("evaluator") or {}
        applier = stats_input.get("applier") or {}
        proposal_count = int(proposal.get("proposal_count", 0))
        evaluation_count = int(evaluator.get(
            "evaluation_count", 0,
        ))
        approved_count = int(evaluator.get(
            "approved_count", 0,
        ))
        approval_rate = round(
            approved_count / evaluation_count
            if evaluation_count else 0.0, 4,
        )
        applied_count = int(applier.get("applied_count", 0))
        out.append({
            "metric": "proposal_count",
            "category": "Growth",
            "value": proposal_count,
            "unit": "条",
            "reason": "成长建议总数",
        })
        out.append({
            "metric": "approval_rate",
            "category": "Growth",
            "value": approval_rate,
            "unit": "比率",
            "reason": "建议评估通过率",
        })
        out.append({
            "metric": "applied_count",
            "category": "Growth",
            "value": applied_count,
            "unit": "次",
            "reason": "成长应用次数 (全部经审批)",
        })

    @staticmethod
    def _identity_metrics(
        stats_input: Dict[str, Any],
        out: List[Dict[str, Any]],
    ) -> None:
        """身份指标: 变更尝试 + 守护拦截"""
        guard = stats_input.get("identity_guard") or {}
        attempts = int(guard.get("attempt_count", 0))
        if attempts <= 0:
            # 无 attempt_count 时回退 (intercept + approval)
            attempts = int(guard.get("intercept_count", 0)) + \
                int(guard.get("approval_count", 0))
        blocked = int(guard.get("intercept_count", 0))
        out.append({
            "metric": "identity_change_attempt",
            "category": "Identity",
            "value": attempts,
            "unit": "次",
            "reason": "身份变更尝试 (身份保护监测)",
        })
        out.append({
            "metric": "identity_guard_block",
            "category": "Identity",
            "value": blocked,
            "unit": "次",
            "reason": "身份守护拦截次数 (安全行为)",
        })

    @staticmethod
    def _memory_metrics(
        stats_input: Dict[str, Any],
        out: List[Dict[str, Any]],
    ) -> None:
        """记忆指标: 经历增长 + 记忆质量"""
        exp = stats_input.get("experience") or {}
        ver = stats_input.get("verification") or {}
        total = int(exp.get("total", 0))
        confirmed = int(ver.get("confirmed", 0))
        rejected = int(ver.get("rejected", 0))
        verified = confirmed + rejected
        quality = round(
            confirmed / verified if verified else 0.0, 4,
        )
        out.append({
            "metric": "experience_growth",
            "category": "Memory",
            "value": total,
            "unit": "条",
            "reason": "累计经历数 (记忆积累)",
        })
        out.append({
            "metric": "memory_quality",
            "category": "Memory",
            "value": quality,
            "unit": "比率",
            "reason": "经验验证通过率 (记忆质量)",
        })

    # ── 成长分 (可解释) ─────────────────────────────────────────
    @staticmethod
    def _growth_score(stats_input: Dict[str, Any]) -> float:
        """加权成长分"""
        refl = stats_input.get("reflection") or {}
        evaluator = stats_input.get("evaluator") or {}
        applier = stats_input.get("applier") or {}
        ver = stats_input.get("verification") or {}
        period_days = float(stats_input.get("period_days", 30))
        # 反思活跃 (0~1)
        frequency = int(refl.get("reflection_count", 0)) / \
            period_days if period_days > 0 else 0.0
        reflection_score = min(1.0, frequency / 1.0)
        # 通过率
        evaluation_count = int(evaluator.get(
            "evaluation_count", 0,
        ))
        approval_rate = (
            int(evaluator.get("approved_count", 0)) /
            evaluation_count if evaluation_count else 0.0
        )
        # 应用活跃 (0~1)
        applied = int(applier.get("applied_count", 0))
        applied_score = min(1.0, applied / 10.0)
        # 记忆质量
        confirmed = int(ver.get("confirmed", 0))
        rejected = int(ver.get("rejected", 0))
        verified = confirmed + rejected
        memory_quality = confirmed / verified if verified else 0.0
        # 经历增长 (0~1)
        exp_total = int(
            (stats_input.get("experience") or {}).get(
                "total", 0,
            ),
        )
        experience_score = min(1.0, exp_total / 100.0)
        score = (
            reflection_score * GROWTH_WEIGHTS["reflection"]
            + approval_rate * GROWTH_WEIGHTS["approval_rate"]
            + applied_score * GROWTH_WEIGHTS["applied"]
            + GROWTH_WEIGHTS["identity"]  # 身份安全基础分
            + experience_score * GROWTH_WEIGHTS["experience"]
            + memory_quality * GROWTH_WEIGHTS["memory_quality"]
        )
        return round(min(1.0, score), 4)

    @staticmethod
    def _trend(growth_score: float) -> str:
        """趋势档位"""
        if growth_score >= 0.75:
            return "accelerating"
        if growth_score <= 0.40:
            return "decelerating"
        return "stable"

    # ── 查询 ─────────────────────────────────────────────────────
    def latest(self) -> Optional[Dict[str, Any]]:
        """最新趋势分析"""
        with self._lock:
            if not self._results:
                return None
            return dict(self._results[-1])

    def stats(self) -> Dict[str, Any]:
        """趋势分析统计"""
        with self._lock:
            return {
                "mode": "rule_based",
                "enabled": self._enabled,
                "analysis_count": len(self._results),
                "periods": list(ANALYSIS_PERIODS),
            }

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = len(self._results)
            self._results.clear()
            return n


__all__ = [
    "ANALYSIS_PERIODS",
    "GROWTH_WEIGHTS",
    "GrowthTrendAnalysis",
    "TREND_LEVELS",
    "TrendAnalysisError",
]
