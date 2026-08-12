"""
YHLZ 前端 Avatar 层 (形象/动画/情绪)

职责:
    - emotion: Emotion State Manager (Runtime Event → Emotion → Animation)
    - animation: 状态驱动动画映射表
"""
from __future__ import annotations

from frontend.avatar.animation import (
    AnimationSpec,
    ANIMATION_MAP,
    EVENT_ANIMATION_MAP,
    animation_for_event,
    animation_for_state,
)
from frontend.avatar.emotion import (
    EMOTIONS,
    EmotionState,
    EmotionStateManager,
    EmotionStateError,
)

__all__ = [
    "ANIMATION_MAP",
    "AnimationSpec",
    "EMOTIONS",
    "EVENT_ANIMATION_MAP",
    "EmotionState",
    "EmotionStateError",
    "EmotionStateManager",
    "animation_for_event",
    "animation_for_state",
]
