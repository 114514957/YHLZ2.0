"""
YHLZ Embodied AI V6.2 - 感知适配器接口 (Perception Interface)

职责:
    - 统一感知适配器接口 (OCR / Detection / Mock / 未来)
    - Service 不直接调用底层, 经接口间接调用
    - 异常转结构化结果, 不崩溃

接口:
    class PerceptionAdapter:
        name: str
        source: str
        def is_available() -> bool
        def ocr(image) -> OCRResult
        def detect(image) -> DetectionResult

设计原则:
    - Adapter 可替换 (注册 + 管理)
    - 不允许 Adapter 直接读写 Service/Manager 状态
    - 权限由 Service 层校验 (Adapter 不负责权限)
"""
from __future__ import annotations

import abc
from typing import Any, Dict, Optional

from backend.embodied.companion.perception.schema import (
    DetectionResult,
    OCRResult,
)


class PerceptionAdapterError(Exception):
    """感知适配器异常"""


class PerceptionAdapter(abc.ABC):
    """感知适配器抽象基类

    实现类必须:
        name (类属性): 适配器名称
        is_available(): 环境是否可用
        ocr(): 执行 OCR, 返回 OCRResult
        detect(): 执行检测, 返回 DetectionResult
    """

    name: str = "abstract"
    source: str = "mock"

    @abc.abstractmethod
    def is_available(self) -> bool:
        """环境/引擎是否可用"""
        raise NotImplementedError

    @abc.abstractmethod
    def ocr(self, image: Any = None,
            metadata: Optional[Dict[str, Any]] = None) -> OCRResult:
        """执行 OCR

        Args:
            image: 图像输入 (数组/路径/None=Mock 合成)
            metadata: 元数据

        Returns:
            OCRResult: 成功文本, 失败抛异常由 Manager 捕获
        """
        raise NotImplementedError

    @abc.abstractmethod
    def detect(self, image: Any = None,
               metadata: Optional[Dict[str, Any]] = None
               ) -> DetectionResult:
        """执行目标检测

        Returns:
            DetectionResult: 目标列表
        """
        raise NotImplementedError

    def get_info(self) -> Dict[str, Any]:
        """适配器信息"""
        return {
            "name": self.name,
            "source": self.source,
            "available": self.is_available(),
        }


__all__ = [
    "PerceptionAdapter",
    "PerceptionAdapterError",
]
