"""
YHLZ Vision Foundation V1.0 - 视觉数据结构

职责:
    - 定义统一视觉数据模型 (VisionFrame)
    - 枚举: 视觉来源 / 帧状态
    - 权限模型 / 采集请求 / 采集结果
    - 不依赖任何外部库 (仅 stdlib + typing)

设计原则:
    - 不可变 (frozen dataclass)
    - 类型注解完整
    - 兼容 JSON 序列化 (to_dict / from_dict)
    - image 字段为 numpy ndarray, 不参与序列化
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


class VisionSource(str, Enum):
    """视觉输入源"""
    SCREEN = "screen"      # 屏幕截图
    CAMERA = "camera"      # 摄像头
    MOCK = "mock"          # 测试用
    FILE = "file"          # 文件输入 (未来扩展)


class VisionStatus(str, Enum):
    """帧采集状态"""
    OK = "ok"                          # 成功
    ERROR = "error"                    # 通用错误
    PERMISSION_DENIED = "denied"       # 权限拒绝
    NO_DEVICE = "no_device"            # 设备不存在
    TIMEOUT = "timeout"                # 超时
    DISCONNECTED = "disconnected"      # 设备断开


@dataclass
class VisionPermission:
    """视觉权限配置

    控制各输入源的开关与采集参数。
    """
    screen_enabled: bool = False       # 屏幕采集开关 (默认关闭, 需用户授权)
    camera_enabled: bool = False       # 摄像头采集开关 (默认关闭, 需用户授权)
    capture_interval: float = 1.0      # 采集频率 (秒/帧, 防止过载)
    save_policy: str = "memory"        # 保存策略: memory(仅内存) / disk(落盘) / off(不保存)
    max_frame_width: int = 1920        # 最大宽度 (像素, 超过则缩放)
    max_frame_height: int = 1080       # 最大高度
    allow_region_capture: bool = True  # 是否允许区域截图

    def to_dict(self) -> Dict[str, Any]:
        return {
            "screen_enabled": self.screen_enabled,
            "camera_enabled": self.camera_enabled,
            "capture_interval": self.capture_interval,
            "save_policy": self.save_policy,
            "max_frame_width": self.max_frame_width,
            "max_frame_height": self.max_frame_height,
            "allow_region_capture": self.allow_region_capture,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "VisionPermission":
        return cls(
            screen_enabled=d.get("screen_enabled", False),
            camera_enabled=d.get("camera_enabled", False),
            capture_interval=d.get("capture_interval", 1.0),
            save_policy=d.get("save_policy", "memory"),
            max_frame_width=d.get("max_frame_width", 1920),
            max_frame_height=d.get("max_frame_height", 1080),
            allow_region_capture=d.get("allow_region_capture", True),
        )


@dataclass
class VisionFrame:
    """统一视觉帧数据结构

    所有 Adapter 输出统一为此结构, 供 Service / Manager / 未来理解层使用。

    字段:
        id:            帧唯一 ID (uuid4)
        source:        来源 (screen / camera / mock)
        timestamp:     采集时间戳 (unix 秒)
        permission:    采集时的权限快照
        metadata:      额外元数据 (设备名/区域/分辨率等)
        status:        采集状态
        image:         numpy ndarray (HxWxC, BGR), 失败时为 None
        width:         图像宽度
        height:        图像高度
        channels:      通道数 (通常 3)
        error:         失败时的错误描述
    """
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    source: str = "unknown"
    timestamp: float = field(default_factory=time.time)
    permission: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    status: str = VisionStatus.OK.value
    image: Any = None  # numpy.ndarray, 不参与 JSON 序列化
    width: int = 0
    height: int = 0
    channels: int = 3
    error: Optional[str] = None

    @property
    def is_ok(self) -> bool:
        """帧是否成功采集"""
        return self.status == VisionStatus.OK.value and self.image is not None

    @property
    def is_error(self) -> bool:
        return not self.is_ok

    def to_dict(self, include_image: bool = False) -> Dict[str, Any]:
        """转 dict (默认不含 image 数据)

        Args:
            include_image: 是否包含 image (编码为 base64 或 bytes, 默认 False)
        """
        d = {
            "id": self.id,
            "source": self.source,
            "timestamp": self.timestamp,
            "permission": self.permission,
            "metadata": self.metadata,
            "status": self.status,
            "width": self.width,
            "height": self.height,
            "channels": self.channels,
            "error": self.error,
        }
        if include_image and self.image is not None:
            try:
                import base64
                import cv2
                _, buf = cv2.imencode(".jpg", self.image)
                d["image_b64"] = base64.b64encode(buf).decode("ascii")
            except Exception as e:
                d["image_b64"] = None
                d["image_encode_error"] = str(e)
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "VisionFrame":
        """从 dict 恢复 (image 字段需单独处理)"""
        return cls(
            id=d.get("id", uuid.uuid4().hex),
            source=d.get("source", "unknown"),
            timestamp=d.get("timestamp", time.time()),
            permission=d.get("permission", {}),
            metadata=d.get("metadata", {}),
            status=d.get("status", VisionStatus.OK.value),
            width=d.get("width", 0),
            height=d.get("height", 0),
            channels=d.get("channels", 3),
            error=d.get("error"),
        )

    @classmethod
    def create_ok(
        cls,
        source: str,
        image: Any,
        permission: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "VisionFrame":
        """快捷构造成功帧"""
        import numpy as np
        if image is not None and isinstance(image, np.ndarray):
            if image.ndim == 2:
                height, width = image.shape
                channels = 1
            else:
                height, width, channels = image.shape
        else:
            height = width = channels = 0
        return cls(
            source=source,
            status=VisionStatus.OK.value,
            image=image,
            width=width,
            height=height,
            channels=channels,
            permission=permission or {},
            metadata=metadata or {},
        )

    @classmethod
    def create_error(
        cls,
        source: str,
        status: str,
        error: str,
        permission: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "VisionFrame":
        """快捷构造失败帧"""
        return cls(
            source=source,
            status=status,
            error=error,
            image=None,
            permission=permission or {},
            metadata=metadata or {},
        )


@dataclass
class VisionCaptureRequest:
    """采集请求参数"""
    source: str = "screen"             # 输入源
    region: Optional[Dict[str, int]] = None  # 区域截图 {x, y, w, h} (None=全屏)
    device_index: int = 0              # 摄像头设备索引 (source=camera 时有效)
    resize: Optional[Dict[str, int]] = None  # 缩放 {width, height}
    metadata: Optional[Dict[str, Any]] = None  # 附加元数据

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "region": self.region,
            "device_index": self.device_index,
            "resize": self.resize,
            "metadata": self.metadata,
        }


@dataclass
class VisionCaptureResult:
    """采集结果 (封装 VisionFrame + 统计信息)"""
    frame: VisionFrame
    latency_ms: float = 0.0
    adapter: str = "unknown"

    @property
    def is_ok(self) -> bool:
        return self.frame.is_ok

    def to_dict(self, include_image: bool = False) -> Dict[str, Any]:
        return {
            "frame": self.frame.to_dict(include_image=include_image),
            "latency_ms": round(self.latency_ms, 2),
            "adapter": self.adapter,
        }
