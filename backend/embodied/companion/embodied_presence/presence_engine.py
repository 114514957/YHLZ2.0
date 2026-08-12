"""
YHLZ Embodied AI V7.0 - 存在表达引擎 (Presence Engine)

职责:
    - 状态机: 内部状态 → Presence Mapper → 状态转移 → 输出
    - 连续性: Presence Memory 支撑长期一致表达
    - 安全: Identity Guard 检查 (表达不触身份)

流程:
    Emotion / Personality / Context
    ↓
    Presence Mapper
    ↓
    Presence State Machine (有限幅)
    ↓
    Identity Guard (表达字段白名单)
    ↓
    Expression Output + Memory + Audit

原则 (形象 ≠ 身份):
    - 表达可以变化, 身份必须稳定
    - 禁止通过表达修改人格/价值/权限
    - 禁止声称拥有未经验证的主观体验

设计原则:
    - 纯规则状态机 (可解释)
    - 强度有限幅 (防剧烈震荡)
    - 每次变化审计 (禁止静默修改)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Callable, Dict, Optional

from backend.embodied.companion.embodied_presence.presence_state import (
    PresenceState,
    PresenceStateError,
)
from backend.embodied.companion.embodied_presence.presence_mapper import (
    PresenceMapper,
    PresenceMapperError,
)
from backend.embodied.companion.embodied_presence.presence_memory import (
    PresenceMemory,
    PresenceMemoryError,
)

logger = logging.getLogger(__name__)


class PresenceEngineError(Exception):
    """存在表达引擎操作异常"""


# 身份保护字段 (可解释, 表达输出禁止触碰)
PRESENCE_PROTECTED_FIELDS: list = [
    "mission", "core_value", "base_personality",
    "safety_rules", "permission",
    "使命", "价值观", "人格", "安全规则", "权限",
    "身份", "核心价值",
]

# 表达输出字段白名单 (可解释)
PRESENCE_OUTPUT_FIELDS: list = [
    "expression", "posture", "intensity",
    "interaction_mode", "timestamp",
]


class PresenceEngine:
    """存在表达引擎 (内部状态 → 可解释的外部表达)

    用法:
        engine = PresenceEngine(emotion=emotion_engine)
        result = engine.update("success")
        state = engine.state()
    """

    def __init__(
        self,
        state: Optional[PresenceState] = None,
        mapper: Optional[PresenceMapper] = None,
        memory: Optional[PresenceMemory] = None,
        emotion=None,
        personality_fn: Optional[Callable[[], Dict[str, Any]]] = None,
        enabled: bool = True,
        intensity_step: float = 0.15,
    ):
        if not (0.0 < intensity_step <= 1.0):
            raise PresenceEngineError(
                f"intensity_step 必须在 (0,1], 当前: "
                f"{intensity_step}"
            )
        self._lock = threading.RLock()
        self._enabled = bool(enabled)
        self._step = float(intensity_step)
        self._state = state or PresenceState()
        self._mapper = mapper or PresenceMapper()
        self._memory = memory or PresenceMemory()
        self._emotion = emotion
        self._personality_fn = personality_fn
        self._update_count = 0
        self._guard_block_count = 0
        self._audit: list = []

    # ── 解释器 (只映射, 不应用) ─────────────────────────────────
    def interpreter(
        self,
        context: str = "idle",
        emotion_state: Optional[Dict[str, Any]] = None,
        personality: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """内部状态 → 表达建议 (只读, 不改变状态)"""
        with self._lock:
            emo = emotion_state
            if emo is None and self._emotion is not None:
                try:
                    emo = self._emotion.get_state()
                except Exception as e:
                    logger.warning(
                        f"[Presence] 读取情绪失败: {e}",
                    )
                    emo = {}
            pers = personality
            if pers is None and self._personality_fn is not None:
                try:
                    pers = self._personality_fn()
                except Exception as e:
                    logger.warning(
                        f"[Presence] 读取人格失败: {e}",
                    )
                    pers = {}
            return self._mapper.map(emo, pers, context)

    # ── 更新 (状态机) ────────────────────────────────────────────
    def update(
        self,
        context: str = "idle",
        emotion_state: Optional[Dict[str, Any]] = None,
        personality: Optional[Dict[str, Any]] = None,
        now: Optional[float] = None,
    ) -> Dict[str, Any]:
        """状态机更新 (映射 → 有限幅 → 身份守护 → 输出)

        Args:
            context: 上下文 (success/failure/idle/...)
            emotion_state: 情绪状态 (None → 引擎注入)
            personality: 人格维度 (None → 引擎注入)

        Returns:
            更新后状态 (含 reason)
        """
        with self._lock:
            now = now if now is not None else time.time()
            if not self._enabled:
                return self._finish_result(
                    "presence_enabled_false", now,
                )
            suggestion = self.interpreter(
                context, emotion_state, personality,
            )
            # 1. Identity Guard (表达不触身份)
            guard_ok, guard_reason = self._guard_check(
                suggestion,
            )
            if not guard_ok:
                self._guard_block_count += 1
                return self._finish_result(
                    f"身份守护拦截: {guard_reason}", now,
                )
            # 2. 状态机有限幅 (强度逐步逼近)
            current = self._state
            target_intensity = float(
                suggestion["intensity"],
            )
            current_intensity = float(
                current.get("intensity"),
            )
            delta = target_intensity - current_intensity
            if abs(delta) > self._step:
                applied_intensity = round(
                    current_intensity + self._step *
                    (1.0 if delta > 0 else -1.0), 4,
                )
            else:
                applied_intensity = target_intensity
            # 3. 应用 (只改表达字段)
            self._state.update(
                expression=suggestion["expression"],
                posture=suggestion["posture"],
                intensity=applied_intensity,
                interaction_mode=suggestion[
                    "interaction_mode"],
                reason=suggestion["reason"],
                now=now,
            )
            # 4. 记忆 (连续性支撑)
            self._memory.record(
                context=context,
                expression=suggestion["expression"],
                interaction_mode=suggestion[
                    "interaction_mode"],
                intensity=applied_intensity,
                now=now,
            )
            # 5. 审计
            self._audit.append({
                "audit_id": "pa_" + uuid.uuid4().hex[:8],
                "time": now,
                "context": context,
                "suggestion": dict(suggestion),
                "applied": dict(self._state.to_dict()),
                "guard_ok": True,
            })
            if len(self._audit) > 1000:
                self._audit = self._audit[-1000:]
            self._update_count += 1
            return self._finish_result(
                suggestion["reason"], now,
            )

    # ── 子步骤 (可解释) ─────────────────────────────────────────
    @staticmethod
    def _guard_check(suggestion: Dict[str, Any]) -> tuple:
        """身份守护: 表达输出只含白名单字段"""
        for key in suggestion:
            if key in PRESENCE_PROTECTED_FIELDS:
                return False, f"表达涉及身份字段 '{key}'"
        text = " ".join(
            str(suggestion.get(k, ""))
            for k in ("expression", "posture",
                      "interaction_mode", "reason")
        )
        for field in PRESENCE_PROTECTED_FIELDS:
            if field in text and (
                "修改" in text or "更改" in text or
                "更新" in text
            ):
                return False, f"表达含身份修改信号 " \
                              f"'{field}'"
        return True, "表达不触身份"

    def _finish_result(self, reason: str,
                       now: float) -> Dict[str, Any]:
        out = self._state.to_dict()
        out["reason"] = reason
        out["mode"] = "rule_based"
        return out

    # ── 查询 ─────────────────────────────────────────────────────
    def state(self) -> Dict[str, Any]:
        """当前表达状态"""
        with self._lock:
            return self._state.to_dict()

    def history(self, limit: int = 50) -> Dict[str, Any]:
        """表达历史"""
        with self._lock:
            return {
                "mode": "rule_based",
                "records": self._memory.history(limit=limit),
            }

    def continuity(self, window_days: int = 30) -> Dict[str, Any]:
        """存在连续性 (节奏/偏好)"""
        with self._lock:
            return self._memory.continuity(
                window_days=window_days,
            )

    def memory_stats(self) -> Dict[str, Any]:
        """记忆统计"""
        with self._lock:
            return self._memory.stats()

    def audit_report(self, limit: int = 100) -> Dict[str, Any]:
        """表达审计报告"""
        with self._lock:
            recent = list(reversed(self._audit))
            if limit > 0:
                recent = recent[:limit]
            return {
                "mode": "rule_based",
                "total": len(self._audit),
                "recent": recent,
            }

    def stats(self) -> Dict[str, Any]:
        """表达引擎统计"""
        with self._lock:
            return {
                "mode": "rule_based",
                "enabled": self._enabled,
                "update_count": self._update_count,
                "guard_block_count": self._guard_block_count,
                "state": self._state.to_dict(),
                "mapper": self._mapper.stats(),
                "memory": self._memory.stats(),
                "intensity_step": self._step,
            }

    def restore_state(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """恢复表达状态 (快照)"""
        with self._lock:
            return self._state.restore(state)

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = len(self._audit) + self._memory.clear()
            self._audit.clear()
            self._state.reset()
            self._update_count = 0
            self._guard_block_count = 0
            return n


__all__ = [
    "PRESENCE_OUTPUT_FIELDS",
    "PRESENCE_PROTECTED_FIELDS",
    "PresenceEngine",
    "PresenceEngineError",
]
