"""
YHLZ Embodied AI V7.0 - 具身表达层 (Embodied Presence Layer)

架构:
    PresenceState     (表达状态: 表情/姿态/强度/互动模式)
    PresenceMapper    (映射器: 情绪/人格/上下文 → 表达建议)
    PresenceMemory    (连续性记忆: 互动模式/表达偏好/沟通节奏)
    PresenceEngine    (状态机: 映射 → 有限幅 → 身份守护 → 输出)

流程:
    Identity → Personality → Emotion → Context
    → Presence Mapper → State Machine → Expression Output

原则:
    表达存在, 而不是制造虚假的主体性
    形象 ≠ 身份 (形象可变化, 身份必须稳定)
"""
from backend.embodied.companion.embodied_presence.presence_state import (
    DEFAULT_PRESENCE,
    EXPRESSIONS,
    INTERACTION_MODES,
    POSTURES,
    PresenceState,
    PresenceStateError,
)
from backend.embodied.companion.embodied_presence.presence_mapper import (
    CONTEXT_EXPRESSIONS,
    PresenceMapper,
    PresenceMapperError,
)
from backend.embodied.companion.embodied_presence.presence_memory import (
    PresenceMemory,
    PresenceMemoryError,
)
from backend.embodied.companion.embodied_presence.presence_engine import (
    PRESENCE_OUTPUT_FIELDS,
    PRESENCE_PROTECTED_FIELDS,
    PresenceEngine,
    PresenceEngineError,
)

__all__ = [
    "CONTEXT_EXPRESSIONS",
    "DEFAULT_PRESENCE",
    "EXPRESSIONS",
    "INTERACTION_MODES",
    "POSTURES",
    "PRESENCE_OUTPUT_FIELDS",
    "PRESENCE_PROTECTED_FIELDS",
    "PresenceEngine",
    "PresenceEngineError",
    "PresenceMapper",
    "PresenceMapperError",
    "PresenceMemory",
    "PresenceMemoryError",
    "PresenceState",
    "PresenceStateError",
]
