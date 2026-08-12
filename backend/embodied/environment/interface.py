"""
YHLZ Embodied AI V4.1 - 环境抽象接口

职责:
    - 定义统一环境抽象 (Environment ABC)
    - 定义环境异常 (EnvironmentError)
    - 不包含任何实现 (实现位于本包 mock.py / adapter.py)

架构位置:
    Service → Manager → Registry → Adapter (Environment)

设计原则:
    - 接口最小化: observe / step / reset / get_state / feedback
    - 与实现解耦: Mock / 仿真 / 未来机器人环境均可实现
    - 纯抽象, 无业务逻辑
    - 不绑定具体硬件: 不包含任何设备专有接口
    - 环境不得绕过权限 (权限只在 Service 层判定)
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from backend.embodied.schema import EmbodiedAction, EnvironmentState, Feedback


class EnvironmentError(Exception):
    """环境操作异常"""


class Environment(ABC):
    """环境抽象接口

    用法:
        class MyEnv(Environment):
            def name(self): ...
            def step(self, action): ...

    实现要求:
        - 线程安全 (RLock)
        - 异常包装为 EnvironmentError (不泄漏底层异常)
        - 不得绕过权限判定 (Service 层负责权限)
        - 不得控制真实设备 (本阶段只建立抽象能力)
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """环境名 (如 'mock' / 'hardware')"""

    @property
    @abstractmethod
    def supported_actions(self) -> List[str]:
        """支持的动作类型列表 (EmbodiedActionType 值)"""

    @abstractmethod
    def observe(self) -> EnvironmentState:
        """观察环境, 返回最新状态快照"""

    @abstractmethod
    def step(self, action: EmbodiedAction) -> EnvironmentState:
        """执行动作, 返回动作后的新状态

        注意: 动作执行结果 (成功/失败/环境变化) 通过 feedback() 查询
        """

    @abstractmethod
    def reset(self) -> EnvironmentState:
        """重置环境为初始状态, 返回初始状态快照"""

    @abstractmethod
    def get_state(self) -> EnvironmentState:
        """获取当前状态 (与 observe 等价, 语义更明确)"""

    @abstractmethod
    def feedback(self, action_id: str) -> Optional[Feedback]:
        """查询动作反馈 (None=未找到)"""

    def is_available(self) -> bool:
        """环境是否可用 (默认 True, 子类可覆盖)"""
        return True

    def close(self) -> None:
        """关闭环境 (释放资源)"""


__all__ = ["Environment", "EnvironmentError"]
