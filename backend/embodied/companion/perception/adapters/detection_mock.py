"""
YHLZ Embodied AI V6.2 - 检测 Mock 适配器 (Detection Mock Adapter)

职责:
    - Mock 目标检测: 合成目标, 行为与真实一致
    - 可配置: 目标列表 / 置信度 / 错误模式
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from backend.embodied.companion.perception.interface import (
    PerceptionAdapter,
)
from backend.embodied.companion.perception.schema import (
    DetectionResult,
    OCRResult,
)


class DetectionMockAdapter(PerceptionAdapter):
    """检测 Mock 适配器"""

    name = "detection_mock"
    source = "mock"

    def __init__(self,
                 objects: Optional[List[Dict[str, Any]]] = None,
                 confidence: float = 0.85,
                 error_mode: bool = False):
        self._objects = list(objects or [
            {"label": "chair", "bbox": [0, 0, 50, 50],
             "confidence": 0.85},
        ])
        self._confidence = float(confidence)
        self._error_mode = bool(error_mode)

    def is_available(self) -> bool:
        return True

    def ocr(self, image: Any = None,
            metadata: Optional[Dict[str, Any]] = None) -> OCRResult:
        return OCRResult(text="")

    def detect(self, image: Any = None,
               metadata: Optional[Dict[str, Any]] = None
               ) -> DetectionResult:
        if self._error_mode:
            raise RuntimeError("Detection Mock 错误模式")
        return DetectionResult(objects=self._objects,
                               confidence=self._confidence)


__all__ = ["DetectionMockAdapter"]
