"""
YHLZ Embodied AI V5.9 - 机会检测器 (Opportunity Detector)

职责:
    - 从 Confirmed Experience + Reflection Report + Relationship Context
      中发现潜在价值机会
    - 输出 Opportunity Candidate:
      {problem, current_state, desired_state, gap, evidence[], confidence}

机会来源类型 (可解释):
    - repetition:      重复需求 (同一 trigger 多次出现 → 自动化机会)
    - failure:         反复失败 (同一失败情境多次 → 新方案机会)
    - pattern:         有效模式 (规律行为 → 固化机会)
    - improvement:     反思建议 (Reflection Report suggestion → 升级机会)
    - relationship:    关系偏好 (高信任 + 成功互动 → 个性化机会)

设计原则:
    - 只基于 CONFIRMED 经验 (未验证经验禁止进入创造流程)
    - 纯规则检测 (禁止黑盒)
    - 每个机会必须含证据与置信度 (可回溯)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class OpportunityError(Exception):
    """机会检测操作异常"""


# 机会来源类型白名单 (可解释)
OPPORTUNITY_SOURCE_TYPES: List[str] = [
    "repetition",     # 重复需求 → 自动化
    "failure",        # 反复失败 → 新方案
    "pattern",        # 有效模式 → 固化
    "improvement",    # 反思建议 → 升级
    "relationship",   # 关系偏好 → 个性化
]


class OpportunityDetector:
    """机会检测器 (可靠经验 → 机会候选)

    用法:
        detector = OpportunityDetector()
        candidates = detector.detect(confirmed_experiences,
                                     reflection_report,
                                     relationship)
    """

    def __init__(
        self,
        min_evidence: int = 2,
        repetition_min_occurrences: int = 3,
        failure_min_occurrences: int = 2,
        relationship_trust_min: float = 0.7,
        max_opportunities: int = 20,
    ):
        if min_evidence <= 0:
            raise OpportunityError(
                f"min_evidence 必须 > 0, 当前: {min_evidence}"
            )
        if repetition_min_occurrences <= 1:
            raise OpportunityError(
                f"repetition_min_occurrences 必须 > 1, "
                f"当前: {repetition_min_occurrences}"
            )
        if failure_min_occurrences <= 0:
            raise OpportunityError(
                f"failure_min_occurrences 必须 > 0, "
                f"当前: {failure_min_occurrences}"
            )
        if not (0.0 <= relationship_trust_min <= 1.0):
            raise OpportunityError(
                f"relationship_trust_min 必须在 [0,1], "
                f"当前: {relationship_trust_min}"
            )
        self._lock = threading.RLock()
        self._min_evidence = int(min_evidence)
        self._repetition_min = int(repetition_min_occurrences)
        self._failure_min = int(failure_min_occurrences)
        self._trust_min = float(relationship_trust_min)
        self._max = int(max_opportunities)
        self._candidates: List[Dict[str, Any]] = []

    # ── 检测主入口 ────────────────────────────────────────────────
    def detect(
        self,
        confirmed_experiences: List[Dict[str, Any]],
        reflection_report: Optional[Dict[str, Any]] = None,
        relationship: Optional[Dict[str, Any]] = None,
        now: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """检测机会 (规则驱动, 可解释)

        Args:
            confirmed_experiences: 只 CONFIRMED 经历列表
                (未验证经验禁止进入创造流程)
            reflection_report: Reflection Report (可空)
            relationship: 关系上下文 (可空, 含 trust 等)

        Returns:
            Opportunity Candidate 列表
        """
        with self._lock:
            now = now if now is not None else time.time()
            candidates: List[Dict[str, Any]] = []
            # 1. 重复需求 → 自动化机会
            candidates += self._detect_repetition(
                confirmed_experiences, now,
            )
            # 2. 反复失败 → 新方案机会
            candidates += self._detect_failure(
                confirmed_experiences, now,
            )
            # 3. 有效模式 → 固化机会
            candidates += self._detect_pattern(
                reflection_report, now,
            )
            # 4. 反思建议 → 升级机会
            candidates += self._detect_improvement(
                reflection_report, now,
            )
            # 5. 关系偏好 → 个性化机会
            candidates += self._detect_relationship(
                confirmed_experiences, relationship, now,
            )
            # 去重 (同一 trigger + source_type)
            seen = {
                (c["trigger"], c["source_type"]) for c in candidates
            }
            unique = [
                c for c in candidates
                if (c["trigger"], c["source_type"]) in seen
                and not self._is_duplicate(
                    self._candidates, c["trigger"], c["source_type"],
                )
            ]
            # 按置信度降序 + 上限
            unique.sort(key=lambda c: c["confidence"], reverse=True)
            unique = unique[: self._max]
            self._candidates.extend(unique)
            return [dict(c) for c in unique]

    # ── 子检测器 (可解释) ────────────────────────────────────────
    def _detect_repetition(
        self, records: List[Dict[str, Any]], now: float,
    ) -> List[Dict[str, Any]]:
        """重复需求检测: 同一 trigger 多次 → 自动化机会"""
        counts: Dict[str, Dict[str, Any]] = {}
        for r in records:
            key = str(r.get("trigger", "")).strip()
            if not key:
                continue
            entry = counts.setdefault(key, {"records": [], "ids": []})
            entry["records"].append(r)
            entry["ids"].append(r.get("id", ""))
        out: List[Dict[str, Any]] = []
        for trigger, entry in counts.items():
            if len(entry["records"]) < self._repetition_min:
                continue
            out.append(self._build_candidate(
                source_type="repetition",
                trigger=trigger,
                problem=f"用户/环境重复需要 '{trigger}'",
                current_state="每次手动/重复处理",
                desired_state="一键/自动完成",
                gap="重复流程缺乏自动化",
                evidence=entry["ids"][-self._min_evidence:],
                records=entry["records"],
                now=now,
            ))
        return out

    def _detect_failure(
        self, records: List[Dict[str, Any]], now: float,
    ) -> List[Dict[str, Any]]:
        """反复失败检测: 同一失败情境多次 → 新方案机会"""
        counts: Dict[str, Dict[str, Any]] = {}
        for r in records:
            if r.get("type") != "failure":
                continue
            key = str(r.get("trigger", "")).strip()
            if not key:
                continue
            entry = counts.setdefault(key, {"records": [], "ids": []})
            entry["records"].append(r)
            entry["ids"].append(r.get("id", ""))
        out: List[Dict[str, Any]] = []
        for trigger, entry in counts.items():
            if len(entry["records"]) < self._failure_min:
                continue
            out.append(self._build_candidate(
                source_type="failure",
                trigger=trigger,
                problem=f"情境 '{trigger}' 反复失败 "
                        f"({len(entry['records'])} 次)",
                current_state="按现有策略执行",
                desired_state="采用新方案规避失败",
                gap="现有策略无法解决该情境",
                evidence=entry["ids"][-self._min_evidence:],
                records=entry["records"],
                now=now,
            ))
        return out

    def _detect_pattern(
        self, report: Optional[Dict[str, Any]], now: float,
    ) -> List[Dict[str, Any]]:
        """有效模式检测: Reflection 有效模式 → 固化机会"""
        out: List[Dict[str, Any]] = []
        if not report:
            return out
        patterns = report.get("patterns", []) or []
        for p in patterns[:5]:
            trigger = str(p.get("trigger", "")).strip()
            if not trigger:
                continue
            out.append(self._build_candidate(
                source_type="pattern",
                trigger=trigger,
                problem=f"存在规律行为 '{trigger}' "
                        f"({p.get('occurrences', 0)} 次)",
                current_state="每次按规则执行",
                desired_state="固化为稳定能力",
                gap="规律行为未固化为能力",
                evidence=[],  # 模式证据来自反思报告
                records=[],
                now=now,
                extra={
                    "pattern_lesson": p.get("lesson", ""),
                },
            ))
        return out

    def _detect_improvement(
        self, report: Optional[Dict[str, Any]], now: float,
    ) -> List[Dict[str, Any]]:
        """反思建议检测: Reflection suggestion → 升级机会"""
        out: List[Dict[str, Any]] = []
        if not report:
            return out
        suggestion = str(report.get("suggestion", "")).strip()
        if not suggestion or suggestion.startswith("暂无"):
            return out
        trigger = suggestion.split(":")[0][:40]
        out.append(self._build_candidate(
            source_type="improvement",
            trigger=trigger,
            problem=suggestion,
            current_state="保持当前策略",
            desired_state="按改进方向升级",
            gap="改进建议未转化为创造方案",
            evidence=[],
            records=[],
            now=now,
            extra={
                "suggestion": suggestion,
                "report_id": report.get("report_id", ""),
            },
        ))
        return out

    def _detect_relationship(
        self, records: List[Dict[str, Any]],
        relationship: Optional[Dict[str, Any]], now: float,
    ) -> List[Dict[str, Any]]:
        """关系偏好检测: 高信任 + 成功互动 → 个性化机会"""
        out: List[Dict[str, Any]] = []
        if not relationship:
            return out
        trust = float(relationship.get("trust", 0.0))
        if trust < self._trust_min:
            return out
        successes = [
            r for r in records
            if str(r.get("result", "")).find("成功") >= 0
            or r.get("type") in ("interaction", "improvement")
        ]
        if not successes:
            return out
        counts: Dict[str, int] = {}
        for r in successes:
            key = str(r.get("trigger", "")).strip()
            if key:
                counts[key] = counts.get(key, 0) + 1
        if not counts:
            return out
        top = max(counts.items(), key=lambda kv: kv[1])
        ids = [
            r.get("id", "") for r in successes
            if r.get("trigger", "").strip() == top[0]
        ]
        out.append(self._build_candidate(
            source_type="relationship",
            trigger=top[0],
            problem=f"高信任用户常做 '{top[0]}' ({counts[top[0]]} 次)",
            current_state="每次按通用方式回应",
            desired_state="按偏好个性化回应",
            gap="缺乏个性化服务",
            evidence=ids[-self._min_evidence:],
            records=successes,
            now=now,
            extra={"trust": trust},
        ))
        return out

    # ── 候选构建与置信度 (可解释) ────────────────────────────────
    def _build_candidate(
        self,
        source_type: str,
        trigger: str,
        problem: str,
        current_state: str,
        desired_state: str,
        gap: str,
        evidence: List[str],
        records: List[Dict[str, Any]],
        now: float,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """构建机会候选 (含置信度)"""
        confidence = self._confidence(
            len(evidence) if evidence else len(records),
            records,
        )
        candidate = {
            "opportunity_id": "opp_" + uuid.uuid4().hex[:8],
            "problem": problem,
            "current_state": current_state,
            "desired_state": desired_state,
            "gap": gap,
            "source_type": source_type,
            "trigger": trigger,
            "evidence": list(evidence),
            "confidence": round(confidence, 4),
            "created_at": now,
        }
        if extra:
            candidate.update(extra)
        return candidate

    @staticmethod
    def _confidence(evidence_count: int,
                    records: List[Dict[str, Any]]) -> float:
        """置信度规则:
            - 基础 0.3
            - 证据每 +1 → +0.15 (上限 +0.45)
            - 高价值经验 (value>=0.6) 比例 ≥ 0.5 → +0.15
            - 成功率 ≥ 0.7 → +0.1
        """
        score = 0.3
        score += min(0.45, 0.15 * max(0, evidence_count - 1))
        if records:
            high_value = sum(
                1 for r in records if float(r.get("value", 0.0)) >= 0.6
            )
            if high_value / len(records) >= 0.5:
                score += 0.15
            success = sum(
                1 for r in records
                if str(r.get("result", "")).find("成功") >= 0
                or r.get("type") in ("interaction", "improvement",
                                     "engineering")
            )
            if success / len(records) >= 0.7:
                score += 0.1
        return min(0.95, score)

    @staticmethod
    def _is_duplicate(candidates: List[Dict[str, Any]],
                      trigger: str, source_type: str) -> bool:
        """同 trigger + 来源不重复检测"""
        for c in candidates:
            if c["trigger"] == trigger and c["source_type"] == source_type:
                return True
        return False

    # ── 查询 ──────────────────────────────────────────────────────
    def get(self, opportunity_id: str) -> Optional[Dict[str, Any]]:
        """查询机会候选"""
        with self._lock:
            for c in self._candidates:
                if c["opportunity_id"] == opportunity_id:
                    return dict(c)
            return None

    def by_source_type(self, source_type: str) -> List[Dict[str, Any]]:
        """按来源类型查询"""
        if source_type not in OPPORTUNITY_SOURCE_TYPES:
            raise OpportunityError(
                f"非法来源类型: {source_type} "
                f"(可选: {OPPORTUNITY_SOURCE_TYPES})"
            )
        with self._lock:
            return [
                dict(c) for c in self._candidates
                if c["source_type"] == source_type
            ]

    def stats(self) -> Dict[str, Any]:
        """机会检测统计"""
        with self._lock:
            by_type: Dict[str, int] = {}
            for c in self._candidates:
                by_type[c["source_type"]] = by_type.get(
                    c["source_type"], 0,
                ) + 1
            avg_conf = (
                sum(c["confidence"] for c in self._candidates)
                / len(self._candidates)
                if self._candidates else 0.0
            )
            return {
                "mode": "rule_based",
                "opportunity_count": len(self._candidates),
                "by_source_type": by_type,
                "avg_confidence": round(avg_conf, 4),
            }

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = len(self._candidates)
            self._candidates.clear()
            return n


__all__ = [
    "OPPORTUNITY_SOURCE_TYPES",
    "OpportunityDetector",
    "OpportunityError",
]
