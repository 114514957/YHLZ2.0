"""
YHLZ Vision Foundation V1.0 - Vision Manager

职责:
    - 管理 Adapter 生命周期 (注册/注销/查询)
    - 路由采集请求到对应 Adapter
    - 不直接对外暴露 (Service 调用)
    - 提供统一采集接口 (含权限校验后的执行)

架构位置:
    Service → Manager → Adapter

设计原则:
    - 注册表模式: 多 Adapter 共存
    - 默认注册 Screen / Camera / Mock 三个 Adapter
    - 线程安全 (Lock)
    - 可重置 (测试隔离)
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List, Optional

from backend.vision.adapters.camera_adapter import CameraAdapter
from backend.vision.adapters.mock_adapter import MockVisionAdapter
from backend.vision.adapters.screen_adapter import ScreenAdapter
from backend.vision.interface import VisionAdapter
from backend.vision.schema import (
    VisionCaptureRequest,
    VisionCaptureResult,
    VisionFrame,
    VisionSource,
    VisionStatus,
)

logger = logging.getLogger(__name__)


class VisionManagerError(Exception):
    """Vision Manager 操作异常"""


class VisionManager:
    """视觉采集管理器

    用法:
        mgr = VisionManager()
        mgr.register_adapter("screen", ScreenAdapter())
        mgr.register_adapter("camera", CameraAdapter())
        result = mgr.capture(VisionCaptureRequest(source="screen"))

    职责:
        - Adapter 注册表 (按 source 注册)
        - 路由采集请求到对应 Adapter
        - 记录 Adapter 信息
        - 不做权限校验 (Service 层负责)
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._adapters: Dict[str, VisionAdapter] = {}
        self._default_registered = False

    # ── 注册管理 ──────────────────────────────────────────────────
    def register_adapter(self, source: str, adapter: VisionAdapter, override: bool = False) -> None:
        """注册 Adapter

        Args:
            source: 来源 (screen / camera / mock)
            adapter: 适配器实例
            override: 是否覆盖已注册的同名 Adapter
        """
        with self._lock:
            if source in self._adapters and not override:
                raise VisionManagerError(f"来源 {source} 已注册 Adapter, override=False")
            self._adapters[source] = adapter
            logger.info(f"已注册 Adapter: source={source} name={adapter.name}")

    def unregister_adapter(self, source: str) -> bool:
        """注销 Adapter"""
        with self._lock:
            if source in self._adapters:
                adapter = self._adapters.pop(source)
                try:
                    adapter.disconnect()
                except Exception:
                    pass
                logger.info(f"已注销 Adapter: source={source}")
                return True
            return False

    def get_adapter(self, source: str) -> Optional[VisionAdapter]:
        """获取指定来源的 Adapter"""
        with self._lock:
            return self._adapters.get(source)

    def list_adapters(self) -> List[Dict[str, Any]]:
        """列出所有已注册 Adapter 的信息"""
        with self._lock:
            return [adapter.get_info() for adapter in self._adapters.values()]

    def list_sources(self) -> List[str]:
        """列出所有已注册来源"""
        with self._lock:
            return list(self._adapters.keys())

    def has_adapter(self, source: str) -> bool:
        with self._lock:
            return source in self._adapters

    # ── 采集 ──────────────────────────────────────────────────────
    def capture(self, request: VisionCaptureRequest) -> VisionCaptureResult:
        """执行采集 (路由到对应 Adapter)

        Args:
            request: 采集请求 (source 指定 Adapter)

        Returns:
            VisionCaptureResult (含 frame + latency + adapter 名)
        """
        import time

        source = request.source
        with self._lock:
            adapter = self._adapters.get(source)

        if adapter is None:
            # 无对应 Adapter
            frame = VisionFrame.create_error(
                source=source,
                status=VisionStatus.ERROR.value,
                error=f"无 {source} 来源的 Adapter",
            )
            return VisionCaptureResult(frame=frame, latency_ms=0.0, adapter="none")

        start = time.perf_counter()
        try:
            frame = adapter.capture(request)
            latency = (time.perf_counter() - start) * 1000
            return VisionCaptureResult(
                frame=frame,
                latency_ms=latency,
                adapter=adapter.name,
            )
        except Exception as e:
            latency = (time.perf_counter() - start) * 1000
            logger.error(f"[Manager] Adapter {adapter.name} 采集异常: {e}", exc_info=True)
            frame = VisionFrame.create_error(
                source=source,
                status=VisionStatus.ERROR.value,
                error=f"Manager 捕获异常: {type(e).__name__}: {e}",
            )
            return VisionCaptureResult(frame=frame, latency_ms=latency, adapter=adapter.name)

    # ── 设备查询 ──────────────────────────────────────────────────
    def list_devices(self, source: Optional[str] = None) -> Dict[str, List[Dict[str, Any]]]:
        """列出设备

        Args:
            source: 指定来源 (None=所有来源)

        Returns:
            {source: [devices]}
        """
        with self._lock:
            if source:
                adapter = self._adapters.get(source)
                if adapter is None:
                    return {}
                return {source: adapter.list_devices()}
            return {s: a.list_devices() for s, a in self._adapters.items()}

    # ── 默认注册 ──────────────────────────────────────────────────
    def register_defaults(self, include_mock: bool = True) -> None:
        """注册默认 Adapter (Screen + Camera + Mock)

        Args:
            include_mock: 是否包含 Mock Adapter (测试环境必需)
        """
        with self._lock:
            if self._default_registered:
                return
            # Screen
            if VisionSource.SCREEN.value not in self._adapters:
                try:
                    self._adapters[VisionSource.SCREEN.value] = ScreenAdapter()
                    logger.info("默认注册 ScreenAdapter")
                except Exception as e:
                    logger.warning(f"注册 ScreenAdapter 失败: {e}")
            # Camera
            if VisionSource.CAMERA.value not in self._adapters:
                try:
                    self._adapters[VisionSource.CAMERA.value] = CameraAdapter()
                    logger.info("默认注册 CameraAdapter")
                except Exception as e:
                    logger.warning(f"注册 CameraAdapter 失败: {e}")
            # Mock
            if include_mock and VisionSource.MOCK.value not in self._adapters:
                self._adapters[VisionSource.MOCK.value] = MockVisionAdapter()
                logger.info("默认注册 MockVisionAdapter")
            self._default_registered = True

    # ── 连接管理 ──────────────────────────────────────────────────
    def connect(self, source: str, device_index: int = 0) -> bool:
        """连接指定来源的设备"""
        with self._lock:
            adapter = self._adapters.get(source)
        if adapter is None:
            return False
        return adapter.connect(device_index)

    def disconnect(self, source: str) -> None:
        """断开指定来源的设备"""
        with self._lock:
            adapter = self._adapters.get(source)
        if adapter:
            adapter.disconnect()

    def disconnect_all(self) -> None:
        """断开所有设备"""
        with self._lock:
            for adapter in self._adapters.values():
                try:
                    adapter.disconnect()
                except Exception as e:
                    logger.warning(f"断开 {adapter.name} 失败: {e}")

    # ── 状态 ──────────────────────────────────────────────────────
    def status(self) -> Dict[str, Any]:
        """获取 Manager 状态"""
        with self._lock:
            return {
                "adapters_count": len(self._adapters),
                "sources": list(self._adapters.keys()),
                "adapters_info": [a.get_info() for a in self._adapters.values()],
                "default_registered": self._default_registered,
            }


# ── 全局单例 ─────────────────────────────────────────────────────
_global_manager: Optional[VisionManager] = None
_manager_lock = threading.Lock()


def get_manager() -> VisionManager:
    """获取全局 VisionManager 单例"""
    global _global_manager
    with _manager_lock:
        if _global_manager is None:
            _global_manager = VisionManager()
            _global_manager.register_defaults(include_mock=True)
        return _global_manager


def reset_manager() -> None:
    """重置全局 Manager (测试用)"""
    global _global_manager
    with _manager_lock:
        if _global_manager is not None:
            _global_manager.disconnect_all()
        _global_manager = None
