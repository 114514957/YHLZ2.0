"""
YHLZ Embodied AI V4.1 - 环境适配器包

架构:
    Environment (抽象接口)
        ↓
    EnvironmentRegistry (注册中心)
        ↓
    MockEnvironment (模拟, 可用) / HardwareEnvironment (占位, 不可用)
"""

from backend.embodied.environment.adapter import HardwareEnvironment
from backend.embodied.environment.interface import Environment, EnvironmentError
from backend.embodied.environment.mock import MockEnvironment, SCENES
from backend.embodied.environment.registry import (
    EnvironmentRegistry,
    EnvironmentRegistryError,
)

__all__ = [
    "Environment",
    "EnvironmentError",
    "EnvironmentRegistry",
    "EnvironmentRegistryError",
    "HardwareEnvironment",
    "MockEnvironment",
    "SCENES",
]
