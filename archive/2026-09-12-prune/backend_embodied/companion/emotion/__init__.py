"""
YHLZ Embodied AI V6.1.1 - 情绪表征层 (Emotion Representation Layer)

架构:
    EmotionEngine  (情绪引擎: update/decay/get_state/get_stats)
        ├── EmotionState   (情绪状态: positivity/energy/warmth)
        ├── EmotionRules   (规则表: 情境 → 维度变化, 禁止 LLM 推断)
        ├── EmotionDecay   (自然衰减: 回归基线)
        ├── EmotionMemory  (情绪历史: 供 Reflection/Growth)
        └── EmotionAudit   (情绪审计: 禁止静默修改)

安全协议:
    - 情绪不是意识 (可计算状态变量)
    - 情绪不是人格 (不触碰 Identity Layer)
    - 情绪不能改变: Personality Base / Core Value / Mission
"""
from backend.embodied.companion.emotion.emotion_audit import (
    AuditError,
    EMOTION_AUDIT_ACTIONS,
    EmotionAudit,
)
from backend.embodied.companion.emotion.emotion_decay import (
    DecayError,
    EmotionDecay,
)
from backend.embodied.companion.emotion.emotion_engine import (
    EmotionEngine,
    EmotionEngineError,
)
from backend.embodied.companion.emotion.emotion_memory import (
    EmotionMemory,
    MemoryError,
)
from backend.embodied.companion.emotion.emotion_rules import (
    EMOTION_CONTEXTS,
    EMOTION_RULES,
    RulesError,
    rule_for,
)
from backend.embodied.companion.emotion.emotion_state import (
    EMOTION_BASELINE,
    EMOTION_DIMENSIONS,
    EmotionError,
    EmotionState,
)

__all__ = [
    "AuditError",
    "DecayError",
    "EMOTION_AUDIT_ACTIONS",
    "EMOTION_BASELINE",
    "EMOTION_CONTEXTS",
    "EMOTION_DIMENSIONS",
    "EMOTION_RULES",
    "EmotionAudit",
    "EmotionDecay",
    "EmotionEngine",
    "EmotionEngineError",
    "EmotionError",
    "EmotionMemory",
    "EmotionState",
    "MemoryError",
    "RulesError",
    "rule_for",
]
