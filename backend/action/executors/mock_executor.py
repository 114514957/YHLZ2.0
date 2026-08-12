"""
YHLZ Vision Action V1.0 - Mock 执行器

职责:
    - 模拟行动执行 (收到动作 → 校验 → 返回结果)
    - 用于: 测试 / 演示 / 权限流程验证
    - 禁止操作真实设备 (不移动鼠标 / 不按键 / 不输入)

设计原则:
    - 线程安全 (RLock)
    - 行动状态登记 (pending / running / ok / cancelled)
    - 结果可预期, 便于断言
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List, Tuple

from backend.action.interface import ActionExecutor, ActionExecutorError
from backend.action.schema import (
    ActionRequest,
    ActionResult,
    ActionStatus,
    ActionType,
)

logger = logging.getLogger(__name__)


class MockActionExecutor(ActionExecutor):
    """Mock 行动执行器 (测试 / 演示用, 绝对安全)"""

    def __init__(self):
        self._lock = threading.RLock()
        self._actions: Dict[str, Dict[str, Any]] = {}
        self._counter = 0

    @property
    def name(self) -> str:
        return "mock"

    @property
    def supported_types(self) -> List[str]:
        return ActionType.values()

    def is_available(self) -> bool:
        return True

    def create(self, request: ActionRequest) -> ActionResult:
        """登记行动 (PENDING)"""
        with self._lock:
            self._counter += 1
            self._actions[request.action_id] = {
                "request": request,
                "state": ActionStatus.PENDING.value,
                "created_at": time.time(),
            }
        return ActionResult(
            action_id=request.action_id,
            status=ActionStatus.PENDING.value,
            message=f"[Mock] 行动已登记: {request.action_type} → {request.target}",
            output={"executor": self.name},
        )

    def validate(self, request: ActionRequest) -> Tuple[bool, str]:
        """执行器级校验 (Mock 接受全部合法类型)"""
        if request.action_type not in ActionType.values():
            return False, f"不支持的 action_type: {request.action_type}"
        return True, ""

    def execute(self, request: ActionRequest) -> ActionResult:
        """模拟执行 (仅登记结果, 不产生真实事件)"""
        start = time.perf_counter()
        with self._lock:
            self._counter += 1
            self._actions[request.action_id] = {
                "request": request,
                "state": ActionStatus.OK.value,
                "created_at": time.time(),
            }
            latency = (time.perf_counter() - start) * 1000
        logger.info(
            f"[Action] Mock 执行 action_type={request.action_type} "
            f"target={request.target} latency={latency:.1f}ms"
        )
        return ActionResult(
            action_id=request.action_id,
            status=ActionStatus.OK.value,
            message=f"[Mock] 模拟执行成功: {request.action_type} → {request.target}",
            output={
                "executor": self.name,
                "simulated": True,
                "action_type": request.action_type,
                "target": request.target,
                "latency_ms": round(latency, 2),
            },
        )

    def cancel(self, action_id: str) -> ActionResult:
        """取消行动"""
        with self._lock:
            record = self._actions.get(action_id)
            if record is None:
                return ActionResult(
                    action_id=action_id,
                    status=ActionStatus.ERROR.value,
                    message=f"[Mock] 未找到行动: {action_id}",
                )
            record["state"] = ActionStatus.CANCELLED.value
        return ActionResult(
            action_id=action_id,
            status=ActionStatus.CANCELLED.value,
            message=f"[Mock] 行动已取消: {action_id}",
            output={"executor": self.name},
        )

    def status(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "name": self.name,
                "available": self.is_available(),
                "supported_types": self.supported_types,
                "pending": sum(1 for r in self._actions.values() if r["state"] == "pending"),
                "total_registered": len(self._actions),
                "total_executed": self._counter,
            }

    def close(self) -> None:
        with self._lock:
            self._actions.clear()


__all__ = ["MockActionExecutor"]
