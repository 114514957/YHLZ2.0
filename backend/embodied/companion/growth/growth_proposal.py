"""
YHLZ Embodied AI V6.5 - 成长建议 (Growth Proposal)

职责:
    - 反思产生成长建议
    - 结构: {id, type, description, expected_gain, risk, confidence}
    - 类型: skill_improvement / memory_strategy /
      interaction_strategy / reasoning_strategy

原则 (AI 提出, 不代表 AI 执行):
    - Proposal → Evaluation → Approval → Apply
    - 建议不自动应用

设计原则:
    - 基于反思结果 (模式/矛盾/总结)
    - 纯规则生成 (无黑盒)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ProposalError(Exception):
    """成长建议操作异常"""


# 建议类型 (可解释)
PROPOSAL_TYPES: List[str] = [
    "skill_improvement",     # 技能改进
    "memory_strategy",       # 记忆策略
    "interaction_strategy",  # 互动策略
    "reasoning_strategy",    # 推理策略
]


class GrowthProposal:
    """成长建议器 (反思 → 建议)

    用法:
        generator = GrowthProposal()
        proposal = generator.generate(reflection_report)
    """

    def __init__(self, enabled: bool = True,
                 max_proposals: int = 30):
        self._lock = threading.RLock()
        self._enabled = bool(enabled)
        self._max = int(max_proposals)
        self._proposals: List[Dict[str, Any]] = []

    # ── 生成主入口 ───────────────────────────────────────────────
    def generate(
        self,
        reflection_report: Dict[str, Any],
        now: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """从反思报告生成成长建议

        Args:
            reflection_report: 认知反思报告

        Returns:
            建议列表
        """
        with self._lock:
            now = now if now is not None else time.time()
            if not self._enabled:
                return []
            if len(self._proposals) >= self._max:
                return []
            proposals: List[Dict[str, Any]] = []
            patterns = reflection_report.get("patterns", []) or []
            contradictions = reflection_report.get(
                "contradictions", []) or []
            # 1. 问题模式 → 技能改进
            for p in patterns:
                if p["type"] == "problem_pattern":
                    proposals.append(self._build(
                        "skill_improvement",
                        f"针对问题模式 '{p['trigger'][:20]}' "
                        f"改进执行技能",
                        expected_gain="降低该情境失败率",
                        risk="medium",
                        confidence=p["confidence"],
                        basis=p["meaning"],
                        now=now,
                    ))
            # 2. 有效策略 → 记忆策略
            for p in patterns:
                if p["type"] == "success_strategy":
                    proposals.append(self._build(
                        "memory_strategy",
                        f"固化有效策略 '{p['trigger'][:20]}' "
                        f"为长期经验",
                        expected_gain="提高同类情境成功率",
                        risk="low",
                        confidence=p["confidence"],
                        basis=p["meaning"],
                        now=now,
                    ))
            # 3. 矛盾 → 互动/推理策略
            if contradictions:
                proposals.append(self._build(
                    "interaction_strategy",
                    f"解决 {len(contradictions)} 处内部矛盾, "
                    f"统一行为策略",
                    expected_gain="减少内部不一致",
                    risk="medium",
                    confidence=0.7,
                    basis="检测到认知矛盾",
                    now=now,
                ))
            # 4. 无模式但有失败 → 推理策略
            if not patterns and reflection_report.get(
                "failure_factor",
            ) and "失败" in str(reflection_report.get(
                "failure_factor", ""),
            ):
                proposals.append(self._build(
                    "reasoning_strategy",
                    "针对失败经历加强推理分析",
                    expected_gain="提升失败归因能力",
                    risk="low",
                    confidence=0.6,
                    basis=reflection_report["failure_factor"],
                    now=now,
                ))
            # 上限截断
            room = max(0, self._max - len(self._proposals))
            kept = proposals[:room]
            self._proposals.extend(kept)
            return [dict(p) for p in kept]

    # ── 构建 (可解释) ───────────────────────────────────────────
    def _build(self, ptype: str, description: str,
               expected_gain: str, risk: str,
               confidence: float, basis: str,
               now: float) -> Dict[str, Any]:
        return {
            "id": "gp_" + uuid.uuid4().hex[:8],
            "type": ptype,
            "description": description,
            "expected_gain": expected_gain,
            "risk": risk,
            "confidence": round(confidence, 4),
            "basis": basis,
            "status": "PENDING_EVALUATION",
            "created_at": now,
        }

    # ── 查询 ─────────────────────────────────────────────────────
    def by_type(self, ptype: str) -> List[Dict[str, Any]]:
        """按类型查询"""
        if ptype not in PROPOSAL_TYPES:
            raise ProposalError(
                f"非法建议类型: {ptype} (可选: {PROPOSAL_TYPES})"
            )
        with self._lock:
            return [
                dict(p) for p in self._proposals
                if p["type"] == ptype
            ]

    def stats(self) -> Dict[str, Any]:
        """建议统计"""
        with self._lock:
            proposals = list(self._proposals)
        by_type: Dict[str, int] = {}
        for p in proposals:
            by_type[p["type"]] = by_type.get(p["type"], 0) + 1
        return {
            "mode": "rule_based",
            "proposal_count": len(proposals),
            "by_type": by_type,
        }

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = len(self._proposals)
            self._proposals.clear()
            return n


__all__ = [
    "PROPOSAL_TYPES",
    "GrowthProposal",
    "ProposalError",
]
