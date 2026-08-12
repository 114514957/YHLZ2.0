"""
YHLZ Embodied AI V6.8 - 本地智能提供器 (Local Provider)

职责:
    - 本地智能执行门面 (负责存在: 身份/记忆/安全/用户数据/实时感知)
    - 通过 LocalCapabilityRegistry 调度本地能力

原则 (本地负责存在):
    - 身份/记忆/权限/安全 永远本地处理
    - 不对外传输用户数据

设计原则:
    - 纯规则 (无黑盒)
    - 异常不外抛 (结构化错误帧)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import uuid
from typing import Any, Dict, Optional

from backend.embodied.companion.hybrid.local.local_capability import (
    LocalCapability,
    LocalCapabilityError,
    LocalCapabilityRegistry,
)

logger = logging.getLogger(__name__)


class LocalProviderError(Exception):
    """本地智能提供器操作异常"""


class LocalProvider:
    """本地智能提供器

    用法:
        provider = LocalProvider()
        provider.register_defaults()
        result = provider.execute("identity", {"query": "我是谁"})
    """

    def __init__(
        self,
        registry: Optional[LocalCapabilityRegistry] = None,
        enabled: bool = True,
    ):
        self._lock = threading.RLock()
        self._enabled = bool(enabled)
        self._registry = registry or LocalCapabilityRegistry()
        self._execute_count = 0

    # ── 初始化 ───────────────────────────────────────────────────
    def register_defaults(self) -> int:
        """注册默认本地能力"""
        return self._registry.register_defaults()

    # ── 执行 ─────────────────────────────────────────────────────
    def execute(
        self,
        capability: str,
        request: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """执行本地能力

        Args:
            capability: 能力名 (identity/memory/vision/...)
            request: 请求 (query/text 等)

        Returns:
            执行结果 (异常 → 结构化错误帧, 不外抛)
        """
        with self._lock:
            if not self._enabled:
                return self._error(
                    capability, "本地智能提供器停用",
                )
            try:
                result = self._registry.execute(
                    capability, request or {},
                )
                self._execute_count += 1
                result["provider"] = "local"
                return result
            except LocalCapabilityError as e:
                return self._error(capability, str(e))
            except Exception as e:
                logger.warning(f"[Hybrid] 本地执行异常: {e}")
                return self._error(
                    capability, f"本地执行失败: {e}",
                )

    # ── 能力查询 ─────────────────────────────────────────────────
    def has_capability(self, name: str) -> bool:
        """是否具备本地能力"""
        return self._registry.get(name) is not None

    def capabilities(self) -> Dict[str, Any]:
        """全部本地能力"""
        return self._registry.list_all()

    def _error(self, capability: str,
               reason: str) -> Dict[str, Any]:
        return {
            "provider": "local",
            "capability": capability,
            "ok": False,
            "reason": reason,
            "mode": "error_frame",
        }

    # ── 查询 ─────────────────────────────────────────────────────
    def stats(self) -> Dict[str, Any]:
        """本地提供器统计"""
        with self._lock:
            reg = self._registry.stats()
            reg["provider"] = "local"
            reg["execute_count"] = self._execute_count
            reg["enabled"] = self._enabled
            return reg

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = self._registry.clear()
            self._execute_count = 0
            return n


__all__ = [
    "LocalProvider",
    "LocalProviderError",
]
