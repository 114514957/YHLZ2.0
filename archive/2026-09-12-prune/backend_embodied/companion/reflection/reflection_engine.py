"""
YHLZ Embodied AI V5.8 - 反思引擎 (Reflection Engine)

职责:
    - 从 Experience 中提取: 长期模式 / 行为规律 / 失败原因 / 改进方向
    - 生成 Reflection Report:
      {observation, evidence[], pattern, risk, suggestion, confidence}

流程:
    Experience → Verification → Validated Experience → Reflection
    → Improvement Proposal

设计原则:
    - 只有验证过的经历参与反思
    - 纯规则 (禁止黑盒)
    - 反思结果可回溯 (含证据)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

from backend.embodied.companion.reflection.failure_analysis import (
    FailureAnalysisEngine,
)
from backend.embodied.companion.reflection.improvement_proposal import (
    ImprovementProposalEngine,
)
from backend.embodied.companion.reflection.pattern_discovery import (
    PatternDiscovery,
)

logger = logging.getLogger(__name__)


class ReflectionError(Exception):
    """反思操作异常"""


class ReflectionEngine:
    """反思引擎 (经历 → 反思报告 + 改进建议)

    用法:
        engine = ReflectionEngine()
        report = engine.reflect(records)
        report = engine.reflect_with_verification(records,
                                                  confirmed_ids)
    """

    def __init__(
        self,
        pattern_discovery: Optional[PatternDiscovery] = None,
        failure_analysis: Optional[FailureAnalysisEngine] = None,
        proposal: Optional[ImprovementProposalEngine] = None,
    ):
        self._lock = threading.RLock()
        self._patterns = pattern_discovery or PatternDiscovery()
        self._failures = failure_analysis or FailureAnalysisEngine()
        self._proposals = proposal or ImprovementProposalEngine()
        self._reports: List[Dict[str, Any]] = []

    # ── 反思 ──────────────────────────────────────────────────────
    def reflect(
        self,
        records: List[Dict[str, Any]],
        now: Optional[float] = None,
    ) -> Dict[str, Any]:
        """反思: 提取模式/失败/建议 → Reflection Report

        Args:
            records: 经历记录列表 (dict)

        Returns:
            {
                'report_id', 'mode': 'rule_based',
                'observation', 'evidence': [...], 'pattern',
                'risk', 'suggestion', 'confidence',
                'patterns': [...], 'failure_analyses': [...],
                'proposals': [...],
                'generated_at',
            }
        """
        with self._lock:
            now = now if now is not None else time.time()
            # 1. 模式发现
            pattern_result = self._patterns.discover(records, now=now)
            patterns = pattern_result["valid_patterns"]
            # 2. 失败分析
            failures = [
                r for r in records if r.get("type") == "failure"
            ]
            failure_analyses = [
                self._failures.analyze(
                    failure=r.get("trigger", "失败"),
                    error=r.get("result", ""),
                    action=r.get("action", ""),
                ) for r in failures
            ]
            # 3. 观察与证据
            observation = self._build_observation(records, patterns)
            evidence = self._build_evidence(records, patterns,
                                            failure_analyses)
            # 4. 风险与建议
            risk = self._assess_risk(failure_analyses)
            suggestion = self._build_suggestion(patterns,
                                                failure_analyses)
            confidence = self._report_confidence(
                records, patterns, failure_analyses,
            )
            # 5. 改进建议 (Proposal ≠ Action)
            proposals = []
            if suggestion and patterns:
                prop = self._proposals.create(
                    trigger=suggestion.split(":")[0][:40]
                    if ":" in suggestion else suggestion[:40],
                    suggestion=suggestion,
                    basis=f"{len(patterns)} 个有效模式",
                    risk=risk,
                )
                proposals.append(prop)
            report = {
                "report_id": "ref_" + uuid.uuid4().hex[:8],
                "mode": "rule_based",
                "observation": observation,
                "evidence": evidence,
                "pattern": (
                    patterns[0]["lesson"] if patterns else ""
                ),
                "risk": risk,
                "suggestion": suggestion,
                "confidence": confidence,
                "patterns": patterns,
                "failure_analyses": failure_analyses,
                "proposals": proposals,
                "generated_at": now,
            }
            self._reports.append(report)
            return dict(report)

    # ── 反思子步骤 (可解释) ───────────────────────────────────────
    @staticmethod
    def _build_observation(records: List[Dict[str, Any]],
                           patterns: List[Dict[str, Any]]) -> str:
        total = len(records)
        failures = sum(1 for r in records
                       if r.get("type") == "failure")
        if patterns:
            top = patterns[0]
            return (
                f"观察 {total} 条经历: 发现 {len(patterns)} 个有效模式, "
                f"最高频 '{top['trigger']}' 出现 {top['occurrences']} 次"
            )
        return (
            f"观察 {total} 条经历: 暂无明显模式 "
            f"({failures} 次失败)"
        )

    @staticmethod
    def _build_evidence(records, patterns, failure_analyses) -> List[str]:
        evidence = [
            f"经历样本: {len(records)} 条",
            f"有效模式: {len(patterns)} 个",
        ]
        for fa in failure_analyses[:3]:
            evidence.append(
                f"失败 '{fa['failure'][:20]}' → "
                f"{fa['possible_reason']} (置信度 {fa['confidence']})"
            )
        return evidence

    @staticmethod
    def _assess_risk(failure_analyses: List[Dict[str, Any]]) -> str:
        """风险评估 (失败比例)"""
        n = len(failure_analyses)
        if n >= 5:
            return "high"
        if n >= 2:
            return "medium"
        return "low"

    @staticmethod
    def _build_suggestion(patterns, failure_analyses) -> str:
        """建议 (基于模式与失败)"""
        if patterns:
            top = patterns[0]
            return (
                f"基于模式 '{top['trigger']}': 建议固化有效行为, "
                f"减少 {len(failure_analyses)} 次失败同类问题"
            )
        if failure_analyses:
            reason = failure_analyses[0]["possible_reason"]
            return f"基于失败分析: 建议针对 {reason} 类问题调整策略"
        return "暂无改进建议, 保持当前策略"

    @staticmethod
    def _report_confidence(records, patterns,
                           failure_analyses) -> float:
        """报告置信度 (样本/模式/失败覆盖)"""
        base = min(1.0, len(records) / 10.0) * 0.4
        pattern_score = min(1.0, len(patterns) / 3.0) * 0.3
        failure_score = min(1.0, len(failure_analyses) / 3.0) * 0.3
        return round(min(1.0, base + pattern_score + failure_score), 4)

    # ── 带验证的反思 (只对 CONFIRMED 经历) ────────────────────────
    def reflect_with_verification(
        self,
        records: List[Dict[str, Any]],
        confirmed_ids: List[str],
    ) -> Dict[str, Any]:
        """反思验证过的经历 (只 CONFIRMED 进入长期成长参考)"""
        with self._lock:
            validated = [
                r for r in records
                if r.get("id") in confirmed_ids
            ]
            return self.reflect(validated)

    # ── 统计 ──────────────────────────────────────────────────────
    def stats(self) -> Dict[str, Any]:
        """反思统计"""
        with self._lock:
            total = len(self._reports)
            proposals = self._proposals.stats()
            return {
                "mode": "rule_based",
                "reflection_count": total,
                "pattern_count": sum(
                    len(r["patterns"]) for r in self._reports
                ),
                "proposal_count": proposals["total"],
                "proposals": proposals,
                "failure_analysis_count": sum(
                    len(r["failure_analyses"]) for r in self._reports
                ),
            }

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = len(self._reports)
            self._reports.clear()
            return n


__all__ = [
    "ReflectionEngine",
    "ReflectionError",
]
