"""
YHLZ Embodied AI V5.9 - 集成桥接层 (Integration Bridges)

架构:
    ExperienceBridge   (经历桥接: 只 CONFIRMED 经验供给 + 新经验回写)
    ReflectionBridge   (反思桥接: Reflection Report → 创造输入)
    ApprovalBridge     (审批桥接: 创造方案必须审批, 禁止自动执行)

目标:
    创造层 ↔ Experience / Reflection / Verification 层安全集成
"""
from backend.embodied.companion.integration.approval_bridge import (
    ApprovalBridge,
    ApprovalBridgeError,
)
from backend.embodied.companion.integration.experience_bridge import (
    ExperienceBridge,
    ExperienceBridgeError,
)
from backend.embodied.companion.integration.reflection_bridge import (
    ReflectionBridge,
    ReflectionBridgeError,
)

__all__ = [
    "ApprovalBridge",
    "ApprovalBridgeError",
    "ExperienceBridge",
    "ExperienceBridgeError",
    "ReflectionBridge",
    "ReflectionBridgeError",
]
