"""
YHLZ Vision Foundation V1.0 - 权限控制

职责:
    - 校验视觉采集请求是否被允许
    - 管理权限配置 (VisionPermission)
    - 支持运行时动态开关
    - 不直接调用 Adapter (仅做策略判断)

设计原则:
    - 默认拒绝 (screen_enabled / camera_enabled 默认 False)
    - 配置驱动 (从 config 加载, 不硬编码)
    - 可测试 (Mock PermissionChecker)
    - 线程安全 (Lock 保护配置读写)
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Dict, Optional

from backend.vision.schema import (
    VisionCaptureRequest,
    VisionPermission,
    VisionSource,
    VisionStatus,
)

logger = logging.getLogger(__name__)


class PermissionError(Exception):
    """权限校验异常"""


class PermissionChecker:
    """视觉权限检查器

    用法:
        checker = PermissionChecker()
        checker.load_from_dict(config_dict)
        ok, reason = checker.check(request)
        if not ok:
            return error_frame

    线程安全: 内部用 Lock 保护配置读写。
    """

    def __init__(self, permission: Optional[VisionPermission] = None):
        self._lock = threading.RLock()
        self._permission: VisionPermission = permission or VisionPermission()

    @property
    def permission(self) -> VisionPermission:
        """获取当前权限配置 (副本)"""
        with self._lock:
            return VisionPermission(**self._permission.__dict__)

    def load_from_dict(self, d: Dict[str, Any]) -> None:
        """从 dict 加载权限配置"""
        with self._lock:
            self._permission = VisionPermission.from_dict(d)
        logger.info(f"视觉权限配置已加载: screen={self._permission.screen_enabled}, "
                    f"camera={self._permission.camera_enabled}")

    def load_from_permission(self, permission: VisionPermission) -> None:
        """从 VisionPermission 对象加载"""
        with self._lock:
            self._permission = VisionPermission(**permission.__dict__)
        logger.info(f"视觉权限配置已加载: screen={permission.screen_enabled}, "
                    f"camera={permission.camera_enabled}")

    def update(self, **kwargs) -> VisionPermission:
        """更新部分权限字段, 返回更新后的配置"""
        with self._lock:
            current = self._permission.__dict__
            current.update(kwargs)
            self._permission = VisionPermission(**current)
            result = VisionPermission(**current)
        logger.info(f"视觉权限已更新: {kwargs}")
        return result

    def reset(self) -> None:
        """重置为默认配置 (全部拒绝)"""
        with self._lock:
            self._permission = VisionPermission()
        logger.info("视觉权限已重置为默认 (全部拒绝)")

    def check(self, request: VisionCaptureRequest) -> tuple:
        """校验采集请求

        Args:
            request: 采集请求

        Returns:
            (allowed: bool, reason: str)
            - allowed=True 表示通过
            - allowed=False 表示拒绝, reason 描述原因
        """
        with self._lock:
            perm = self._permission

        source = request.source

        # 1. 来源开关校验
        if source == VisionSource.SCREEN.value:
            if not perm.screen_enabled:
                return False, "屏幕采集权限未开启"
        elif source == VisionSource.CAMERA.value:
            if not perm.camera_enabled:
                return False, "摄像头采集权限未开启"
        elif source == VisionSource.MOCK.value:
            # Mock 模式始终允许 (测试用)
            pass
        elif source == VisionSource.FILE.value:
            # 文件输入暂未实现, 但默认允许 (未来扩展)
            pass
        else:
            return False, f"未知视觉来源: {source}"

        # 2. 区域截图权限校验
        if request.region is not None:
            if not perm.allow_region_capture:
                return False, "区域截图权限未开启"
            # 校验区域参数合法性
            region = request.region
            if not all(k in region for k in ("x", "y", "w", "h")):
                return False, "区域参数不完整 (需含 x, y, w, h)"
            if region["w"] <= 0 or region["h"] <= 0:
                return False, "区域尺寸非法 (w/h 必须大于 0)"
            if region["w"] > perm.max_frame_width or region["h"] > perm.max_frame_height:
                return False, f"区域尺寸超出限制 (max {perm.max_frame_width}x{perm.max_frame_height})"

        # 3. resize 校验
        if request.resize is not None:
            resize = request.resize
            if not all(k in resize for k in ("width", "height")):
                return False, "resize 参数不完整 (需含 width, height)"
            if resize["width"] > perm.max_frame_width or resize["height"] > perm.max_frame_height:
                return False, f"resize 尺寸超出限制 (max {perm.max_frame_width}x{perm.max_frame_height})"

        return True, "ok"

    def check_source(self, source: str) -> tuple:
        """校验来源是否被允许 (不检查请求细节)"""
        with self._lock:
            perm = self._permission
        if source == VisionSource.SCREEN.value:
            return perm.screen_enabled, "屏幕采集" if perm.screen_enabled else "屏幕采集未开启"
        if source == VisionSource.CAMERA.value:
            return perm.camera_enabled, "摄像头采集" if perm.camera_enabled else "摄像头采集未开启"
        if source == VisionSource.MOCK.value:
            return True, "mock 模式"
        if source == VisionSource.FILE.value:
            return True, "文件输入"
        return False, f"未知来源: {source}"

    def to_dict(self) -> Dict[str, Any]:
        """导出权限配置"""
        with self._lock:
            return self._permission.to_dict()
