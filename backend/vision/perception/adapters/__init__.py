"""
YHLZ Vision Perception V1.0 - Adapters 包入口
"""
from __future__ import annotations

from backend.vision.perception.adapters.ocr_adapter import OCRAdapter as OCRAdapterImpl
from backend.vision.perception.adapters.detection_adapter import (
    DetectionAdapter as DetectionAdapterImpl,
)

__all__ = ["OCRAdapterImpl", "DetectionAdapterImpl"]
