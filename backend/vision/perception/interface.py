"""
YHLZ Vision Perception V1.0 - Adapter 抽象接口

职责:
    - 定义 OCR / Detection / 联合 Perception 三类 Adapter 接口
    - Service 不直接调用底层库, 经 Adapter 间接调用
    - 所有异常转换为错误结果, 不向外抛

接口:
    class OCRAdapter:
        name: str
        def is_available() -> bool
        def recognize(image, options) -> OCRResult

    class DetectionAdapter:
        name: str
        def is_available() -> bool
        def detect(image, options) -> DetectionResult

    class PerceptionAdapter:
        name: str
        def perceive(image, options) -> PerceptionResult

设计原则:
    1. 不修改 Agent Core / Voice 模块 / Vision Foundation
    2. Adapter 可替换: 抽象基类 + 注册
    3. 所有异常转换为错误结果, 不抛
    4. 不绑定单一 OCR / 检测库
    5. 业务代码不直接调用 Provider (经 Adapter)
"""
from __future__ import annotations

import abc
from typing import Any, Dict, Optional

from backend.vision.perception.schema import (
    DetectionResult,
    OCRResult,
    PerceptionResult,
)


# ----------------------------------------------------------------------
# 异常
# ----------------------------------------------------------------------

class PerceptionAdapterError(Exception):
    """Perception Adapter 操作异常"""


# ----------------------------------------------------------------------
# 共享 Options
# ----------------------------------------------------------------------

class PerceptionOptions:
    """感知选项 (传递给 Adapter/Provider)

    与 PerceptionRequest 字段对应, 但只携带执行参数, 不携带 image。

    Attributes:
        language: OCR 期望语言 (zh / en / mixed)
        min_confidence: 最小置信度 (低于则过滤)
        max_objects: 最大对象数 (None=不限)
        timeout: 超时秒数
        extra: 额外参数 (Provider 特定)
    """

    def __init__(
        self,
        language: str = "zh",
        min_confidence: float = 0.0,
        max_objects: Optional[int] = None,
        timeout: float = 10.0,
        extra: Optional[Dict[str, Any]] = None,
    ):
        self.language = language
        self.min_confidence = min_confidence
        self.max_objects = max_objects
        self.timeout = timeout
        self.extra: Dict[str, Any] = extra or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "language": self.language,
            "min_confidence": self.min_confidence,
            "max_objects": self.max_objects,
            "timeout": self.timeout,
            "extra": self.extra,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "PerceptionOptions":
        return cls(
            language=d.get("language", "zh"),
            min_confidence=float(d.get("min_confidence", 0.0)),
            max_objects=d.get("max_objects"),
            timeout=float(d.get("timeout", 10.0)),
            extra=d.get("extra"),
        )


# ----------------------------------------------------------------------
# OCR Adapter
# ----------------------------------------------------------------------

class OCRAdapter(abc.ABC):
    """OCR Adapter 抽象基类

    子类必须实现:
        name (类属性): 适配器名
        is_available(): 检测库/设备是否可用
        recognize(): 执行 OCR 识别, 返回 OCRResult

    约束:
        - 所有方法返回 OCRResult, 不抛异常 (内部捕获并转错误结果)
        - 不直接调用 Service/Manager 状态
        - 通过 Provider 间接调用底层库 (业务代码不直接调 Provider)
    """

    name: str = "abstract_ocr"
    source: str = "ocr"

    @abc.abstractmethod
    def is_available(self) -> bool:
        """检测 OCR 库 / 模型是否可用"""
        raise NotImplementedError

    @abc.abstractmethod
    def recognize(self, image: Any, options: Optional[PerceptionOptions] = None) -> OCRResult:
        """执行 OCR 识别

        Args:
            image: numpy ndarray (HxWxC, BGR)
            options: 感知选项

        Returns:
            OCRResult: 成功含 texts, 失败含 error
        """
        raise NotImplementedError

    def get_info(self) -> Dict[str, Any]:
        """获取 Adapter 信息"""
        return {
            "name": self.name,
            "source": self.source,
            "type": "ocr",
            "available": self.is_available(),
        }

    # ── 内部辅助 ──────────────────────────────────────────────────
    def _error_result(self, error: str, provider: str = "unknown") -> OCRResult:
        """构造错误 OCRResult"""
        return OCRResult(
            success=False,
            error=error,
            provider=provider,
        )


# ----------------------------------------------------------------------
# Detection Adapter
# ----------------------------------------------------------------------

class DetectionAdapter(abc.ABC):
    """Detection Adapter 抽象基类

    本版本建立接口, 支持未来 YOLO 等检测模型接入。
    """

    name: str = "abstract_detection"
    source: str = "detection"

    @abc.abstractmethod
    def is_available(self) -> bool:
        """检测检测库 / 模型是否可用"""
        raise NotImplementedError

    @abc.abstractmethod
    def detect(self, image: Any, options: Optional[PerceptionOptions] = None) -> DetectionResult:
        """执行目标检测

        Args:
            image: numpy ndarray (HxWxC, BGR)
            options: 感知选项

        Returns:
            DetectionResult: 成功含 objects, 失败含 error
        """
        raise NotImplementedError

    def get_info(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "source": self.source,
            "type": "detection",
            "available": self.is_available(),
        }

    def _error_result(self, error: str, provider: str = "unknown") -> DetectionResult:
        return DetectionResult(
            success=False,
            error=error,
            provider=provider,
        )


# ----------------------------------------------------------------------
# Perception Adapter (联合接口, 可同时执行 OCR + Detection)
# ----------------------------------------------------------------------

class PerceptionAdapter(abc.ABC):
    """联合感知 Adapter (OCR + Detection)

    用法:
        adapter = SomeCombinedAdapter(ocr_adapter, detection_adapter)
        result = adapter.perceive(image, options)  # 同时返回 text + objects
    """

    name: str = "abstract_perception"
    source: str = "combined"

    @abc.abstractmethod
    def is_available(self) -> bool:
        raise NotImplementedError

    @abc.abstractmethod
    def perceive(
        self,
        image: Any,
        options: Optional[PerceptionOptions] = None,
    ) -> PerceptionResult:
        """执行联合感知 (OCR + Detection)

        Args:
            image: numpy ndarray (HxWxC, BGR)
            options: 感知选项

        Returns:
            PerceptionResult: 同时含 text + objects
        """
        raise NotImplementedError

    def get_info(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "source": self.source,
            "type": "combined",
            "available": self.is_available(),
        }


__all__ = [
    "PerceptionAdapterError",
    "PerceptionOptions",
    "OCRAdapter",
    "DetectionAdapter",
    "PerceptionAdapter",
]
