"""
YHLZ Vision Action V1.0 - 行动执行器接口

职责:
    - 定义统一执行器抽象 (ActionExecutor ABC)
    - 定义执行器异常 (ActionExecutorError)
    - 不包含任何实现 (实现位于 executors/ 目录)

架构位置:
    Service → Manager → Executor (Adapter)

设计原则:
    - 接口最小化: create / validate / execute / cancel / status
    - 与实现解耦: Mock / 真实桌面 / 未来机器人接口均可实现
    - 纯抽象, 无业务逻辑
    - 执行器不得绕过权限 (权限只在 Service 层判定)
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Tuple

from backend.action.schema import ActionRequest, ActionResult


class ActionExecutorError(Exception):
    """行动执行器操作异常"""


class ActionExecutor(ABC):
    """行动执行器抽象接口

    用法:
        class MyExecutor(ActionExecutor):
            def name(self): ...
            def execute(self, request): ...

    实现要求:
        - 线程安全 (RLock)
        - 异常包装为 ActionExecutorError (不泄漏底层异常)
        - 不得绕过权限判定 (Service 层负责权限)
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """执行器名 (如 'mock' / 'real')"""

    @property
    @abstractmethod
    def supported_types(self) -> List[str]:
        """支持的行动类型列表 (ActionType 值)"""

    @abstractmethod
    def create(self, request: ActionRequest) -> ActionResult:
        """创建行动 (登记待执行), 返回 PENDING 结果"""

    @abstractmethod
    def validate(self, request: ActionRequest) -> Tuple[bool, str]:
        """执行器级校验 (True, '') = 通过"""

    @abstractmethod
    def execute(self, request: ActionRequest) -> ActionResult:
        """执行行动, 返回 ActionResult"""

    @abstractmethod
    def cancel(self, action_id: str) -> ActionResult:
        """取消行动, 返回 ActionResult"""

    @abstractmethod
    def status(self) -> Dict[str, Any]:
        """执行器状态 (可用性 / 支持类型 / 统计)"""

    def is_available(self) -> bool:
        """执行器是否可用 (默认 True, 子类可覆盖)"""
        return True

    def close(self) -> None:
        """关闭执行器 (释放资源)"""


__all__ = ["ActionExecutor", "ActionExecutorError"]
