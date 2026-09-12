"""
YHLZ Embodied AI V6.5 - 认知反思引擎 (Cognitive Reflection Engine)

职责:
    - 分析: 经历 / 行为 / 结果 / 用户反馈
    - 生成认知总结:
      {summary, pattern, success_factor, failure_factor, confidence}

原则 (反思不是意识):
    - Reflection 是计算过程, 不是真实体验
    - 禁止宣称拥有意识

设计原则:
    - 统计 + 规则驱动 (可解释)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

from backend.embodied.companion.reflection.contradiction_detector import (
    CognitiveContradictionDetector,
)
from backend.embodied.companion.reflection.pattern_analyzer import (
    PatternAnalyzer,
)

logger = logging.getLogger(__name__)


class ReflectionError(Exception):
    """认知反思操作异常"""


class CognitiveReflectionEngine:
    """认知反思引擎 (经历 → 认知总结)

    用法:
        engine = CognitiveReflectionEngine()
        result = engine.analyze(records, identity_state)
    """

    def __init__(
        self,
        pattern_analyzer: Optional[PatternAnalyzer] = None,
        contradiction_detector: Optional[
            CognitiveContradictionDetector] = None,
        enabled: bool = True,
    ):
        self._lock = threading.RLock()
        self._patterns = pattern_analyzer or PatternAnalyzer()
        self._contradictions = contradiction_detector or \
            CognitiveContradictionDetector()
        self._enabled = bool(enabled)
        self._reports: List[Dict[str, Any]] = []

    # ── 分析主入口 ───────────────────────────────────────────────
    def analyze(
        self,
        records: List[Dict[str, Any]],
        identity_state: Optional[Dict[str, Any]] = None,
        now: Optional[float] = None,
    ) -> Dict[str, Any]:
        """认知反思: 经历 → 认知总结

        Args:
            records: 经历列表
            identity_state: 身份状态 (矛盾检测)

        Returns:
            {
                'report_id', 'summary', 'pattern',
                'success_factor', 'failure_factor',
                'confidence', 'patterns', 'contradictions',
                'mode',
            }
        """
        with self._lock:
            now = now if now is not None else time.time()
            if not self._enabled:
                return self._empty_report("反思引擎停用", now)
            patterns = self._patterns.analyze(records, now)
            contradictions = []
            # 逐条新经历检测矛盾 (最后 N 条)
            for r in records[-5:]:
                c = self._contradictions.detect(
                    r, identity_state, records[:-1],
                )
                if c["conflict"]:
                    contradictions.append(c)
            summary = self._build_summary(records, patterns)
            success_factor = self._success_factor(
                records, patterns,
            )
            failure_factor = self._failure_factor(
                records, patterns,
            )
            confidence = self._confidence(records, patterns)
            report = {
                "report_id": "cr_" + uuid.uuid4().hex[:8],
                "summary": summary,
                "pattern": (
                    patterns[0]["meaning"] if patterns else ""
                ),
                "success_factor": success_factor,
                "failure_factor": failure_factor,
                "confidence": round(confidence, 4),
                "patterns": [dict(p) for p in patterns],
                "contradictions": [
                    dict(c) for c in contradictions
                ],
                "mode": "rule_based",
                "generated_at": now,
            }
            self._reports.append(report)
            return dict(report)

    def _empty_report(self, reason: str, now: float) -> Dict[str, Any]:
        report = {
            "report_id": "cr_" + uuid.uuid4().hex[:8],
            "summary": reason,
            "pattern": "", "success_factor": "",
            "failure_factor": "", "confidence": 0.0,
            "patterns": [], "contradictions": [],
            "mode": "rule_based", "generated_at": now,
        }
        self._reports.append(report)
        return dict(report)

    # ── 总结子步骤 (可解释) ─────────────────────────────────────
    @staticmethod
    def _build_summary(records: List[Dict[str, Any]],
                       patterns: List[Dict[str, Any]]) -> str:
        """认知总结"""
        total = len(records)
        failures = sum(
            1 for r in records if r.get("type") == "failure"
        )
        if patterns:
            top = patterns[0]
            return (
                f"观察 {total} 条经历: 发现模式 "
                f"'{top['meaning'][:30]}', "
                f"失败 {failures} 次"
            )
        return (
            f"观察 {total} 条经历: 暂无明显模式 "
            f"({failures} 次失败)"
        )

    @staticmethod
    def _success_factor(records: List[Dict[str, Any]],
                        patterns: List[Dict[str, Any]]) -> str:
        """成功因素"""
        success = sum(
            1 for r in records
            if str(r.get("result", "")).find("成功") >= 0
            or r.get("type") in ("interaction", "improvement",
                                 "engineering")
        )
        if patterns:
            sp = [p for p in patterns
                  if p["type"] == "success_strategy"]
            if sp:
                return f"有效策略: {sp[0]['trigger'][:30]}"
        return f"成功比例 {success}/{len(records) if records else 0}"

    @staticmethod
    def _failure_factor(records: List[Dict[str, Any]],
                        patterns: List[Dict[str, Any]]) -> str:
        """失败因素"""
        failures = [
            r for r in records if r.get("type") == "failure"
        ]
        if patterns:
            pp = [p for p in patterns
                  if p["type"] == "problem_pattern"]
            if pp:
                return f"问题模式: {pp[0]['trigger'][:30]}"
        if failures:
            return f"失败 {len(failures)} 次, 原因待分析"
        return "无失败记录"

    @staticmethod
    def _confidence(records: List[Dict[str, Any]],
                    patterns: List[Dict[str, Any]]) -> float:
        """置信度: 样本 + 模式"""
        base = min(1.0, len(records) / 10.0) * 0.6
        pattern_score = min(1.0, len(patterns) / 3.0) * 0.4
        return round(min(1.0, base + pattern_score), 4)

    # ── 查询 ─────────────────────────────────────────────────────
    def latest(self) -> Optional[Dict[str, Any]]:
        """最新认知报告"""
        with self._lock:
            if not self._reports:
                return None
            return dict(self._reports[-1])

    def stats(self) -> Dict[str, Any]:
        """反思统计"""
        with self._lock:
            reports = list(self._reports)
        return {
            "mode": "rule_based",
            "reflection_count": len(reports),
            "pattern_count": self._patterns.stats()[
                "pattern_count"],
            "conflict_count": self._contradictions.stats()[
                "conflict_count"],
        }

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = len(self._reports)
            self._reports.clear()
            self._patterns.clear()
            self._contradictions.clear()
            return n


__all__ = [
    "CognitiveReflectionEngine",
    "ReflectionError",
]
