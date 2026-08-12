"""
YHLZ Vision Foundation V1.0 - 摄像头采集 Adapter

职责:
    - 实现摄像头图像采集
    - 设备检测 / 连接管理 / 图像读取 / 异常处理
    - 使用 OpenCV (cv2.VideoCapture)
    - Mock 模式: 无摄像头环境返回错误帧而非崩溃

依赖:
    - cv2 (OpenCV, VideoCapture)
    - numpy

设计原则:
    - 不绑定单一库: 可替换为 pygame.camera / v4l2
    - 连接管理: connect/disconnect 控制设备生命周期
    - 异常隔离: 断开/无设备返回 NO_DEVICE 错误帧
    - 线程安全: 单实例, 内部用 Lock 保护 capture 调用
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List

import numpy as np

from backend.vision.adapters.base import BaseVisionAdapter
from backend.vision.schema import VisionCaptureRequest, VisionSource, VisionStatus

logger = logging.getLogger(__name__)


class CameraAdapter(BaseVisionAdapter):
    """摄像头采集 Adapter (基于 OpenCV)

    用法:
        adapter = CameraAdapter()
        if adapter.is_available():
            adapter.connect(device_index=0)
            frame = adapter.capture(VisionCaptureRequest(source="camera"))
            adapter.disconnect()

    特性:
        - 跨平台 (Windows / macOS / Linux)
        - 支持多摄像头 (通过 device_index 指定)
        - 自动检测可用设备 (探测 0~9)
        - 连接断开自动重连
        - 无设备时返回 NO_DEVICE 错误帧
    """

    name: str = "CameraAdapter"
    source: str = VisionSource.CAMERA.value

    def __init__(self, max_detect: int = 5):
        self._lock = threading.RLock()
        self._cap = None  # cv2.VideoCapture
        self._device_index: int = -1
        self._connected: bool = False
        self._devices_cache: List[Dict[str, Any]] = []
        self._max_detect = max_detect  # 设备探测上限

    def _check_available(self) -> bool:
        """检查 cv2 是否可用 + 是否有摄像头设备"""
        try:
            import cv2
            # 探测设备 (不打开, 仅检查枚举)
            devices = self._detect_devices()
            return len(devices) > 0
        except ImportError:
            logger.warning("cv2 未安装, CameraAdapter 不可用")
            return False
        except Exception as e:
            logger.warning(f"CameraAdapter 可用性检查失败: {e}")
            return False

    def _detect_devices(self) -> List[Dict[str, Any]]:
        """探测可用摄像头设备 (打开测试, 然后释放)

        策略: 尝试打开 0 ~ max_detect-1, 能成功打开且能读取帧的算作可用
        """
        import cv2
        devices = []
        for i in range(self._max_detect):
            try:
                cap = cv2.VideoCapture(i, cv2.CAP_DSHOW) if hasattr(cv2, "CAP_DSHOW") else cv2.VideoCapture(i)
                if cap.isOpened():
                    ret, _ = cap.read()
                    if ret:
                        devices.append({
                            "index": i,
                            "name": f"Camera {i}",
                            "type": "camera",
                            "backend": "cv2",
                        })
                cap.release()
            except Exception:
                continue
        self._devices_cache = devices
        return devices

    def list_devices(self) -> List[Dict[str, Any]]:
        """列出可用摄像头"""
        return list(self._devices_cache)

    def connect(self, device_index: int = 0) -> bool:
        """连接摄像头

        Args:
            device_index: 设备索引 (默认 0)

        Returns:
            True 连接成功
        """
        with self._lock:
            try:
                import cv2
                # 先断开旧连接
                self._disconnect_internal()

                backend = cv2.CAP_DSHOW if hasattr(cv2, "CAP_DSHOW") else None
                if backend is not None:
                    self._cap = cv2.VideoCapture(device_index, backend)
                else:
                    self._cap = cv2.VideoCapture(device_index)

                if not self._cap.isOpened():
                    logger.warning(f"摄像头 {device_index} 打开失败")
                    self._connected = False
                    return False

                self._device_index = device_index
                self._connected = True
                logger.info(f"摄像头 {device_index} 连接成功")
                return True
            except Exception as e:
                logger.error(f"连接摄像头 {device_index} 失败: {e}")
                self._connected = False
                return False

    def disconnect(self) -> None:
        """断开摄像头"""
        with self._lock:
            self._disconnect_internal()

    def _disconnect_internal(self) -> None:
        """内部断开 (调用方需持有锁)"""
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None
        self._connected = False
        self._device_index = -1

    def _do_capture(self, request: VisionCaptureRequest) -> np.ndarray:
        """执行摄像头采集

        Args:
            request: 采集请求 (device_index 指定设备)

        Returns:
            numpy ndarray (HxWxC, BGR)
        """
        import cv2

        with self._lock:
            # 检查连接, 必要时重连
            target_device = request.device_index if request.device_index is not None else 0
            if not self._connected or self._cap is None or self._device_index != target_device:
                if not self.connect(target_device):
                    raise RuntimeError(f"摄像头 {target_device} 连接失败")

            # 读取帧
            ret, frame = self._cap.read()
            if not ret or frame is None:
                # 读取失败, 标记断开
                self._connected = False
                raise RuntimeError(f"摄像头 {target_device} 读取失败 (设备可能断开)")

            return frame

    def get_info(self) -> Dict[str, Any]:
        info = super().get_info()
        info["library"] = "cv2"
        info["connected"] = self._connected
        info["device_index"] = self._device_index
        return info
