"""
YHLZ Vision Perception V1.0 - Provider 抽象基类

职责:
    - 定义 OCRProvider / DetectionProvider 抽象接口
    - 屏蔽底层库差异 (PaddleOCR / Tesseract / YOLO / Mock)
    - Adapter 通过 Provider 调用底层库

设计原则:
    - Provider 是底层封装层 (Adapter 调用 Provider)
    - Provider 可抛异常 (实现层)
    - Adapter 捕获 Provider 异常并转为错误结果
    - 不绑定单一库: 每个库一个 Provider 实现
"""
from __future__ import annotations

import abc
from typing import Any, Dict, List, Optional

from backend.vision.perception.interface import PerceptionOptions
from backend.vision.perception.schema import DetectedObject, DetectedText


class ProviderError(Exception):
    """Provider 操作异常"""


class OCRProvider(abc.ABC):
    """OCR Provider 抽象基类

    子类必须实现:
        name (类属性): provider 名 (paddleocr / tesseract / mock)
        is_available(): 库是否可用
        recognize_text(image, options) -> List[DetectedText]
    """

    name: str = "abstract_ocr_provider"

    @abc.abstractmethod
    def is_available(self) -> bool:
        """检测库 / 模型是否可用"""
        raise NotImplementedError

    @abc.abstractmethod
    def recognize_text(
        self,
        image: Any,
        options: Optional[PerceptionOptions] = None,
    ) -> List[DetectedText]:
        """执行 OCR 识别

        Args:
            image: numpy ndarray (HxWxC, BGR)
            options: 感知选项

        Returns:
            List[DetectedText]: 识别到的文本列表

        可抛:
            ProviderError 或其子类异常 (由 Adapter 捕获)
        """
        raise NotImplementedError

    def get_info(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "type": "ocr",
            "available": self.is_available(),
        }


class DetectionProvider(abc.ABC):
    """Detection Provider 抽象基类

    子类必须实现:
        name (类属性): provider 名 (yolo / mock)
        is_available(): 库是否可用
        detect_objects(image, options) -> List[DetectedObject]
    """

    name: str = "abstract_detection_provider"

    @abc.abstractmethod
    def is_available(self) -> bool:
        raise NotImplementedError

    @abc.abstractmethod
    def detect_objects(
        self,
        image: Any,
        options: Optional[PerceptionOptions] = None,
    ) -> List[DetectedObject]:
        """执行目标检测

        Args:
            image: numpy ndarray (HxWxC, BGR)
            options: 感知选项

        Returns:
            List[DetectedObject]: 检测到的对象列表
        """
        raise NotImplementedError

    def get_info(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "type": "detection",
            "available": self.is_available(),
        }


__all__ = ["ProviderError", "OCRProvider", "DetectionProvider"]
