"""
YHLZ Vision Foundation V1.0 - 视觉基础模块

职责:
    - 提供统一视觉输入基础设施
    - 支持 Screen / Camera 双输入源
    - Adapter 可替换 (mss / cv2 / mock / 未来库)
    - 完整权限控制与日志记录
    - 不包含理解能力 (YOLO/OCR/VLM 在后续版本)

架构:
    Interface (VisionService)
        ↓
    Manager (VisionManager)
        ↓
    Adapter (ScreenAdapter / CameraAdapter)
        ↓
    Storage / Schema (VisionFrame)

设计原则:
    - 模块化: 各组件单一职责
    - 接口抽象: VisionAdapter 基类 + 注册表
    - Adapter 可替换: 不绑定单一视觉库
    - 完整异常处理: 所有异常转 Result
    - 类型注解: 全部函数签名
    - Mock 模式: 测试无需真实设备
"""
from backend.vision.schema import (
    VisionFrame,
    VisionSource,
    VisionStatus,
    VisionPermission,
    VisionCaptureRequest,
    VisionCaptureResult,
)
from backend.vision.interface import VisionAdapter, VisionAdapterError
from backend.vision.permission import PermissionChecker, PermissionError
from backend.vision.logger import VisionLogger, VisionLogEntry
from backend.vision.adapters.base import BaseVisionAdapter
from backend.vision.adapters.screen_adapter import ScreenAdapter
from backend.vision.adapters.camera_adapter import CameraAdapter
from backend.vision.adapters.mock_adapter import MockVisionAdapter
from backend.vision.manager import VisionManager, VisionManagerError, get_manager, reset_manager
from backend.vision.service import VisionService, VisionServiceError, get_service, reset_service

__all__ = [
    # Schema
    "VisionFrame", "VisionSource", "VisionStatus", "VisionPermission",
    "VisionCaptureRequest", "VisionCaptureResult",
    # Interface
    "VisionAdapter", "VisionAdapterError",
    # Permission
    "PermissionChecker", "PermissionError",
    # Logger
    "VisionLogger", "VisionLogEntry",
    # Adapters
    "BaseVisionAdapter", "ScreenAdapter", "CameraAdapter", "MockVisionAdapter",
    # Manager / Service
    "VisionManager", "VisionManagerError", "get_manager", "reset_manager",
    "VisionService", "VisionServiceError", "get_service", "reset_service",
]
