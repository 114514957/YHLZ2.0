"""
YHLZ Embodied AI V5.9 - 模拟引擎 (Simulation Engine)

职责:
    - 执行前模拟: 预期收益 / 潜在风险 / 副作用 / 可行性
    - 输出:
      {expected_result, risk_analysis, side_effects[], feasibility,
       recommendation, confidence}

推荐规则 (可解释):
    - 成功率 >= proceed_rate (0.7) → proceed (可执行)
    - 成功率 >= revise_rate (0.4) → revise (需修订)
    - 其余 → abandon (放弃)

设计原则:
    - 模拟不执行 (Proposal 禁止自动执行)
    - 模拟结果必须基于 CONFIRMED 经验 (可回溯)
    - 副作用检测: 与已有可靠经验冲突的方面
    - 纯规则模拟 (禁止黑盒)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class SimulationError(Exception):
    """模拟操作异常"""


# 推荐白名单 (可解释)
RECOMMENDATIONS: List[str] = ["proceed", "revise", "abandon"]

# 副作用关键词 (与可靠经验冲突信号, 可解释)
SIDE_EFFECT_KEYWORDS: List[str] = [
    "冲突", "矛盾", "覆盖", "删除", "禁用", "忽略",
    "失败", "不可用", "降级",
]


class SimulationEngine:
    """模拟引擎 (方案 → 执行前模拟)

    用法:
        engine = SimulationEngine()
        result = engine.simulate(proposal, confirmed_experiences)
    """

    def __init__(self, proceed_rate: float = 0.7,
                 revise_rate: float = 0.4):
        if not (0.0 <= proceed_rate <= 1.0):
            raise SimulationError(
                f"proceed_rate 必须在 [0,1], 当前: {proceed_rate}"
            )
        if not (0.0 <= revise_rate <= 1.0):
            raise SimulationError(
                f"revise_rate 必须在 [0,1], 当前: {revise_rate}"
            )
        if revise_rate >= proceed_rate:
            raise SimulationError(
                f"revise_rate({revise_rate}) 必须小于 "
                f"proceed_rate({proceed_rate})"
            )
        self._lock = threading.RLock()
        self._proceed = float(proceed_rate)
        self._revise = float(revise_rate)
        self._results: List[Dict[str, Any]] = []

    # ── 模拟主入口 ────────────────────────────────────────────────
    def simulate(
        self,
        proposal: Dict[str, Any],
        confirmed_experiences: Optional[List[Dict[str, Any]]] = None,
        now: Optional[float] = None,
    ) -> Dict[str, Any]:
        """执行前模拟 (规则驱动, 可解释)

        Args:
            proposal: Creative Proposal
            confirmed_experiences: 全部 CONFIRMED 经历
                (只可靠经验参与模拟)

        Returns:
            {
                'simulation_id', 'proposal_id', 'expected_result',
                'risk_analysis', 'side_effects': [...],
                'feasibility', 'recommendation', 'confidence',
                'mode', 'simulated_at',
            }
        """
        with self._lock:
            if not proposal or not proposal.get("proposal_id"):
                raise SimulationError("方案无效: 缺 proposal_id")
            now = now if now is not None else time.time()
            experiences = confirmed_experiences or []
            rate, n = self._success_rate(proposal, experiences)
            risk = self._risk_analysis(proposal, experiences)
            side_effects = self._side_effects(proposal, experiences)
            recommendation = self._recommendation(rate, risk)
            feasibility = self._feasibility(rate, recommendation)
            confidence = self._confidence(rate, n)
            result = {
                "simulation_id": "sim_" + uuid.uuid4().hex[:8],
                "proposal_id": proposal["proposal_id"],
                "expected_result": (
                    f"基于 {n} 条同类经验, 预期成功率 {rate:.0%}, "
                    f"执行后形成新经验并验证"
                ),
                "risk_analysis": risk,
                "side_effects": side_effects,
                "feasibility": feasibility,
                "recommendation": recommendation,
                "confidence": round(confidence, 4),
                "mode": "rule_based",
                "simulated_at": now,
            }
            self._results.append(result)
            return dict(result)

    # ── 模拟子步骤 (可解释) ──────────────────────────────────────
    @staticmethod
    def _success_rate(
        proposal: Dict[str, Any],
        experiences: List[Dict[str, Any]],
    ) -> tuple:
        """同类经验成功率: 同来源/同触发情境"""
        trigger = str(proposal.get("problem", ""))[:20]
        related = [
            r for r in experiences
            if str(r.get("trigger", "")).find(trigger) >= 0
            or str(proposal.get("problem", "")).find(
                str(r.get("trigger", ""))[:8],
            ) >= 0
        ]
        if not related:
            related = experiences[:10]
        if not related:
            return 0.4, 0  # 无参考 → 保守
        success = sum(
            1 for r in related
            if str(r.get("result", "")).find("成功") >= 0
            or r.get("type") in ("interaction", "improvement",
                                 "engineering")
        )
        return success / len(related), len(related)

    @staticmethod
    def _risk_analysis(
        proposal: Dict[str, Any], experiences: List[Dict[str, Any]],
    ) -> str:
        """风险分析: 失败经验占比"""
        failures = [
            r for r in experiences if r.get("type") == "failure"
        ]
        if not failures:
            return "同类经验无失败记录, 风险低"
        ratio = len(failures) / len(experiences)
        top_trigger = max(
            failures, key=lambda r: str(r.get("trigger", "")),
        ).get("trigger", "")
        if ratio >= 0.5:
            level = "高风险"
        elif ratio >= 0.25:
            level = "中风险"
        else:
            level = "低风险"
        return (
            f"{level}: 失败经验占比 {ratio:.0%} "
            f"({len(failures)}/{len(experiences)}), "
            f"常见失败情境 '{top_trigger}'"
        )

    @staticmethod
    def _side_effects(
        proposal: Dict[str, Any], experiences: List[Dict[str, Any]],
    ) -> List[str]:
        """副作用检测: 方案文本与可靠经验冲突信号"""
        text = " ".join([
            str(proposal.get("title", "")),
            str(proposal.get("idea", "")),
            str(proposal.get("reasoning", "")),
        ])
        effects: List[str] = []
        for kw in SIDE_EFFECT_KEYWORDS:
            if kw in text:
                effects.append(
                    f"方案涉及'{kw}', 可能影响既有可靠经验"
                )
        # 方案影响面检查: 关联证据数
        evidence_n = len(proposal.get("evidence", []) or [])
        if evidence_n == 0:
            effects.append("方案无直接证据关联, 需补充验证")
        return effects[:5]

    def _recommendation(self, rate: float, risk: str) -> str:
        """推荐规则 (可解释)"""
        risk_penalty = {"high": 0.1, "medium": 0.05, "low": 0.0}
        effective = rate - risk_penalty.get(risk, 0.0)
        if effective >= self._proceed:
            return "proceed"
        if effective >= self._revise:
            return "revise"
        return "abandon"

    @staticmethod
    def _feasibility(rate: float, recommendation: str) -> str:
        """可行性等级"""
        if recommendation == "proceed":
            return "high"
        if recommendation == "revise":
            return "medium"
        return "low"

    @staticmethod
    def _confidence(rate: float, n: int) -> float:
        """模拟置信度: 成功率 + 样本量"""
        base = rate * 0.7
        sample = min(1.0, n / 10.0) * 0.25
        return round(min(0.95, base + sample), 4)

    # ── 查询 ──────────────────────────────────────────────────────
    def get(self, simulation_id: str) -> Optional[Dict[str, Any]]:
        """查询模拟结果"""
        with self._lock:
            for r in self._results:
                if r["simulation_id"] == simulation_id:
                    return dict(r)
            return None

    def by_proposal(
        self, proposal_id: str,
    ) -> List[Dict[str, Any]]:
        """按方案查询模拟"""
        with self._lock:
            return [
                dict(r) for r in self._results
                if r["proposal_id"] == proposal_id
            ]

    def stats(self) -> Dict[str, Any]:
        """模拟统计"""
        with self._lock:
            results = list(self._results)
        by_rec: Dict[str, int] = {}
        by_feas: Dict[str, int] = {}
        for r in results:
            by_rec[r["recommendation"]] = by_rec.get(
                r["recommendation"], 0,
            ) + 1
            by_feas[r["feasibility"]] = by_feas.get(
                r["feasibility"], 0,
            ) + 1
        total_effects = sum(len(r["side_effects"]) for r in results)
        return {
            "mode": "rule_based",
            "simulation_count": len(results),
            "by_recommendation": by_rec,
            "by_feasibility": by_feas,
            "risk_found_count": total_effects,
        }

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = len(self._results)
            self._results.clear()
            return n


__all__ = [
    "RECOMMENDATIONS",
    "SIDE_EFFECT_KEYWORDS",
    "SimulationEngine",
    "SimulationError",
]
