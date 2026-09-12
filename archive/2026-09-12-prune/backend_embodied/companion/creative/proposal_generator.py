"""
YHLZ Embodied AI V5.9 - 方案生成器 (Proposal Generator)

职责:
    - 基于机会 + 推理 + 价值评估生成创造方案
    - 输出 Creative Proposal:
      {title, problem, idea, reasoning, expected_value, risk, confidence}

方案标题规则 (可解释):
    - automation:          自动化{trigger}
    - optimization:        优化{trigger}方案
    - new_capability:      新增{trigger}能力
    - personalization:     个性化{trigger}服务
    - process_improvement: 改进{trigger}流程

设计原则:
    - 所有方案必须: 有来源 (evidence) / 有推理链 (reasoning) /
      有风险分析 (risk) / 有预期收益 (expected_value)
    - Proposal ≠ Action (禁止自动执行)
    - 纯规则生成 (禁止黑盒)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ProposalGenerationError(Exception):
    """方案生成操作异常"""


class ProposalGenerator:
    """方案生成器 (机会+推理+评估 → 创造方案)

    用法:
        generator = ProposalGenerator()
        proposal = generator.generate(opportunity, reasoning, evaluation)
    """

    def __init__(self, max_proposals: int = 30):
        if max_proposals <= 0:
            raise ProposalGenerationError(
                f"max_proposals 必须 > 0, 当前: {max_proposals}"
            )
        self._lock = threading.RLock()
        self._max = int(max_proposals)
        self._proposals: List[Dict[str, Any]] = []

    # ── 生成主入口 ────────────────────────────────────────────────
    def generate(
        self,
        opportunity: Dict[str, Any],
        reasoning: Dict[str, Any],
        evaluation: Dict[str, Any],
        now: Optional[float] = None,
    ) -> Dict[str, Any]:
        """生成创造方案 (规则驱动, 可解释)

        Args:
            opportunity: Opportunity Candidate
            reasoning: Creative Reasoning 结果
            evaluation: Value Evaluation 结果

        Returns:
            Creative Proposal dict
        """
        with self._lock:
            if not opportunity or not opportunity.get("opportunity_id"):
                raise ProposalGenerationError("机会候选无效")
            if not reasoning or not reasoning.get("reasoning_id"):
                raise ProposalGenerationError("推理结果无效")
            if not evaluation or not evaluation.get("evaluation_id"):
                raise ProposalGenerationError("价值评估无效")
            if evaluation.get("decision") != "create":
                raise ProposalGenerationError(
                    f"只有 decision=create 可生成方案, "
                    f"当前: {evaluation.get('decision')}"
                )
            if len(self._proposals) >= self._max:
                raise ProposalGenerationError("方案数已达上限")
            now = now if now is not None else time.time()
            paths = reasoning.get("paths", []) or []
            primary = paths[0] if paths else {}
            path_type = primary.get("type", "process_improvement")
            title = self._build_title(
                opportunity, path_type,
            )
            idea = self._build_idea(opportunity, primary)
            reasoning_text = self._build_reasoning_text(
                opportunity, reasoning,
            )
            expected_value = self._build_expected_value(evaluation)
            risk = self._assess_risk(evaluation)
            confidence = self._proposal_confidence(
                opportunity, reasoning, evaluation,
            )
            proposal = {
                "proposal_id": "cp_" + uuid.uuid4().hex[:8],
                "title": title,
                "problem": opportunity.get("problem", ""),
                "idea": idea,
                "reasoning": reasoning_text,
                "expected_value": expected_value,
                "risk": risk,
                "confidence": round(confidence, 4),
                "source_type": opportunity.get("source_type", ""),
                "path_type": path_type,
                "evidence": list(opportunity.get("evidence", []) or []),
                "opportunity_id": opportunity["opportunity_id"],
                "reasoning_id": reasoning["reasoning_id"],
                "evaluation_id": evaluation["evaluation_id"],
                "status": "PENDING",
                "simulation": None,
                "created_at": now,
                "approved_at": 0.0,
                "executed_at": 0.0,
                "result": "",
            }
            self._proposals.append(proposal)
            return dict(proposal)

    # ── 方案构建 (可解释) ────────────────────────────────────────
    @staticmethod
    def _build_title(
        opportunity: Dict[str, Any], path_type: str,
    ) -> str:
        """方案标题规则"""
        trigger = opportunity.get("trigger", "")
        templates = {
            "automation": f"自动化{trigger}",
            "optimization": f"优化{trigger}方案",
            "new_capability": f"新增{trigger}能力",
            "personalization": f"个性化{trigger}服务",
            "process_improvement": f"改进{trigger}流程",
        }
        return templates.get(path_type, f"改进{trigger}")

    @staticmethod
    def _build_idea(
        opportunity: Dict[str, Any], primary_path: Dict[str, Any],
    ) -> str:
        """方案思路: 路径描述 + 差距"""
        desc = primary_path.get("description", "")
        gap = opportunity.get("gap", "")
        return f"{desc}; 针对差距 '{gap}'"

    @staticmethod
    def _build_reasoning_text(
        opportunity: Dict[str, Any], reasoning: Dict[str, Any],
    ) -> str:
        """推理链摘要 (可回溯)"""
        return (
            f"当前: {opportunity.get('current_state', '')} → "
            f"理想: {opportunity.get('desired_state', '')}; "
            f"差距: {reasoning.get('gap', '')} "
            f"(推理置信度 {reasoning.get('confidence', 0.0)})"
        )

    @staticmethod
    def _build_expected_value(evaluation: Dict[str, Any]) -> str:
        """预期收益 (来自价值评估)"""
        dims = {d["name"]: d for d in evaluation.get("dimensions", [])}
        return (
            f"影响 {evaluation.get('impact')}, "
            f"频率 {evaluation.get('frequency')}, "
            f"用户收益 {evaluation.get('benefit')}, "
            f"可实现性 {evaluation.get('feasibility')}, "
            f"价值分 {evaluation.get('value_score')}"
        )

    @staticmethod
    def _assess_risk(evaluation: Dict[str, Any]) -> str:
        """风险等级 (来自价值评估)"""
        return evaluation.get("risk", "low")

    @staticmethod
    def _proposal_confidence(
        opportunity: Dict[str, Any], reasoning: Dict[str, Any],
        evaluation: Dict[str, Any],
    ) -> float:
        """方案置信度: 机会/推理/价值 加权"""
        return round(min(0.98, (
            float(opportunity.get("confidence", 0.0)) * 0.4
            + float(reasoning.get("confidence", 0.0)) * 0.3
            + float(evaluation.get("value_score", 0.0)) * 0.3
        )), 4)

    # ── 查询 ──────────────────────────────────────────────────────
    def get(self, proposal_id: str) -> Optional[Dict[str, Any]]:
        """查询方案"""
        with self._lock:
            for p in self._proposals:
                if p["proposal_id"] == proposal_id:
                    return dict(p)
            return None

    def by_opportunity(
        self, opportunity_id: str,
    ) -> List[Dict[str, Any]]:
        """按机会查询方案"""
        with self._lock:
            return [
                dict(p) for p in self._proposals
                if p["opportunity_id"] == opportunity_id
            ]

    def stats(self) -> Dict[str, Any]:
        """方案统计"""
        with self._lock:
            proposals = list(self._proposals)
        by_source: Dict[str, int] = {}
        by_risk: Dict[str, int] = {}
        for p in proposals:
            by_source[p["source_type"]] = by_source.get(
                p["source_type"], 0,
            ) + 1
            by_risk[p["risk"]] = by_risk.get(p["risk"], 0) + 1
        return {
            "mode": "rule_based",
            "proposal_count": len(proposals),
            "by_source_type": by_source,
            "by_risk": by_risk,
        }

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = len(self._proposals)
            self._proposals.clear()
            return n


__all__ = [
    "ProposalGenerationError",
    "ProposalGenerator",
]
