"""
YHLZ Embodied AI V4.1 - 环境注册中心

职责:
    - 管理 Environment 实例 (注册 / 注销 / 查询 / 路由)
    - 多环境共存 (mock / 仿真 / 未来硬件)
    - 不直接对外暴露 (Manager 持有)

架构位置:
    Service → Manager → Registry → Adapter (Environment)

设计原则:
    - 注册表模式: 多 Environment 共存, 可替换
    - 路由: 默认首个注册环境, 或 action.parameters['environment'] 指定
    - 线程安全 (RLock)
    - 可重置 (测试隔离)
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List, Optional

from backend.embodied.environment.interface import Environment
from backend.embodied.schema import EmbodiedAction

logger = logging.getLogger(__name__)


class EnvironmentRegistryError(Exception):
    """环境注册中心操作异常"""


class EnvironmentRegistry:
    """环境注册中心

    用法:
        reg = EnvironmentRegistry()
        reg.register("mock", MockEnvironment())
        env = reg.get_default()
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._environments: Dict[str, Environment] = {}
        self._default_name: Optional[str] = None  # V4.3: 当前默认环境 (可动态切换)

    # ── 注册管理 ──────────────────────────────────────────────────
    def register(
        self,
        name: str,
        env: Environment,
        override: bool = False,
    ) -> None:
        """注册环境

        Args:
            name: 环境名 (如 'mock' / 'hardware')
            env: Environment 实例
            override: 是否覆盖同名环境
        """
        with self._lock:
            if name in self._environments and not override:
                raise EnvironmentRegistryError(
                    f"Environment {name} 已注册, override=False"
                )
            self._environments[name] = env
            logger.info(
                f"已注册 Environment: name={name} class={env.__class__.__name__}"
            )

    def unregister(self, name: str) -> bool:
        """注销环境, 返回是否成功"""
        with self._lock:
            env = self._environments.pop(name, None)
            if env is not None:
                if self._default_name == name:
                    self._default_name = None
                logger.info(f"已注销 Environment: name={name}")
                return True
            return False

    # ── 默认环境切换 (V4.3 场景生命周期) ─────────────────────────
    def set_default(self, name: str) -> bool:
        """设置默认环境 (场景切换后路由目标)

        Args:
            name: 已注册的环境名

        Returns:
            是否设置成功 (环境不存在返回 False)
        """
        with self._lock:
            if name not in self._environments:
                logger.warning(f"[Embodied] 设置默认环境失败: {name} 未注册")
                return False
            self._default_name = name
            logger.info(f"[Embodied] 默认环境已切换: {name}")
            return True

    def get_default_name(self) -> Optional[str]:
        """当前默认环境名 (None=未显式设置)"""
        with self._lock:
            return self._default_name

    # ── 查询 ──────────────────────────────────────────────────────
    def get(self, name: str) -> Optional[Environment]:
        """按名获取环境"""
        with self._lock:
            return self._environments.get(name)

    def get_default(self) -> Optional[Environment]:
        """获取默认环境 (显式设置优先, 否则第一个注册的)"""
        with self._lock:
            if not self._environments:
                return None
            if self._default_name and self._default_name in self._environments:
                return self._environments[self._default_name]
            return next(iter(self._environments.values()))

    def list(self) -> List[Dict[str, Any]]:
        """列出所有环境信息"""
        with self._lock:
            return [
                {
                    "name": name,
                    "class": env.__class__.__name__,
                    "available": env.is_available(),
                    "supported_actions": env.supported_actions,
                }
                for name, env in self._environments.items()
            ]

    def list_names(self) -> List[str]:
        with self._lock:
            return list(self._environments.keys())

    def has(self, name: str) -> bool:
        with self._lock:
            return name in self._environments

    # ── 路由 ──────────────────────────────────────────────────────
    def route(self, action: EmbodiedAction) -> Optional[Environment]:
        """路由动作到环境

        优先 action.parameters['environment'] 指定; 否则默认 (首个注册)
        """
        requested = None
        try:
            requested = action.parameters.get("environment")
        except AttributeError:
            pass
        if requested:
            env = self.get(str(requested))
            if env is not None:
                return env
            logger.warning(f"[Embodied] 指定环境 {requested} 不存在, 回退默认")
        return self.get_default()

    # ── 状态 ──────────────────────────────────────────────────────
    def count(self) -> int:
        with self._lock:
            return len(self._environments)

    def reset(self) -> None:
        """清空所有注册 (不关闭环境, 供测试复用)"""
        with self._lock:
            self._environments.clear()
            self._default_name = None


__all__ = ["EnvironmentRegistry", "EnvironmentRegistryError"]
