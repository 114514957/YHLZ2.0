"""
YHLZ Embodied AI V6.3 - 记忆网关 (Memory Gate)

职责:
    - 感知记忆批准层:
      Memory Candidate → Candidate Validator → Reflection Check
      → Approval → Experience Memory
    - 禁止感知直接成为经历 (必须经过批准)

流程:
    Perception → Candidate → Reflection → Approval → Experience Memory

安全:
    - 批准前不触碰人格/行动
    - 拒绝必须有审计
    - 写入经历 source="vision_perception"

设计原则:
    - 记忆必须经过批准 (原则2)
    - 纯规则 (无黑盒)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

from backend.embodied.companion.perception.memory_gate.approval_rule import (
    ApprovalRule,
)
from backend.embodied.companion.perception.memory_gate.candidate_validator import (
    CandidateValidator,
)
from backend.embodied.companion.perception.memory_gate.reflection.counterfactual_check import (
    CounterfactualCheck,
)
from backend.embodied.companion.perception.memory_gate.reflection.reflection_evaluator import (
    ReflectionEvaluator,
)

logger = logging.getLogger(__name__)


class MemoryGateError(Exception):
    """记忆网关操作异常"""


class MemoryGate:
    """记忆网关 (候选 → 批准 → 经历)

    用法:
        gate = MemoryGate()
        result = gate.process(candidate, store_fn, reflect_fn)
    """

    def __init__(
        self,
        validator: Optional[CandidateValidator] = None,
        rule: Optional[ApprovalRule] = None,
        evaluator: Optional[ReflectionEvaluator] = None,
        counterfactual: Optional[CounterfactualCheck] = None,
        enabled: bool = True,
    ):
        self._lock = threading.RLock()
        self._validator = validator or CandidateValidator()
        self._rule = rule or ApprovalRule()
        self._evaluator = evaluator or ReflectionEvaluator()
        self._counterfactual = counterfactual or CounterfactualCheck()
        self._enabled = bool(enabled)
        self._history: List[Dict[str, Any]] = []

    # ── 处理主入口 ───────────────────────────────────────────────
    def process(
        self,
        candidate: Dict[str, Any],
        store_fn=None,
        reflect_fn=None,
        now: Optional[float] = None,
    ) -> Dict[str, Any]:
        """处理候选: 校验 → 反思 → 批准 → 写入

        Args:
            candidate: 记忆候选
            store_fn: 写入回调 (experience_manager.store_from_event)
            reflect_fn: 反思回调 (可选, 提供上下文)

        Returns:
            {
                'gate_id', 'candidate_id', 'status',
                'reason', 'confidence', 'steps': [...],
                'mode',
            }
        """
        with self._lock:
            now = now if now is not None else time.time()
            steps: List[Dict[str, Any]] = []
            if not self._enabled:
                return {
                    "gate_id": "gate_" + uuid.uuid4().hex[:8],
                    "candidate_id": candidate.get("candidate_id", ""),
                    "status": "DISABLED",
                    "reason": "记忆网关停用",
                    "confidence": 0.0,
                    "steps": [{"step": "disabled", "ok": True,
                               "reason": "网关停用"}],
                    "mode": "rule_based",
                }
            # 1. Candidate Validator
            ok, reason = self._validator.validate(candidate)
            steps.append({"step": "candidate_validator", "ok": ok,
                          "reason": reason})
            if not ok:
                return self._finish(candidate, "rejected", reason,
                                    0.0, steps, now)
            # 2. Reflection Evaluation (V6.4 深度评估, Advisor)
            known = []
            if reflect_fn is not None:
                try:
                    known = reflect_fn(candidate) or []
                except Exception as e:
                    logger.warning(f"[MemoryGate] 反思回调异常: {e}")
                    known = []
            try:
                reflection = self._evaluator.evaluate(
                    candidate, known,
                )
            except Exception as e:
                logger.warning(f"[MemoryGate] 评估异常: {e}")
                reflection = {
                    "reflection_score": 0.5,
                    "recommendation": "neutral",
                    "reason": f"评估异常: {e}",
                }
            steps.append({"step": "reflection_evaluation",
                          "ok": True,
                          "reason": (
                              f"反思评分 {reflection['reflection_score']}, "
                              f"建议 {reflection['recommendation']}"
                          )})
            # Advisor 建议被 Authority 采纳 (Reflection 不是决策者,
            # 但建议影响批准)
            if reflection["recommendation"] == "reject":
                return self._finish(
                    candidate, "rejected",
                    f"反思评估建议拒绝: "
                    f"{reflection.get('recommendation_reason', '')}",
                    float(reflection["reflection_score"]), steps,
                    now,
                )
            # 2.5 Counterfactual Check (V6.4 反事实验证)
            try:
                cf = self._counterfactual.check(candidate)
            except Exception as e:
                logger.warning(f"[MemoryGate] 反事实验证异常: {e}")
                cf = {"status": "neutral", "reason": str(e)}
            steps.append({"step": "counterfactual_check",
                          "ok": cf["status"] != "fails",
                          "reason": cf["reason"]})
            if cf["status"] == "fails":
                return self._finish(
                    candidate, "rejected",
                    f"反事实验证失败: {cf['reason']}",
                    cf.get("score", 0.0), steps, now,
                )
            # 3. Approval (六维最终评分)
            approval = self._rule.evaluate(
                candidate,
                reflection_score=reflection["reflection_score"],
            )
            steps.append({"step": "approval", "ok": approval[
                "status"] == "approved",
                "reason": approval["reason"]})
            if approval["status"] != "approved":
                return self._finish(
                    candidate, "rejected", approval["reason"],
                    approval["confidence"], steps, now,
                )
            # 4. Experience Memory (写入)
            if store_fn is None:
                return self._finish(
                    candidate, "pending_store",
                    "批准但未提供写入回调", approval["confidence"],
                    steps, now,
                )
            try:
                stored = store_fn(candidate)
                steps.append({"step": "store", "ok": True,
                              "reason": "已写入经历"})
                result = self._finish(
                    candidate, "approved",
                    approval["reason"], approval["confidence"],
                    steps, now,
                )
                result["stored"] = stored
                return result
            except Exception as e:
                logger.warning(f"[MemoryGate] 写入失败: {e}")
                return self._finish(
                    candidate, "store_failed",
                    f"批准但写入失败: {e}",
                    approval["confidence"], steps, now,
                )

    def _finish(self, candidate, status, reason, confidence,
                steps, now) -> Dict[str, Any]:
        """完成处理 (记录历史)"""
        result = {
            "gate_id": "gate_" + uuid.uuid4().hex[:8],
            "candidate_id": candidate.get("candidate_id", ""),
            "status": status,
            "reason": reason,
            "confidence": round(confidence, 4),
            "steps": steps,
            "mode": "rule_based",
            "processed_at": now,
        }
        self._history.append(result)
        return dict(result)

    # ── 查询 ─────────────────────────────────────────────────────
    def stats(self) -> Dict[str, Any]:
        """网关统计"""
        with self._lock:
            history = list(self._history)
        by_status: Dict[str, int] = {}
        for h in history:
            by_status[h["status"]] = by_status.get(h["status"], 0) + 1
        return {
            "mode": "rule_based",
            "candidate_count": len(history),
            "approved_count": by_status.get("approved", 0),
            "rejected_count": by_status.get("rejected", 0),
            "by_status": by_status,
            "thresholds": self._rule.thresholds(),
        }

    def history(self, limit: int = 20) -> List[Dict[str, Any]]:
        """处理历史"""
        with self._lock:
            recent = list(reversed(self._history))
            if limit > 0:
                recent = recent[:limit]
            return [dict(h) for h in recent]

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = len(self._history)
            self._history.clear()
            return n


__all__ = [
    "MemoryGate",
    "MemoryGateError",
]
