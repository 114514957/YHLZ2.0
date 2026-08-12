"""
YHLZ Embodied AI V7.0 - 存在表达映射器 (Presence Mapper)

职责:
    - 内部状态 → 外部表达 (情绪/人格/上下文 → 表情/姿态/强度/模式)
    - 只读输入 (禁止修改情绪/人格)

原则 (内部状态 ≠ 主观体验):
    - 表达是内部状态经过解释后的外部接口
    - 禁止声称拥有未经验证的主观体验
    - 禁止通过表达模拟修改人格/价值

映射规则 (可解释):
    情绪维度:
        positivity ≥ 0.7 → 高兴
        positivity ≤ 0.3 → 关切
        energy ≥ 0.6 → 思考/专注
        warmth ≥ 0.7 → 关切 (supportive)
    人格维度:
        humor ≥ 0.6 → playful 倾向
        patience 高 → 聆听倾向
    上下文:
        success → 高兴/回应/playful
        failure → 关切/聆听/supportive
        creative_done → 高兴/回应/playful
        深度任务 → 思考/专注/focused

设计原则:
    - 纯规则映射 (无黑盒, 可解释)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import uuid
from typing import Any, Dict, Optional

from backend.embodied.companion.embodied_presence.presence_state import (
    EXPRESSIONS,
    INTERACTION_MODES,
    POSTURES,
)

logger = logging.getLogger(__name__)


class PresenceMapperError(Exception):
    """存在表达映射操作异常"""


# 上下文 → 表达 (可解释)
CONTEXT_EXPRESSIONS: Dict[str, Dict[str, Any]] = {
    "success": {
        "expression": "高兴", "posture": "回应",
        "intensity": 0.7, "interaction_mode": "playful",
        "reason": "任务成功: 积极回应",
    },
    "failure": {
        "expression": "关切", "posture": "聆听",
        "intensity": 0.6, "interaction_mode": "supportive",
        "reason": "任务失败: 支持陪伴",
    },
    "creative_done": {
        "expression": "高兴", "posture": "回应",
        "intensity": 0.7, "interaction_mode": "playful",
        "reason": "创造完成: 积极表达",
    },
    "creative_rejected": {
        "expression": "关切", "posture": "聆听",
        "intensity": 0.5, "interaction_mode": "supportive",
        "reason": "创造被拒: 有限关切",
    },
    "relationship_up": {
        "expression": "高兴", "posture": "回应",
        "intensity": 0.65, "interaction_mode": "playful",
        "reason": "关系提升: 温暖表达",
    },
    "deep_task": {
        "expression": "思考", "posture": "专注",
        "intensity": 0.6, "interaction_mode": "focused",
        "reason": "深度任务: 专注处理",
    },
    "idle": {
        "expression": "平静", "posture": "待机",
        "intensity": 0.3, "interaction_mode": "neutral",
        "reason": "空闲: 默认状态",
    },
}


class PresenceMapper:
    """存在表达映射器 (内部状态 → 表达建议)

    用法:
        mapper = PresenceMapper()
        suggestion = mapper.map(emotion_state, personality)
    """

    def __init__(self, enabled: bool = True):
        self._lock = threading.RLock()
        self._enabled = bool(enabled)
        self._map_count = 0

    # ── 映射主入口 ───────────────────────────────────────────────
    def map(
        self,
        emotion_state: Optional[Dict[str, Any]] = None,
        personality: Optional[Dict[str, Any]] = None,
        context: str = "idle",
    ) -> Dict[str, Any]:
        """内部状态 → 表达建议

        Args:
            emotion_state: 情绪状态 (positivity/energy/warmth)
            personality: 人格维度 (warmth/patience/humor/...)
            context: 上下文 (success/failure/idle/...)

        Returns:
            {
                'expression', 'posture', 'intensity',
                'interaction_mode', 'reason', 'confidence',
                'mode',
            }
        """
        with self._lock:
            if not self._enabled:
                return {
                    "expression": "平静",
                    "posture": "待机",
                    "intensity": 0.3,
                    "interaction_mode": "neutral",
                    "reason": "映射器停用",
                    "confidence": 0.5,
                    "mode": "rule_based",
                }
            emotion = emotion_state or {}
            pers = personality or {}
            # 1. 上下文优先 (可解释)
            base = CONTEXT_EXPRESSIONS.get(
                context, CONTEXT_EXPRESSIONS["idle"],
            )
            expression = base["expression"]
            posture = base["posture"]
            intensity = float(base["intensity"])
            mode = base["interaction_mode"]
            reasons = [base["reason"]]
            # 2. 情绪维度调整
            try:
                positivity = float(emotion.get("positivity", 0.5))
            except (TypeError, ValueError):
                positivity = 0.5
            try:
                energy = float(emotion.get("energy", 0.5))
            except (TypeError, ValueError):
                energy = 0.5
            try:
                warmth = float(emotion.get("warmth", 0.5))
            except (TypeError, ValueError):
                warmth = 0.5
            if context == "idle":
                if positivity >= 0.7:
                    expression = "高兴"
                    intensity = max(intensity, 0.5)
                    reasons.append(
                        f"情绪积极 (positivity {positivity})",
                    )
                elif positivity <= 0.3:
                    expression = "关切"
                    mode = "supportive"
                    reasons.append(
                        f"情绪偏低 (positivity {positivity})",
                    )
                if energy >= 0.6:
                    posture = "专注"
                    reasons.append(
                        f"能量充足 (energy {energy})",
                    )
            if warmth >= 0.7:
                if mode != "focused":
                    mode = "supportive"
                    reasons.append(
                        f"温暖度高 (warmth {warmth})",
                    )
            # 3. 人格维度调整
            try:
                humor = float(pers.get("humor", 0.3))
            except (TypeError, ValueError):
                humor = 0.3
            if humor >= 0.6 and expression == "平静":
                expression = "高兴"
                mode = "playful"
                intensity = min(1.0, intensity + 0.1)
                reasons.append(
                    f"幽默人格 (humor {humor})",
                )
            # 4. 强度钳制
            intensity = round(min(1.0, max(0.0, intensity)),
                              4)
            confidence = round(
                min(1.0, 0.5 + positivity * 0.3 +
                    energy * 0.2), 4,
            )
            self._map_count += 1
            return {
                "mode": "rule_based",
                "expression": expression,
                "posture": posture,
                "intensity": intensity,
                "interaction_mode": mode,
                "reason": "; ".join(reasons),
                "confidence": confidence,
            }

    # ── 查询 ─────────────────────────────────────────────────────
    def stats(self) -> Dict[str, Any]:
        """映射统计"""
        with self._lock:
            return {
                "mode": "rule_based",
                "enabled": self._enabled,
                "map_count": self._map_count,
                "contexts": list(CONTEXT_EXPRESSIONS.keys()),
            }

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            self._map_count = 0
            return 0


__all__ = [
    "CONTEXT_EXPRESSIONS",
    "PresenceMapper",
    "PresenceMapperError",
]
