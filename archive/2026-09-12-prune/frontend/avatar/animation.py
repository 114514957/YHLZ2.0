"""
YHLZ 前端状态驱动动画映射 (Animation Mapping)

职责:
    - 定义动画规格 (表情/动作组/动作编号/优先级)
    - Runtime 事件 → 动画映射表

设计原则:
    - 与 live2d_renderer 接口对齐 (set_emotion / start_motion)
    - 可解释: 每个映射含 reason
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class AnimationSpec:
    """动画规格"""
    emotion: str = "neutral"        # 表情 (renderer.set_emotion)
    motion_group: str = ""          # 动作组 (renderer.start_motion)
    motion_no: int = 0              # 动作编号
    priority: int = 3               # 动作优先级
    reason: str = ""                # 触发原因 (可解释)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "emotion": self.emotion,
            "motion_group": self.motion_group,
            "motion_no": self.motion_no,
            "priority": self.priority,
            "reason": self.reason,
        }


# 伙伴状态 → 动画 (可解释)
ANIMATION_MAP: Dict[str, AnimationSpec] = {
    "idle": AnimationSpec(
        emotion="neutral", motion_group="Idle",
        motion_no=0, priority=1,
        reason="待机: 安静存在",
    ),
    "initializing": AnimationSpec(
        emotion="neutral", motion_group="Init",
        motion_no=0, priority=2,
        reason="初始化: 专注准备",
    ),
    "online": AnimationSpec(
        emotion="happy", motion_group="TapBody",
        motion_no=0, priority=2,
        reason="在线: 愉快回应",
    ),
    "thinking": AnimationSpec(
        emotion="neutral", motion_group="Think",
        motion_no=0, priority=2,
        reason="思考: 专注思考",
    ),
    "learning": AnimationSpec(
        emotion="surprised", motion_group="TapHead",
        motion_no=0, priority=2,
        reason="学习: 好奇吸收",
    ),
    "waiting": AnimationSpec(
        emotion="neutral", motion_group="Idle",
        motion_no=1, priority=1,
        reason="等待: 耐心等待",
    ),
    "error": AnimationSpec(
        emotion="sad", motion_group="TapBody",
        motion_no=1, priority=3,
        reason="错误: 提醒用户",
    ),
}

# Runtime 事件 → 动画 (可解释)
EVENT_ANIMATION_MAP: Dict[str, AnimationSpec] = {
    "SYSTEM_READY": AnimationSpec(
        emotion="happy", motion_group="TapBody",
        motion_no=0, priority=3,
        reason="启动成功: 开心动画",
    ),
    "MEMORY_SYNC": AnimationSpec(
        emotion="surprised", motion_group="TapHead",
        motion_no=0, priority=2,
        reason="记忆同步: 好奇",
    ),
    "MODEL_SWITCH": AnimationSpec(
        emotion="neutral", motion_group="Think",
        motion_no=0, priority=2,
        reason="模型切换: 思考",
    ),
    "TASK_START": AnimationSpec(
        emotion="neutral", motion_group="Think",
        motion_no=0, priority=2,
        reason="任务开始: 专注",
    ),
    "TASK_END": AnimationSpec(
        emotion="happy", motion_group="TapBody",
        motion_no=0, priority=2,
        reason="任务完成: 开心",
    ),
    "ERROR": AnimationSpec(
        emotion="sad", motion_group="TapBody",
        motion_no=1, priority=3,
        reason="错误: 提醒动画",
    ),
}


def animation_for_state(state: str) -> Optional[AnimationSpec]:
    """伙伴状态 → 动画 (未知状态返回 None)"""
    return ANIMATION_MAP.get(state)


def animation_for_event(event_type: str) -> Optional[AnimationSpec]:
    """运行时事件 → 动画 (未知事件返回 None)"""
    return EVENT_ANIMATION_MAP.get(event_type)


__all__ = [
    "ANIMATION_MAP",
    "AnimationSpec",
    "EVENT_ANIMATION_MAP",
    "animation_for_event",
    "animation_for_state",
]
