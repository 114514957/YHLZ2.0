"""
YHLZ Embodied AI V4.1 - 硬件环境适配器 (占位)

职责:
    - 预留真实硬件环境接口 (未来机器人 / 机械臂版本实现)
    - 本版本 (V4.1) 明确禁止控制实体设备:
      硬件适配器默认不可用, step 一律抛 EnvironmentError

设计原则:
    - 默认关闭 (is_available=False, 需环境变量显式开启)
    - 即使开启, 本版本也拒绝执行 (仅验证框架, 不控制真实设备)
    - 优雅降级: 不阻塞启动, 不影响主流程
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

from backend.embodied.environment.interface import Environment, EnvironmentError
from backend.embodied.schema import EmbodiedAction, EnvironmentState, Feedback

logger = logging.getLogger(__name__)


class HardwareEnvironment(Environment):
    """硬件环境适配器 (V4.1 占位, 不控制任何真实设备)"""

    def __init__(self):
        # 本版本默认禁用硬件执行
        self._enabled = os.getenv("YHLZ_EMBODIED_ENABLE_HARDWARE", "false").lower() == "true"

    @property
    def name(self) -> str:
        return "hardware"

    @property
    def supported_actions(self) -> List[str]:
        # 占位: 未实现任何真实动作
        return []

    def is_available(self) -> bool:
        # 本版本: 即使 env 开启也返回 False (未实现硬件控制, 防止误操作)
        return False

    def observe(self) -> EnvironmentState:
        return EnvironmentState.create(metadata={
            "environment": self.name,
            "available": False,
            "note": "硬件环境未启用: 本版本仅建立具身智能基础设施",
        })

    def get_state(self) -> EnvironmentState:
        return self.observe()

    def step(self, action: EmbodiedAction) -> EnvironmentState:
        logger.warning(
            f"[Embodied] 拒绝硬件执行: action_type={action.action_type} "
            f"target={action.target} (本版本禁止控制真实设备)"
        )
        raise EnvironmentError("HARDWARE_NOT_AVAILABLE_V4.1: 硬件环境未启用")

    def reset(self) -> EnvironmentState:
        raise EnvironmentError("HARDWARE_NOT_AVAILABLE_V4.1: 硬件环境未启用")

    def feedback(self, action_id: str) -> Optional[Feedback]:
        return None

    def status(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "available": self.is_available(),
            "enabled_env": self._enabled,
            "supported_actions": self.supported_actions,
            "note": "V4.1 占位适配器: 不控制任何真实设备",
        }


__all__ = ["HardwareEnvironment"]
