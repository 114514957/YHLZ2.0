"""
YHLZ Embodied AI V5.5 - 自适应人格引擎 (Adaptive Personality Engine)

职责:
    - 人格状态管理: 核心人格 (base) 稳定 + 表现维度自适应 (warmth/patience/
      humor/serious, 0.0~1.0)
    - 情境分析: 任务类型/执行结果 → 人格情境 (success/failure/
      consecutive_fail/casual_chat/serious_task)
    - 规则调整: 情境 → 维度调整 (纯规则, 步长可配)
    - 人格审计: 每次调整记录 (context/before_state/adjustment/after_state/
      result/timestamp)
    - 互动统计: interaction_count/success_count/failure_count/success_rate
      (只存统计, 禁止保存聊天)

数据模型:
    PersonalityState:
    {
        base: "铁哥们",
        dimensions: {warmth, patience, humor, serious},
        interactions: n,
        success_rate: 0.0~1.0,
        last_adjust: "情境说明",
    }

设计原则:
    - 核心人格 (base) 不可修改 (一个人格 / 一个核心意识 / 一个决策中心)
    - 表现人格自适应 (纯规则, 禁止黑盒人格优化)
    - 互动统计只存数字 (不保存聊天, 不写 Agent Memory)
    - 线程安全 (RLock)
    - 单例 + reset (get_personality_service / reset_personality_service)
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

from backend.embodied.companion.personality_rules import (
    BASE_DIMENSIONS,
    PERSONALITY_CONTEXTS,
    PERSONALITY_DIMENSIONS,
    PersonalityRuleError,
    adjustment_reason,
    apply_adjustment,
    rule_for,
)

logger = logging.getLogger(__name__)


class PersonalityError(Exception):
    """自适应人格操作异常"""


class PersonalityState:
    """人格状态 (可序列化)

    Attributes:
        base:        核心人格 (不可修改)
        dimensions:  表现维度 (warmth/patience/humor/serious)
        interactions:互动次数
        success_count:成功次数
        failure_count:失败次数
        last_adjust: 最近调整说明
    """

    def __init__(
        self,
        base: str = "铁哥们",
        dimensions: Optional[Dict[str, float]] = None,
    ):
        self.base = base
        self.dimensions = dict(
            dimensions or BASE_DIMENSIONS,
        )
        self.interactions = 0
        self.success_count = 0
        self.failure_count = 0
        self.last_adjust = ""

    @property
    def success_rate(self) -> float:
        """互动成功率 (只统计)"""
        total = self.success_count + self.failure_count
        return round(self.success_count / total, 4) if total else 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "base": self.base,
            "dimensions": dict(self.dimensions),
            "interactions": self.interactions,
            "success_rate": self.success_rate,
            "last_adjust": self.last_adjust,
        }

    def snapshot(self) -> Dict[str, Any]:
        """状态快照 (审计 before/after)"""
        return self.to_dict()


class PersonalityAuditRecord:
    """人格调整审计记录 (V5.6: 关系上下文/衰减原因/窗口统计)

    Attributes:
        record_id:           记录 ID
        context:             情境
        before_state:        调整前状态
        adjustment:          调整说明
        after_state:         调整后状态
        result:              调整结果 (applied/limited)
        timestamp:           记录时间
        relationship_context: 关系上下文 (V5.6, 可选)
        decay_reason:        衰减原因 (V5.6, 可选)
        window_statistics:   窗口统计 (V5.6, 可选)
    """

    def __init__(self, context: str, before_state: Dict[str, Any],
                 adjustment: str, after_state: Dict[str, Any],
                 result: str, timestamp: float,
                 relationship_context: Optional[Dict[str, Any]] = None,
                 decay_reason: Optional[str] = None,
                 window_statistics: Optional[Dict[str, Any]] = None):
        self.record_id = "pa_" + uuid.uuid4().hex[:8]
        self.context = context
        self.before_state = dict(before_state)
        self.adjustment = adjustment
        self.after_state = dict(after_state)
        self.result = result
        self.timestamp = timestamp
        self.relationship_context = dict(relationship_context or {})
        self.decay_reason = decay_reason or ""
        self.window_statistics = dict(window_statistics or {})

    def to_dict(self) -> Dict[str, Any]:
        return {
            "record_id": self.record_id,
            "context": self.context,
            "before_state": dict(self.before_state),
            "adjustment": self.adjustment,
            "after_state": dict(self.after_state),
            "result": self.result,
            "timestamp": self.timestamp,
            "relationship_context": dict(self.relationship_context),
            "decay_reason": self.decay_reason,
            "window_statistics": dict(self.window_statistics),
        }


class AdaptivePersonalityEngine:
    """自适应人格引擎 (核心稳定 + 表现自适应)

    用法:
        engine = AdaptivePersonalityEngine(base="铁哥们", step=0.1)
        state = engine.personality()
        result = engine.adjust("success")
        audit = engine.audit()
    """

    def __init__(
        self,
        base: str = "铁哥们",
        step: float = 0.1,
        enabled: bool = True,
        max_audit: int = 200,
    ):
        if step <= 0:
            raise PersonalityError(f"step 必须 > 0, 当前: {step}")
        if max_audit <= 0:
            raise PersonalityError(f"max_audit 必须 > 0, 当前: {max_audit}")
        self._lock = threading.RLock()
        self._base = base
        self._step = float(step)
        self._enabled = bool(enabled)
        self._max_audit = int(max_audit)
        self._state = PersonalityState(base=base)
        self._audit: List[PersonalityAuditRecord] = []
        # 连续失败计数 (情境判定)
        self._consecutive_failures = 0

    # ── 人格状态 ──────────────────────────────────────────────────
    def personality(self) -> Dict[str, Any]:
        """当前人格状态 (维度/统计/调整原因)"""
        with self._lock:
            return self._state.to_dict()

    def reset(self) -> Dict[str, Any]:
        """重置为基础人格 (表现维度恢复基础值, 统计保留)"""
        with self._lock:
            self._state.dimensions = dict(BASE_DIMENSIONS)
            self._state.last_adjust = "重置为基础人格"
            self._consecutive_failures = 0
            return self._state.to_dict()

    # ── 情境分析 ──────────────────────────────────────────────────
    @staticmethod
    def infer_context(
        result: Optional[bool] = None,
        casual: bool = False,
        serious: bool = False,
        consecutive_failures: int = 0,
    ) -> str:
        """情境推断 (规则驱动, 可解释)

        Args:
            result: 执行结果 (True=成功 / False=失败 / None=未知)
            casual: 是否轻松交流
            serious: 是否严肃任务
            consecutive_failures: 连续失败次数

        Returns:
            情境: success / failure / consecutive_fail /
                  casual_chat / serious_task
        """
        if casual:
            return "casual_chat"
        if serious:
            return "serious_task"
        if result is True:
            return "success"
        if result is False:
            if consecutive_failures >= 2:
                return "consecutive_fail"
            return "failure"
        return "casual_chat"

    # ── 规则调整 ──────────────────────────────────────────────────
    def adjust(
        self,
        context: str,
        record_result: bool = True,
    ) -> Dict[str, Any]:
        """人格调整: 情境 → 维度调整 → 审计

        Args:
            context: 情境 (success/failure/consecutive_fail/
                     casual_chat/serious_task)
            record_result: 是否记录互动统计 (True=按情境记录成功/失败)

        Returns:
            {
                'applied': bool, 'context', 'base',
                'dimensions': {...}, 'adjustment': str,
                'result': 'applied' | 'limited' | 'disabled',
                'reason': 可解释原因,
            }

        Raises:
            PersonalityError: 非法情境
        """
        with self._lock:
            if context not in PERSONALITY_CONTEXTS:
                raise PersonalityError(
                    f"非法情境: {context} "
                    f"(可选: {PERSONALITY_CONTEXTS})"
                )
            if not self._enabled:
                return {
                    "applied": False, "context": context,
                    "base": self._base,
                    "dimensions": dict(self._state.dimensions),
                    "adjustment": "人格自适应已停用",
                    "result": "disabled",
                    "reason": "companion_personality_enabled=False",
                }
            before = self._state.snapshot()
            # 互动统计
            if record_result:
                self._state.interactions += 1
                if context in ("success",):
                    self._state.success_count += 1
                    self._consecutive_failures = 0
                elif context in ("failure", "consecutive_fail"):
                    self._state.failure_count += 1
                    self._consecutive_failures += 1
                elif context == "casual_chat":
                    self._consecutive_failures = 0
            # 维度调整
            updated = apply_adjustment(
                self._state.dimensions, context, self._step,
            )
            changed = any(
                updated[d] != self._state.dimensions.get(d)
                for d in PERSONALITY_DIMENSIONS
            )
            self._state.dimensions = updated
            reason = adjustment_reason(context, self._step)
            self._state.last_adjust = reason
            result_tag = "applied" if changed else "limited"
            # 审计记录
            self._audit.append(PersonalityAuditRecord(
                context=context,
                before_state=before,
                adjustment=reason,
                after_state=self._state.snapshot(),
                result=result_tag,
                timestamp=time.time(),
            ))
            if len(self._audit) > self._max_audit:
                self._audit = self._audit[-self._max_audit:]
            logger.info(
                f"[Personality] {context}: {reason} "
                f"(step={self._step})"
            )
            return {
                "applied": True, "context": context,
                "base": self._base,
                "dimensions": dict(self._state.dimensions),
                "adjustment": reason,
                "result": result_tag,
                "reason": reason,
            }

    # ── 互动统计 ──────────────────────────────────────────────────
    def record_interaction(self, success: bool) -> Dict[str, Any]:
        """记录互动 (只存统计, 不保存聊天)

        Args:
            success: 是否成功

        Returns:
            {'interactions', 'success_count', 'failure_count',
             'success_rate'}
        """
        with self._lock:
            self._state.interactions += 1
            if success:
                self._state.success_count += 1
                self._consecutive_failures = 0
            else:
                self._state.failure_count += 1
                self._consecutive_failures += 1
            return self._stats()

    def _stats(self) -> Dict[str, Any]:
        return {
            "interactions": self._state.interactions,
            "success_count": self._state.success_count,
            "failure_count": self._state.failure_count,
            "success_rate": self._state.success_rate,
        }

    def stats(self) -> Dict[str, Any]:
        """互动统计 (只存数字)"""
        with self._lock:
            return self._stats()

    # ── 人格审计 ──────────────────────────────────────────────────
    def audit(self, limit: int = 50) -> Dict[str, Any]:
        """人格审计: 每次调整记录"""
        with self._lock:
            records = list(self._audit)
        recent = list(reversed(records))
        if limit > 0:
            recent = recent[:limit]
        return {
            "mode": "rule_based",
            "total": len(records),
            "recent": [r.to_dict() for r in recent],
        }

    # ── 状态 ──────────────────────────────────────────────────────
    def thresholds(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "base": self._base,
                "step": self._step,
                "enabled": self._enabled,
                "max_audit": self._max_audit,
                "dimensions": list(PERSONALITY_DIMENSIONS),
            }

    def set_enabled(self, enabled: bool) -> None:
        with self._lock:
            self._enabled = bool(enabled)


# ── 单例 (V5.5: get_personality_service / reset_personality_service) ──
_personality_service: Optional[AdaptivePersonalityEngine] = None
_personality_lock = threading.RLock()


def get_personality_service() -> AdaptivePersonalityEngine:
    """获取人格引擎单例"""
    global _personality_service
    with _personality_lock:
        if _personality_service is None:
            _personality_service = AdaptivePersonalityEngine()
        return _personality_service


def reset_personality_service() -> AdaptivePersonalityEngine:
    """重置人格引擎单例 (测试隔离)"""
    global _personality_service
    with _personality_lock:
        _personality_service = AdaptivePersonalityEngine()
        return _personality_service


__all__ = [
    "AdaptivePersonalityEngine",
    "PersonalityAuditRecord",
    "PersonalityError",
    "PersonalityState",
    "get_personality_service",
    "reset_personality_service",
]
