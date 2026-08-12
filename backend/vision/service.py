"""
YHLZ Vision Foundation V1.0 - Vision Service

职责:
    - 统一对外 API (Interface 层)
    - 组合 Manager + Permission + Logger
    - 权限校验 → 采集 → 日志记录 完整流程
    - 不直接调用 Adapter (经 Manager 路由)

架构位置:
    Interface (FastAPI / 外部调用)
        ↓
    Service (本模块)
        ↓
    Manager → Adapter

设计原则:
    - 单一入口: 所有视觉操作经 Service
    - 权限优先: 采集前先校验权限
    - 日志完整: 记录开始/成功/失败/耗时/异常
    - 配置驱动: 从 config 加载权限与参数
    - 可测试: 提供完整 Mock 注入接口
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List, Optional

from backend.vision.logger import VisionLogger
from backend.vision.manager import VisionManager, get_manager, reset_manager
from backend.vision.permission import PermissionChecker
from backend.vision.schema import (
    VisionCaptureRequest,
    VisionCaptureResult,
    VisionFrame,
    VisionPermission,
    VisionSource,
    VisionStatus,
)

logger = logging.getLogger(__name__)


class VisionServiceError(Exception):
    """Vision Service 操作异常"""


class VisionService:
    """视觉采集统一服务

    用法:
        svc = VisionService()
        svc.load_config(config_dict)
        result = svc.capture(VisionCaptureRequest(source="screen"))

    流程:
        1. 权限校验 (PermissionChecker)
        2. 采集 (Manager → Adapter)
        3. 日志记录 (VisionLogger)
        4. 返回 VisionCaptureResult
    """

    def __init__(
        self,
        manager: Optional[VisionManager] = None,
        permission: Optional[PermissionChecker] = None,
        vlog: Optional[VisionLogger] = None,
    ):
        self._lock = threading.RLock()
        self._manager: VisionManager = manager or VisionManager()
        self._permission: PermissionChecker = permission or PermissionChecker()
        self._vlog: VisionLogger = vlog or VisionLogger()
        self._initialized = False

    # ── 依赖注入 ──────────────────────────────────────────────────
    def set_manager(self, manager: VisionManager) -> None:
        with self._lock:
            self._manager = manager

    def set_permission(self, permission: PermissionChecker) -> None:
        with self._lock:
            self._permission = permission

    def set_logger(self, vlog: VisionLogger) -> None:
        with self._lock:
            self._vlog = vlog

    @property
    def manager(self) -> VisionManager:
        return self._manager

    @property
    def permission(self) -> PermissionChecker:
        return self._permission

    @property
    def vlog(self) -> VisionLogger:
        return self._vlog

    # ── 配置 ──────────────────────────────────────────────────────
    def load_config(self, config: Dict[str, Any]) -> None:
        """从 dict 加载配置 (权限 + 默认注册)"""
        with self._lock:
            # 权限配置
            perm = VisionPermission.from_dict(config)
            self._permission.load_from_permission(perm)
            # 默认 Adapter 注册
            self._manager.register_defaults(include_mock=True)
            self._initialized = True
        logger.info(f"VisionService 配置已加载: {perm.to_dict()}")

    def load_permission(self, permission: VisionPermission) -> None:
        """加载权限配置"""
        self._permission.load_from_permission(permission)

    def update_permission(self, **kwargs) -> VisionPermission:
        """更新权限字段"""
        return self._permission.update(**kwargs)

    def get_permission(self) -> Dict[str, Any]:
        """获取当前权限配置"""
        return self._permission.to_dict()

    def reset_permission(self) -> None:
        """重置权限为默认 (全部拒绝)"""
        self._permission.reset()

    # ── 核心采集 ──────────────────────────────────────────────────
    def capture(self, request: VisionCaptureRequest) -> VisionCaptureResult:
        """执行视觉采集 (完整流程)

        流程:
            1. 日志记录开始
            2. 权限校验
            3. Manager 路由到 Adapter 采集
            4. 日志记录成功/失败
            5. 返回结果

        Args:
            request: 采集请求

        Returns:
            VisionCaptureResult
        """
        # 1. 日志记录开始
        self._vlog.log_start(
            source=request.source,
            adapter="unknown",  # 实际 adapter 名在 result 中
            metadata=request.to_dict(),
        )

        # 2. 权限校验
        allowed, reason = self._permission.check(request)
        if not allowed:
            # 权限拒绝
            import time
            start = time.perf_counter()
            latency = (time.perf_counter() - start) * 1000
            frame = VisionFrame.create_error(
                source=request.source,
                status=VisionStatus.PERMISSION_DENIED.value,
                error=reason,
                metadata=request.to_dict(),
            )
            result = VisionCaptureResult(
                frame=frame,
                latency_ms=latency,
                adapter="none",
            )
            self._vlog.log_fail(
                source=request.source,
                adapter="none",
                status=VisionStatus.PERMISSION_DENIED.value,
                error=reason,
                latency_ms=latency,
            )
            return result

        # 3. Manager 采集
        result = self._manager.capture(request)

        # 4. 日志记录
        if result.is_ok:
            self._vlog.log_success(
                source=request.source,
                adapter=result.adapter,
                frame_id=result.frame.id,
                latency_ms=result.latency_ms,
            )
        else:
            self._vlog.log_fail(
                source=request.source,
                adapter=result.adapter,
                status=result.frame.status,
                error=result.frame.error or "未知错误",
                latency_ms=result.latency_ms,
            )

        return result

    def capture_screen(
        self,
        region: Optional[Dict[str, int]] = None,
        resize: Optional[Dict[str, int]] = None,
        monitor: int = 1,
    ) -> VisionCaptureResult:
        """快捷采集屏幕

        Args:
            region: 区域 {x, y, w, h} (None=全屏)
            resize: 缩放 {width, height}
            monitor: 显示器索引 (默认 1=主屏)
        """
        metadata = {"monitor": monitor}
        request = VisionCaptureRequest(
            source=VisionSource.SCREEN.value,
            region=region,
            resize=resize,
            metadata=metadata,
        )
        return self.capture(request)

    def capture_camera(
        self,
        device_index: int = 0,
        resize: Optional[Dict[str, int]] = None,
    ) -> VisionCaptureResult:
        """快捷采集摄像头

        Args:
            device_index: 设备索引 (默认 0)
            resize: 缩放 {width, height}
        """
        request = VisionCaptureRequest(
            source=VisionSource.CAMERA.value,
            device_index=device_index,
            resize=resize,
        )
        return self.capture(request)

    def capture_mock(
        self,
        width: int = 640,
        height: int = 480,
    ) -> VisionCaptureResult:
        """快捷采集 Mock (测试用)"""
        request = VisionCaptureRequest(
            source=VisionSource.MOCK.value,
            resize={"width": width, "height": height},
        )
        return self.capture(request)

    # ── 设备管理 ──────────────────────────────────────────────────
    def list_adapters(self) -> List[Dict[str, Any]]:
        """列出所有 Adapter"""
        return self._manager.list_adapters()

    def list_devices(self, source: Optional[str] = None) -> Dict[str, List[Dict[str, Any]]]:
        """列出设备"""
        return self._manager.list_devices(source)

    def connect(self, source: str, device_index: int = 0) -> bool:
        """连接设备"""
        return self._manager.connect(source, device_index)

    def disconnect(self, source: str) -> None:
        """断开设备"""
        self._manager.disconnect(source)

    def disconnect_all(self) -> None:
        """断开所有设备"""
        self._manager.disconnect_all()

    # ── 日志查询 ──────────────────────────────────────────────────
    def get_logs(
        self,
        source: Optional[str] = None,
        adapter: Optional[str] = None,
        event: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """查询日志"""
        entries = self._vlog.query(source=source, adapter=adapter, event=event, limit=limit)
        return [e.to_dict() for e in entries]

    def get_log_stats(self) -> Dict[str, Any]:
        """获取日志统计"""
        return self._vlog.stats()

    def clear_logs(self) -> int:
        """清空日志"""
        return self._vlog.clear()

    # ── 状态 ──────────────────────────────────────────────────────
    def status(self) -> Dict[str, Any]:
        """获取系统状态"""
        return {
            "version": "1.0.0",
            "initialized": self._initialized,
            "permission": self._permission.to_dict(),
            "manager": self._manager.status(),
            "log_stats": self._vlog.stats(),
        }


# ── 全局单例 ─────────────────────────────────────────────────────
_global_service: Optional[VisionService] = None
_service_lock = threading.Lock()


def get_service() -> VisionService:
    """获取全局 VisionService 单例"""
    global _global_service
    with _service_lock:
        if _global_service is None:
            mgr = get_manager()
            _global_service = VisionService(manager=mgr)
        return _global_service


def reset_service() -> None:
    """重置全局 Service (测试用)"""
    global _global_service
    with _service_lock:
        if _global_service is not None:
            _global_service.disconnect_all()
        _global_service = None
    reset_manager()
