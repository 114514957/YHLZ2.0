"""
YHLZ Vision Action V1.0 - 行动 Manager

职责:
    - 管理 ActionExecutor 生命周期 (注册/注销/路由/启停)
    - 路由行动请求到对应 Executor
    - 不直接对外暴露 (Service 调用)

架构位置:
    Service → Manager → Executor (Adapter)

设计原则:
    - 注册表模式: 多 Executor 共存 (mock / real / 未来更多)
    - 默认注册: 测试模式 / 生产均注册 Mock; Real 作为占位
    - 路由: 默认首个注册执行器, 或 request.parameters['executor'] 指定
    - 线程安全 (RLock)
    - 可重置 (测试隔离)
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List, Optional

from backend.action.interface import ActionExecutor
from backend.action.schema import ActionRequest

logger = logging.getLogger(__name__)


class ActionManagerError(Exception):
    """Action Manager 操作异常"""


class ActionManager:
    """行动管理器

    用法:
        mgr = ActionManager()
        mgr.register_defaults()
        result = mgr.execute(request)   # 路由到执行器
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._executors: Dict[str, ActionExecutor] = {}
        self._default_registered = False
        self._running = False

    # ── 注册管理 ──────────────────────────────────────────────────
    def register_executor(
        self,
        name: str,
        executor: ActionExecutor,
        override: bool = False,
    ) -> None:
        """注册执行器

        Args:
            name: 执行器名 (如 'mock' / 'real')
            executor: ActionExecutor 实例
            override: 是否覆盖同名执行器
        """
        with self._lock:
            if name in self._executors and not override:
                raise ActionManagerError(
                    f"ActionExecutor {name} 已注册, override=False"
                )
            self._executors[name] = executor
            logger.info(
                f"已注册 ActionExecutor: name={name} class={executor.__class__.__name__}"
            )

    def unregister_executor(self, name: str) -> bool:
        with self._lock:
            executor = self._executors.pop(name, None)
            if executor is not None:
                logger.info(f"已注销 ActionExecutor: name={name}")
                return True
            return False

    # ── 查询 ──────────────────────────────────────────────────────
    def get_executor(self, name: str) -> Optional[ActionExecutor]:
        with self._lock:
            return self._executors.get(name)

    def get_default_executor(self) -> Optional[ActionExecutor]:
        """获取默认执行器 (第一个注册的)"""
        with self._lock:
            if not self._executors:
                return None
            return next(iter(self._executors.values()))

    def list_executors(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [
                {
                    "name": name,
                    "class": ex.__class__.__name__,
                    "available": ex.is_available(),
                    "supported_types": ex.supported_types,
                }
                for name, ex in self._executors.items()
            ]

    def list_names(self) -> List[str]:
        with self._lock:
            return list(self._executors.keys())

    def has_executor(self, name: str) -> bool:
        with self._lock:
            return name in self._executors

    # ── 路由 ──────────────────────────────────────────────────────
    def route(self, request: ActionRequest) -> Optional[ActionExecutor]:
        """路由行动请求到执行器

        优先 request.parameters['executor'] 指定; 否则默认 (首个注册)
        """
        requested = None
        try:
            requested = request.parameters.get("executor")
        except AttributeError:
            pass
        if requested:
            ex = self.get_executor(str(requested))
            if ex is not None:
                return ex
            logger.warning(f"[Action] 指定执行器 {requested} 不存在, 回退默认")
        return self.get_default_executor()

    # ── 生命周期 ──────────────────────────────────────────────────
    def start(self) -> None:
        """启动 Manager (标记运行中)"""
        with self._lock:
            self._running = True
        logger.info("[Action] ActionManager 已启动")

    def stop(self) -> None:
        """停止 Manager (关闭所有执行器)"""
        with self._lock:
            executors = list(self._executors.values())
            self._executors.clear()
            self._default_registered = False
            self._running = False
        for ex in executors:
            try:
                ex.close()
            except Exception as e:
                logger.warning(f"[Action] 关闭执行器异常: {e}")
        logger.info("[Action] ActionManager 已停止")

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._running

    # ── 默认注册 ──────────────────────────────────────────────────
    def register_defaults(self) -> None:
        """注册默认执行器

        行为:
            - Mock 执行器必注册 (测试/演示/权限流程)
            - Real 执行器注册为占位 (is_available=False, 本版本不执行真实动作)
        """
        with self._lock:
            if self._default_registered:
                return
            from backend.action.executors.mock_executor import MockActionExecutor
            from backend.action.executors.real_executor import RealActionExecutor

            self._executors.setdefault("mock", MockActionExecutor())
            self._executors.setdefault("real", RealActionExecutor())
            self._default_registered = True
            logger.info("[Action] 默认执行器已注册: mock (真实可用) / real (占位不可用)")

    # ── 状态 ──────────────────────────────────────────────────────
    def status(self) -> Dict[str, Any]:
        with self._lock:
            default = self.get_default_executor()
            return {
                "executors_count": len(self._executors),
                "executors": self.list_executors(),
                "default_executor": default.name if default else None,
                "default_registered": self._default_registered,
                "running": self._running,
            }

    def reset(self) -> None:
        """清空所有注册 (不关闭执行器, 供测试复用)"""
        with self._lock:
            self._executors.clear()
            self._default_registered = False
            self._running = False


# ── 全局单例 ─────────────────────────────────────────────────────
_global_manager: Optional[ActionManager] = None
_manager_lock = threading.Lock()


def get_manager() -> ActionManager:
    """获取全局 ActionManager 单例"""
    global _global_manager
    with _manager_lock:
        if _global_manager is None:
            _global_manager = ActionManager()
            _global_manager.register_defaults()
        return _global_manager


def reset_manager() -> None:
    """重置全局 Manager (测试用)"""
    global _global_manager
    with _manager_lock:
        if _global_manager is not None:
            _global_manager.reset()
        _global_manager = None


__all__ = [
    "ActionManager",
    "ActionManagerError",
    "get_manager",
    "reset_manager",
]
