"""
YHLZ Vision Understanding V1.0 - Understanding Manager

职责:
    - 管理 VLM Adapter 生命周期 (注册/注销/查询)
    - 路由理解请求到对应 Adapter
    - 不直接对外暴露 (Service 调用)
    - 提供统一理解接口

架构位置:
    Service → Manager → Adapter → Provider

设计原则:
    - 注册表模式: 多 Adapter 共存
    - 默认注册 VLM / Mock Adapter
    - 线程安全 (Lock)
    - 可重置 (测试隔离)
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List, Optional

from backend.vision.understanding.adapters.vlm_adapter import VLMAdapter
from backend.vision.understanding.interface import (
    UnderstandingOptions,
    VLMAdapter as VLMAdapterABC,
)
from backend.vision.understanding.schema import (
    UnderstandingResult,
    UnderstandingStatus,
)

logger = logging.getLogger(__name__)


class UnderstandingManagerError(Exception):
    """Understanding Manager 操作异常"""


class UnderstandingManager:
    """理解管理器

    用法:
        mgr = UnderstandingManager()
        mgr.register_defaults()
        result = mgr.understand(image, options)

    职责:
        - VLM Adapter 注册表
        - 路由理解请求到对应 Adapter
        - 不做权限校验 (Service 层负责)
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._adapters: Dict[str, VLMAdapterABC] = {}
        self._default_registered = False

    # ── 注册管理 ──────────────────────────────────────────────────
    def register_adapter(
        self,
        name: str,
        adapter: VLMAdapterABC,
        override: bool = False,
    ) -> None:
        """注册 VLM Adapter

        Args:
            name: Adapter 名 (如 'vlm' / 'mock' / 'openai_vlm')
            adapter: VLMAdapter 实例
            override: 是否覆盖已注册的同名 Adapter
        """
        with self._lock:
            if name in self._adapters and not override:
                raise UnderstandingManagerError(
                    f"VLM Adapter {name} 已注册, override=False"
                )
            self._adapters[name] = adapter
            logger.info(
                f"已注册 VLM Adapter: name={name} class={adapter.__class__.__name__}"
            )

    def unregister_adapter(self, name: str) -> bool:
        with self._lock:
            if name in self._adapters:
                self._adapters.pop(name)
                logger.info(f"已注销 VLM Adapter: name={name}")
                return True
            return False

    # ── 查询 ──────────────────────────────────────────────────────
    def get_adapter(self, name: str) -> Optional[VLMAdapterABC]:
        with self._lock:
            return self._adapters.get(name)

    def get_default_adapter(self) -> Optional[VLMAdapterABC]:
        """获取默认 Adapter (第一个注册的)"""
        with self._lock:
            if not self._adapters:
                return None
            return next(iter(self._adapters.values()))

    def list_adapters(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [a.get_info() for a in self._adapters.values()]

    def list_names(self) -> List[str]:
        with self._lock:
            return list(self._adapters.keys())

    def has_adapter(self, name: str) -> bool:
        with self._lock:
            return name in self._adapters

    # ── 执行 ──────────────────────────────────────────────────────
    def understand(
        self,
        image: Any,
        prompt: Optional[str] = None,
        options: Optional[UnderstandingOptions] = None,
        adapter_name: Optional[str] = None,
    ) -> UnderstandingResult:
        """执行视觉理解

        Args:
            image: numpy ndarray
            prompt: 自定义提示词 (None=内置模板)
            options: 理解选项
            adapter_name: 指定 Adapter (None=默认第一个)
        """
        with self._lock:
            adapter = (
                self._adapters.get(adapter_name)
                if adapter_name
                else self.get_default_adapter()
            )

        if adapter is None:
            return UnderstandingResult.create_error(
                source="vlm",
                status=UnderstandingStatus.NO_PROVIDER.value,
                error=f"无可用 VLM Adapter (requested={adapter_name or 'default'})",
                metadata={"provider": "none"},
            )

        try:
            return adapter.understand(image, prompt, options)
        except Exception as e:
            logger.error(
                f"[Manager] VLM Adapter {adapter.name} 异常: {e}", exc_info=True
            )
            return UnderstandingResult.create_error(
                source="vlm",
                status=UnderstandingStatus.ERROR.value,
                error=f"Manager 捕获异常: {type(e).__name__}: {e}",
                metadata={"provider": getattr(adapter, "name", "unknown")},
            )

    # ── 默认注册 ──────────────────────────────────────────────────
    def register_defaults(
        self,
        include_mock: bool = True,
        prefer_providers: Optional[List[str]] = None,
    ) -> None:
        """注册默认 Adapter

        Args:
            include_mock: 是否包含 Mock Adapter (测试环境必需)
            prefer_providers: 偏好 Provider 顺序 (['openai_vlm'])
                              第一个可用的会被注册为默认
        """
        with self._lock:
            if self._default_registered:
                return

            # 测试模式强制 Mock (YHLZ_UNDERSTANDING_TEST_MODE=true)
            import os as _os
            if _os.getenv("YHLZ_UNDERSTANDING_TEST_MODE", "false").lower() == "true":
                if include_mock:
                    self._adapters["mock"] = VLMAdapter()
                    logger.info("测试模式: 默认注册 Mock VLMAdapter")
                self._default_registered = True
                return

            # 优先尝试真实 VLM Provider, 失败回退 Mock
            vlm_provider = self._select_provider(prefer_providers)
            if vlm_provider is not None:
                adapter = VLMAdapter(provider=vlm_provider)
                self._adapters["default"] = adapter
                logger.info(f"默认注册 VLMAdapter (provider={vlm_provider.name})")
            elif include_mock:
                self._adapters["mock"] = VLMAdapter()  # 默认 Mock
                logger.info("默认注册 Mock VLMAdapter")

            self._default_registered = True

    def _select_provider(self, prefer_providers: Optional[List[str]] = None):
        """选择第一个可用的 VLM Provider (None=无可用, 由 Mock 兜底)"""
        from backend.vision.understanding.providers.mock_provider import MockVLMProvider
        from backend.vision.understanding.providers.openai_vlm_provider import (
            OpenAICompatibleVLMProvider,
        )

        order = prefer_providers or ["openai_vlm"]
        for name in order:
            try:
                if name == "openai_vlm":
                    p = OpenAICompatibleVLMProvider()
                    if p.is_available():
                        return p
                elif name == "mock":
                    p = MockVLMProvider()
                    if p.is_available():
                        return p
            except Exception as e:
                logger.warning(f"VLM Provider {name} 加载失败: {e}")
        return None

    # ── 状态 ──────────────────────────────────────────────────────
    def status(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "adapters_count": len(self._adapters),
                "adapters": self.list_adapters(),
                "default_registered": self._default_registered,
            }

    def reset(self) -> None:
        """清空所有注册"""
        with self._lock:
            self._adapters.clear()
            self._default_registered = False


# ── 全局单例 ─────────────────────────────────────────────────────
_global_manager: Optional[UnderstandingManager] = None
_manager_lock = threading.Lock()


def get_manager() -> UnderstandingManager:
    """获取全局 UnderstandingManager 单例"""
    global _global_manager
    with _manager_lock:
        if _global_manager is None:
            _global_manager = UnderstandingManager()
            _global_manager.register_defaults(include_mock=True)
        return _global_manager


def reset_manager() -> None:
    """重置全局 Manager (测试用)"""
    global _global_manager
    with _manager_lock:
        if _global_manager is not None:
            _global_manager.reset()
        _global_manager = None


__all__ = [
    "UnderstandingManager",
    "UnderstandingManagerError",
    "get_manager",
    "reset_manager",
]
