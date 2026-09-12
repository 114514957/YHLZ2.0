"""
YHLZ Embodied AI V6.2 - OCR Mock 适配器 (OCR Mock Adapter)

职责:
    - Mock OCR: 合成文本, 行为与真实一致
    - 可配置: 文本 / 置信度 / 错误模式
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from backend.embodied.companion.perception.interface import (
    PerceptionAdapter,
)
from backend.embodied.companion.perception.schema import (
    DetectionResult,
    OCRResult,
)


class OCRMockAdapter(PerceptionAdapter):
    """OCR Mock 适配器"""

    name = "ocr_mock"
    source = "mock"

    def __init__(self, text: str = "YHLZ OCR 文本",
                 confidence: float = 0.9,
                 error_mode: bool = False):
        self._text = str(text)
        self._confidence = float(confidence)
        self._error_mode = bool(error_mode)

    def is_available(self) -> bool:
        return True

    def ocr(self, image: Any = None,
            metadata: Optional[Dict[str, Any]] = None) -> OCRResult:
        if self._error_mode:
            raise RuntimeError("OCR Mock 错误模式")
        return OCRResult(text=self._text,
                         confidence=self._confidence)

    def detect(self, image: Any = None,
               metadata: Optional[Dict[str, Any]] = None
               ) -> DetectionResult:
        return DetectionResult()


__all__ = ["OCRMockAdapter"]
