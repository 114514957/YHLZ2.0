"""
YHLZ Embodied AI V6.1.1 - 情绪引擎 (Emotion Engine)

职责:
    - 状态更新 / 状态查询 / 状态统计 / 状态衰减
    - 接口: update(context) / decay() / get_state() / get_stats()
    - 稳定性: 连续失败/连续成功有限幅, 回归基线

流程:
    Interaction → Event → Emotion Representation → Growth Rhythm

安全隔离:
    - 情绪不能改变: Personality Base / Core Value / Mission /
      Decision Boundary (完全不触碰 Identity Layer)

设计原则:
    - 规则驱动 (禁止 LLM 情绪推断)
    - 每次变化: 记忆 + 审计 (禁止静默修改)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, Optional

from backend.embodied.companion.emotion.emotion_audit import (
    EmotionAudit,
)
from backend.embodied.companion.emotion.emotion_decay import (
    EmotionDecay,
)
from backend.embodied.companion.emotion.emotion_memory import (
    EmotionMemory,
)
from backend.embodied.companion.emotion.emotion_rules import (
    EMOTION_CONTEXTS,
    rule_for,
)
from backend.embodied.companion.emotion.emotion_state import (
    EMOTION_DIMENSIONS,
    EmotionState,
)

logger = logging.getLogger(__name__)


class EmotionEngineError(Exception):
    """情绪引擎操作异常"""


class EmotionEngine:
    """情绪引擎 (可计算/可解释/可审计)

    用法:
        engine = EmotionEngine()
        engine.update("success")
        engine.decay()
        state = engine.get_state()
    """

    def __init__(
        self,
        enabled: bool = True,
        update_step: float = 0.1,
        decay_rate: float = 0.05,
        decay_window_days: float = 7.0,
        consecutive_limit: int = 3,
        floor: float = 0.1,
        state: Optional[EmotionState] = None,
        decay: Optional[EmotionDecay] = None,
        memory: Optional[EmotionMemory] = None,
        audit: Optional[EmotionAudit] = None,
    ):
        if not (0.0 < update_step <= 1.0):
            raise EmotionEngineError(
                f"update_step 必须在 (0,1], 当前: {update_step}"
            )
        if consecutive_limit <= 1:
            raise EmotionEngineError(
                f"consecutive_limit 必须 > 1, 当前: "
                f"{consecutive_limit}"
            )
        self._lock = threading.RLock()
        self._enabled = bool(enabled)
        self._step = float(update_step)
        self._consecutive_limit = int(consecutive_limit)
        self._state = state or EmotionState(floor=float(floor))
        self._decay = decay or EmotionDecay(
            rate=decay_rate, window_days=decay_window_days,
        )
        self._memory = memory or EmotionMemory()
        self._audit = audit or EmotionAudit()
        # 连续计数 (稳定性)
        self._consecutive_failures = 0
        self._consecutive_successes = 0
        # 统计
        self._update_count = 0
        self._decay_count = 0
        self._reason_distribution: Dict[str, int] = {}
        self._change_sum = 0.0

    # ── 更新 ─────────────────────────────────────────────────────
    def update(self, context: str,
               now: Optional[float] = None) -> Dict[str, Any]:
        """按情境更新情绪 (规则驱动, 可解释)

        Args:
            context: 情境 (success/failure/consecutive_fail/
                creative_done/creative_rejected/relationship_up/
                relationship_down/idle)

        Returns:
            更新后的情绪状态
        """
        with self._lock:
            if not self._enabled:
                raise EmotionEngineError("情绪引擎已停用")
            if context not in EMOTION_CONTEXTS:
                raise EmotionEngineError(
                    f"非法情境: {context} "
                    f"(可选: {EMOTION_CONTEXTS})"
                )
            before = self._state.to_dict()
            rule = rule_for(context)
            # 稳定性: 连续计数调整
            if context == "success":
                self._consecutive_successes += 1
                self._consecutive_failures = 0
            elif context == "failure":
                self._consecutive_failures += 1
                self._consecutive_successes = 0
            else:
                self._consecutive_failures = 0
                self._consecutive_successes = 0
            deltas = self._apply_stability(rule["deltas"], context)
            # 应用
            reason = rule["reason"]
            after = self._state.apply(deltas, reason)
            impact = {
                d: round(after[d] - before[d], 4)
                for d in EMOTION_DIMENSIONS
            }
            # 记忆 + 审计 (禁止静默修改)
            mem = self._memory.record(
                event=context, before=before, after=after,
                reason=reason, impact=impact,
            )
            self._audit.record(
                action="update", detail=context, ref_id=mem[
                    "memory_id"],
            )
            self._update_count += 1
            self._reason_distribution[context] = \
                self._reason_distribution.get(context, 0) + 1
            self._change_sum += sum(abs(v) for v in impact.values())
            return dict(after)

    def _apply_stability(self, deltas: Dict[str, float],
                         context: str) -> Dict[str, float]:
        """稳定性规则: 连续事件有限幅 (防剧烈震荡/无限下降)"""
        out = dict(deltas)
        if context == "failure" and \
                self._consecutive_failures >= self._consecutive_limit:
            out = {k: v * 0.5 for k, v in out.items()}
        elif context == "success" and \
                self._consecutive_successes >= self._consecutive_limit:
            out = {k: v * 0.5 for k, v in out.items()}
        return {k: v * self._step for k, v in out.items()}

    # ── 衰减 ─────────────────────────────────────────────────────
    def decay(self, now: Optional[float] = None) -> Dict[str, Any]:
        """自然衰减 (回归基线)"""
        with self._lock:
            if not self._enabled:
                raise EmotionEngineError("情绪引擎已停用")
            before = self._state.to_dict()
            after = self._decay.decay(self._state, now)
            changed = after != before
            if changed:
                self._memory.record(
                    event="decay", before=before, after=after,
                    reason="自然衰减回归基线",
                )
                self._audit.record(action="decay",
                                   detail="自然衰减")
                self._decay_count += 1
            return dict(after)

    # ── 查询 ─────────────────────────────────────────────────────
    def get_state(self) -> Dict[str, Any]:
        """当前情绪状态"""
        with self._lock:
            return self._state.to_dict()

    def get_stats(self) -> Dict[str, Any]:
        """情绪统计"""
        with self._lock:
            return {
                "mode": "rule_based",
                "enabled": self._enabled,
                "state": self._state.to_dict(),
                "update_count": self._update_count,
                "decay_count": self._decay_count,
                "reason_distribution": dict(self._reason_distribution),
                "avg_change": round(
                    self._change_sum / self._update_count
                    if self._update_count else 0.0, 4,
                ),
                "consecutive_failures": self._consecutive_failures,
                "consecutive_successes": self._consecutive_successes,
                "baseline": self._state.baseline(),
            }

    def memory(self) -> Dict[str, Any]:
        """情绪历史统计"""
        with self._lock:
            return self._memory.stats()

    def history(self, limit: int = 50) -> Dict[str, Any]:
        """情绪历史 (供 Reflection/Growth)"""
        with self._lock:
            return {
                "mode": "rule_based",
                "records": self._memory.history(limit=limit),
                "stats": self._memory.stats(),
            }

    def audit_report(self, limit: int = 100) -> Dict[str, Any]:
        """情绪审计报告"""
        return self._audit.report(limit=limit)

    # ── 恢复 (快照) ──────────────────────────────────────────────
    def restore_state(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """恢复情绪状态 (快照恢复)"""
        with self._lock:
            before = self._state.to_dict()
            after = self._state.set_state(state, reason="快照恢复")
            self._memory.record(
                event="restore", before=before, after=after,
                reason="快照恢复",
            )
            self._audit.record(action="restore", detail="快照恢复")
            return dict(after)

    # ── 生命周期 ─────────────────────────────────────────────────
    def reset(self) -> Dict[str, Any]:
        """重置 (测试隔离)"""
        with self._lock:
            self._state = EmotionState(
                floor=self._state._floor,
            )
            n_mem = self._memory.clear()
            n_audit = self._audit.clear()
            self._consecutive_failures = 0
            self._consecutive_successes = 0
            self._update_count = 0
            self._decay_count = 0
            self._reason_distribution = {}
            self._change_sum = 0.0
            return {"memory": n_mem, "audit": n_audit}


__all__ = [
    "EmotionEngine",
    "EmotionEngineError",
]
