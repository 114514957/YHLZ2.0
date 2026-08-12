"""
YHLZ Vision Perception V1.0 - Provider 层

底层库 (PaddleOCR / Tesseract / YOLO / Mock) 的抽象与实现。
Adapter 不直接调用这些库, 而是通过 Provider 间接调用。
"""
from __future__ import annotations

from backend.vision.perception.providers.base import (
    OCRProvider,
    DetectionProvider,
    ProviderError,
)
from backend.vision.perception.providers.mock_provider import (
    MockOCRProvider,
    MockDetectionProvider,
)

__all__ = [
    "OCRProvider",
    "DetectionProvider",
    "ProviderError",
    "MockOCRProvider",
    "MockDetectionProvider",
]
