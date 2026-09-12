"""
YHLZ Vision Perception V1.0 - Mock Provider (测试用)

职责:
    - 提供无模型环境下的 OCR / Detection 合成结果
    - 用于单元测试 / 集成测试 / CI 环境
    - 模拟识别失败 / 异常 / 空结果等场景

设计原则:
    - 无外部依赖 (仅 numpy)
    - 可配置行为 (返回特定文本/对象/错误模式)
    - 不进入生产代码路径
"""
from __future__ import annotations

import logging
from typing import Any, List, Optional

from backend.vision.perception.interface import PerceptionOptions
from backend.vision.perception.providers.base import (
    DetectionProvider,
    OCRProvider,
    ProviderError,
)
from backend.vision.perception.schema import (
    BoundingBox,
    DetectedObject,
    DetectedText,
)

logger = logging.getLogger(__name__)


class MockOCRProvider(OCRProvider):
    """Mock OCR Provider (测试专用)

    用法:
        # 正常模式
        provider = MockOCRProvider()
        texts = provider.recognize_text(image)  # 返回合成文本

        # 模拟空结果
        provider = MockOCRProvider(mode="empty")

        # 模拟异常
        provider = MockOCRProvider(mode="exception")

        # 自定义返回文本
        provider = MockOCRProvider(texts=["你好", "世界"])
    """

    name: str = "mock"

    def __init__(
        self,
        mode: str = "ok",                  # ok / empty / exception
        texts: Optional[List[str]] = None,
        language: str = "zh",
        confidence: float = 0.95,
        available: bool = True,
    ):
        self._mode = mode
        self._texts = texts or ["测试文本一", "测试文本二", "Hello World"]
        self._language = language
        self._confidence = confidence
        self._available = available
        self._call_count = 0

    def is_available(self) -> bool:
        return self._available

    def recognize_text(
        self,
        image: Any,
        options: Optional[PerceptionOptions] = None,
    ) -> List[DetectedText]:
        self._call_count += 1

        if not self._available:
            raise ProviderError("Mock OCR Provider 不可用")

        if self._mode == "exception":
            raise ProviderError("Mock OCR 异常 (mode=exception)")

        if self._mode == "empty":
            return []

        # ok 模式: 生成合成文本
        language = (options.language if options else self._language) or self._language
        result: List[DetectedText] = []
        for i, text in enumerate(self._texts):
            # 在图像高度内均匀分布文本位置
            position = None
            if image is not None and hasattr(image, "shape"):
                h, w = image.shape[:2]
                y = int((i + 1) * h / (len(self._texts) + 1))
                position = BoundingBox(x=10, y=y - 20, w=max(50, len(text) * 15), h=30)
            result.append(DetectedText(
                content=text,
                language=language,
                confidence=self._confidence,
                position=position,
            ))
        return result

    def set_mode(self, mode: str) -> None:
        """运行时切换模式"""
        self._mode = mode

    def set_available(self, available: bool) -> None:
        """运行时切换可用性"""
        self._available = available

    @property
    def call_count(self) -> int:
        return self._call_count

    def reset(self) -> None:
        self._call_count = 0
        self._mode = "ok"
        self._available = True

    def get_info(self) -> dict:
        info = super().get_info()
        info["mode"] = self._mode
        info["call_count"] = self._call_count
        return info


class MockDetectionProvider(DetectionProvider):
    """Mock Detection Provider (测试专用)

    用法:
        provider = MockDetectionProvider()
        objects = provider.detect_objects(image)
    """

    name: str = "mock"

    def __init__(
        self,
        mode: str = "ok",                  # ok / empty / exception
        objects: Optional[List[DetectedObject]] = None,
        available: bool = True,
    ):
        self._mode = mode
        self._available = available
        self._call_count = 0
        # 默认合成对象
        self._default_objects = objects or [
            DetectedObject(
                name="person",
                category="human",
                position=BoundingBox(x=100, y=100, w=80, h=120),
                confidence=0.92,
            ),
            DetectedObject(
                name="laptop",
                category="electronics",
                position=BoundingBox(x=200, y=200, w=150, h=100),
                confidence=0.88,
            ),
            DetectedObject(
                name="cup",
                category="kitchen",
                position=BoundingBox(x=50, y=300, w=40, h=50),
                confidence=0.75,
            ),
        ]

    def is_available(self) -> bool:
        return self._available

    def detect_objects(
        self,
        image: Any,
        options: Optional[PerceptionOptions] = None,
    ) -> List[DetectedObject]:
        self._call_count += 1

        if not self._available:
            raise ProviderError("Mock Detection Provider 不可用")

        if self._mode == "exception":
            raise ProviderError("Mock Detection 异常 (mode=exception)")

        if self._mode == "empty":
            return []

        # 应用 max_objects
        result = list(self._default_objects)
        if options and options.max_objects is not None:
            result = result[:options.max_objects]
        # 应用 min_confidence
        if options and options.min_confidence > 0:
            result = [o for o in result if o.confidence >= options.min_confidence]
        return result

    def set_mode(self, mode: str) -> None:
        self._mode = mode

    def set_available(self, available: bool) -> None:
        self._available = available

    @property
    def call_count(self) -> int:
        return self._call_count

    def reset(self) -> None:
        self._call_count = 0
        self._mode = "ok"
        self._available = True

    def get_info(self) -> dict:
        info = super().get_info()
        info["mode"] = self._mode
        info["call_count"] = self._call_count
        return info


__all__ = ["MockOCRProvider", "MockDetectionProvider"]
