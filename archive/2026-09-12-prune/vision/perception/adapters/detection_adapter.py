"""
YHLZ Vision Perception V1.0 - Detection Adapter (基于 Provider)

职责:
    - 组合 DetectionProvider (YOLO / Mock)
    - 对外提供统一 detect 接口
    - 不绑定单一检测库

本版本范围:
    - 接口完整实现
    - 默认 MockDetectionProvider (无 YOLO 环境也能工作)
    - 真实 YOLO 接入在 V1.1 / V2.0 完善
"""
from __future__ import annotations

import logging
from typing import Optional

from backend.vision.perception.base import BaseDetectionAdapter
from backend.vision.perception.providers.base import DetectionProvider
from backend.vision.perception.providers.mock_provider import MockDetectionProvider

logger = logging.getLogger(__name__)


class DetectionAdapter(BaseDetectionAdapter):
    """Detection Adapter (生产可注入任意 DetectionProvider)

    用法:
        # Mock 模式 (测试)
        adapter = DetectionAdapter()

        # YOLO 模式
        from backend.vision.perception.providers.yolo_provider import YOLOProvider
        adapter = DetectionAdapter(provider=YOLOProvider())
    """

    name: str = "DetectionAdapter"
    source: str = "detection"

    def __init__(self, provider: Optional[DetectionProvider] = None):
        # 默认 Mock
        super().__init__(provider=provider or MockDetectionProvider())
        if provider is None:
            logger.debug("DetectionAdapter 未指定 Provider, 使用 MockDetectionProvider")

    def get_info(self) -> dict:
        info = super().get_info()
        info["default_provider"] = "mock"
        return info


__all__ = ["DetectionAdapter"]
