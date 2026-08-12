"""
YHLZ Embodied AI V6.2 - Mock 视觉适配器 (Vision Mock Adapter)

职责:
    - Mock 视觉: 合成数据, 行为与真实一致, 不加载真实引擎
    - 可配置: OCR 文本 / 目标列表 / 错误模式
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


class VisionMockAdapter(PerceptionAdapter):
    """Mock 视觉适配器 (合成图像)"""

    name = "vision_mock"
    source = "mock"

    def __init__(
        self,
        ocr_text: str = "YHLZ 感知测试文本",
        objects: Optional[List[Dict[str, Any]]] = None,
        error_mode: bool = False,
        ocr_confidence: float = 0.9,
        detect_confidence: float = 0.85,
    ):
        self._ocr_text = str(ocr_text)
        self._objects = list(objects or [
            {"label": "book", "bbox": [0, 0, 100, 80],
             "confidence": 0.9},
            {"label": "cup", "bbox": [120, 30, 60, 90],
             "confidence": 0.8},
        ])
        self._error_mode = bool(error_mode)
        self._ocr_conf = float(ocr_confidence)
        self._det_conf = float(detect_confidence)

    def is_available(self) -> bool:
        """Mock 始终可用"""
        return True

    def ocr(self, image: Any = None,
            metadata: Optional[Dict[str, Any]] = None) -> OCRResult:
        if self._error_mode:
            raise RuntimeError("Mock OCR 错误模式")
        return OCRResult(text=self._ocr_text,
                         confidence=self._ocr_conf)

    def detect(self, image: Any = None,
               metadata: Optional[Dict[str, Any]] = None
               ) -> DetectionResult:
        if self._error_mode:
            raise RuntimeError("Mock Detection 错误模式")
        return DetectionResult(objects=self._objects,
                               confidence=self._det_conf)


__all__ = ["VisionMockAdapter"]
