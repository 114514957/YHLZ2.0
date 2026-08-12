"""
YHLZ Vision Action V1.0 - 真实执行器 (占位)

职责:
    - 预留真实桌面自动化接口 (未来版本实现)
    - 本版本 (V1.0) 明确禁止自动控制电脑:
      真实执行器默认不可用, execute 一律返回 unsupported

设计原则:
    - 默认关闭 (is_available=False, 需环境变量显式开启)
    - 即使开启, 本版本也返回 unsupported (仅验证框架, 不产生真实动作)
    - 优雅降级: 不阻塞启动, 不影响主流程
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Tuple

from backend.action.interface import ActionExecutor
from backend.action.schema import (
    ActionRequest,
    ActionResult,
    ActionStatus,
    ActionType,
)

logger = logging.getLogger(__name__)


class RealActionExecutor(ActionExecutor):
    """真实行动执行器 (V1.0 占位, 不执行任何真实动作)"""

    def __init__(self):
        # 本版本默认禁用真实执行
        self._enabled = os.getenv("YHLZ_ACTION_ENABLE_REAL", "false").lower() == "true"

    @property
    def name(self) -> str:
        return "real"

    @property
    def supported_types(self) -> List[str]:
        return ActionType.values()

    def is_available(self) -> bool:
        # 本版本: 即使 env 开启也返回 False (未实现真实动作, 防止误操作)
        return False

    def create(self, request: ActionRequest) -> ActionResult:
        return ActionResult(
            action_id=request.action_id,
            status=ActionStatus.UNSUPPORTED.value,
            message="真实执行器未启用: 本版本仅建立行动基础设施, 不自动控制电脑",
            output={"executor": self.name},
        )

    def validate(self, request: ActionRequest) -> Tuple[bool, str]:
        return False, "真实执行器不可用 (本版本禁止自动控制电脑)"

    def execute(self, request: ActionRequest) -> ActionResult:
        logger.warning(
            f"[Action] 拒绝真实执行: action_type={request.action_type} target={request.target} "
            f"(本版本禁止自动控制电脑)"
        )
        return ActionResult(
            action_id=request.action_id,
            status=ActionStatus.UNSUPPORTED.value,
            message="真实执行不可用: 本版本仅建立行动基础设施 (V1.0 禁止自动控制电脑)",
            error="REAL_EXECUTOR_NOT_AVAILABLE_V1.0",
            output={"executor": self.name, "available": False},
        )

    def cancel(self, action_id: str) -> ActionResult:
        return ActionResult(
            action_id=action_id,
            status=ActionStatus.UNSUPPORTED.value,
            message="真实执行器无进行中的行动可取消",
            output={"executor": self.name},
        )

    def status(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "available": self.is_available(),
            "enabled_env": self._enabled,
            "supported_types": self.supported_types,
            "note": "V1.0 占位执行器: 不执行任何真实动作",
        }


__all__ = ["RealActionExecutor"]
