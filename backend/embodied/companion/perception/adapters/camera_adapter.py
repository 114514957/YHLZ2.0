"""
YHLZ Embodied AI V6.2 - 摄像头适配器 (Camera Adapter)

职责:
    - OpenCV 摄像头采集 (真实设备)
    - 无 OpenCV / 无摄像头 → is_available=False (测试 skipIf)
    - 采集必须经 Permission (Service 层校验, 默认拒绝)

设计原则:
    - 真实适配器与 Mock 同一接口 (行为一致)
    - 摄像头默认关闭 (高权限感知默认拒绝)
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from backend.embodied.companion.perception.interface import (
    PerceptionAdapter,
)
from backend.embodied.companion.perception.schema import (
    DetectionResult,
    OCRResult,
)

logger = logging.getLogger(__name__)


class CameraAdapter(PerceptionAdapter):
    """摄像头适配器 (OpenCV)"""

    name = "camera"
    source = "camera"

    def __init__(self, device_index: int = 0,
                 ocr_text: str = "摄像头OCR文本"):
        self._device_index = int(device_index)
        self._ocr_text = str(ocr_text)
        self._connected = False
        self._capture = None
        self._try_load_cv2()

    def _try_load_cv2(self) -> None:
        """尝试加载 OpenCV (不可用则不加载)"""
        self._cv2 = None
        try:
            import cv2  # type: ignore
            self._cv2 = cv2
        except ImportError:
            logger.info("[Perception] OpenCV 不可用, "
                        "摄像头适配器将报告不可用")

    def is_available(self) -> bool:
        """无 OpenCV / 无设备 → 不可用"""
        if self._cv2 is None:
            return False
        try:
            cap = self._cv2.VideoCapture(self._device_index)
            ok = cap.isOpened()
            cap.release()
            return ok
        except Exception:
            return False

    def connect(self) -> bool:
        if self._cv2 is None:
            return False
        try:
            self._capture = self._cv2.VideoCapture(
                self._device_index,
            )
            self._connected = self._capture.isOpened()
            return self._connected
        except Exception:
            self._connected = False
            return False

    def disconnect(self) -> None:
        if self._capture is not None:
            try:
                self._capture.release()
            except Exception:
                pass
        self._capture = None
        self._connected = False

    def _grab(self) -> Any:
        """采集一帧 (未连接则尝试连接)"""
        if not self._connected:
            self.connect()
        if not self._connected or self._capture is None:
            raise RuntimeError("摄像头未连接")
        ok, frame = self._capture.read()
        if not ok:
            raise RuntimeError("摄像头读取失败")
        return frame

    def ocr(self, image: Any = None,
            metadata: Optional[Dict[str, Any]] = None) -> OCRResult:
        """摄像头采集 → OCR (规则占位, 真实 OCR 引擎 V6.3 接入)"""
        if image is None:
            self._grab()
        return OCRResult(text=self._ocr_text, confidence=0.7)

    def detect(self, image: Any = None,
               metadata: Optional[Dict[str, Any]] = None
               ) -> DetectionResult:
        if image is None:
            self._grab()
        return DetectionResult(objects=[], confidence=0.5)


__all__ = ["CameraAdapter"]
