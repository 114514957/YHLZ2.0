"""
YHLZ Vision Perception V1.0 - 感知层数据结构

职责:
    - 定义统一感知结果 (PerceptionResult)
    - 子结构: DetectedObject / DetectedText
    - 请求 / 子结果 (OCRResult / DetectionResult)
    - 枚举: 感知来源 / 处理状态
    - 不依赖任何外部库 (仅 stdlib + typing)

设计原则:
    - 不可变 (frozen dataclass)
    - 类型注解完整
    - 兼容 JSON 序列化 (to_dict / from_dict)
    - 与 VisionFrame 解耦: PerceptionRequest 仅持 image + 元数据
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


# ----------------------------------------------------------------------
# 枚举
# ----------------------------------------------------------------------

class PerceptionSource(str, Enum):
    """感知来源 (与 Adapter 类型对应)"""
    OCR = "ocr"                          # 文字识别
    DETECTION = "detection"              # 目标检测
    MOCK = "mock"                        # 测试用
    COMBINED = "combined"                # OCR + Detection 联合结果


class PerceptionStatus(str, Enum):
    """感知处理状态"""
    OK = "ok"                            # 成功
    ERROR = "error"                      # 通用错误
    PERMISSION_DENIED = "denied"         # 权限拒绝
    NO_PROVIDER = "no_provider"          # 无可用 Provider
    TIMEOUT = "timeout"                  # 超时
    EMPTY_INPUT = "empty_input"          # 输入图像为空


# ----------------------------------------------------------------------
# 子结构
# ----------------------------------------------------------------------

@dataclass
class BoundingBox:
    """矩形边界框 (像素坐标)

    Attributes:
        x: 左上角 x
        y: 左上角 y
        w: 宽度
        h: 高度
    """
    x: int = 0
    y: int = 0
    w: int = 0
    h: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {"x": self.x, "y": self.y, "w": self.w, "h": self.h}

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "BoundingBox":
        return cls(
            x=int(d.get("x", 0)),
            y=int(d.get("y", 0)),
            w=int(d.get("w", 0)),
            h=int(d.get("h", 0)),
        )

    @property
    def area(self) -> int:
        """面积"""
        return self.w * self.h


@dataclass
class DetectedObject:
    """检测到的对象 (Detection 结果)

    Attributes:
        name: 对象名 (如 'person' / 'car')
        category: 类别 (如 'human' / 'vehicle')
        position: 边界框
        confidence: 置信度 (0.0 ~ 1.0)
    """
    name: str = ""
    category: str = ""
    position: BoundingBox = field(default_factory=BoundingBox)
    confidence: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "category": self.category,
            "position": self.position.to_dict(),
            "confidence": round(self.confidence, 4),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "DetectedObject":
        return cls(
            name=d.get("name", ""),
            category=d.get("category", ""),
            position=BoundingBox.from_dict(d.get("position", {})),
            confidence=float(d.get("confidence", 0.0)),
        )


@dataclass
class DetectedText:
    """检测到的文本 (OCR 结果)

    Attributes:
        content: 文本内容
        language: 语言 (如 'zh' / 'en' / 'mixed')
        confidence: 置信度 (0.0 ~ 1.0)
        position: 边界框 (可选, 文本所在区域)
    """
    content: str = ""
    language: str = "unknown"
    confidence: float = 0.0
    position: Optional[BoundingBox] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "content": self.content,
            "language": self.language,
            "confidence": round(self.confidence, 4),
            "position": self.position.to_dict() if self.position else None,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "DetectedText":
        pos = d.get("position")
        return cls(
            content=d.get("content", ""),
            language=d.get("language", "unknown"),
            confidence=float(d.get("confidence", 0.0)),
            position=BoundingBox.from_dict(pos) if pos else None,
        )


# ----------------------------------------------------------------------
# 子结果
# ----------------------------------------------------------------------

@dataclass
class OCRResult:
    """OCR 子结果

    Attributes:
        success: 是否成功
        texts: 识别到的文本列表
        processing_time_ms: 处理耗时 (毫秒)
        error: 失败原因 (success=False 时)
        provider: 执行 Provider 名
    """
    success: bool = False
    texts: List[DetectedText] = field(default_factory=list)
    processing_time_ms: float = 0.0
    error: Optional[str] = None
    provider: str = "unknown"

    @property
    def is_ok(self) -> bool:
        return self.success

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "texts": [t.to_dict() for t in self.texts],
            "processing_time_ms": round(self.processing_time_ms, 2),
            "error": self.error,
            "provider": self.provider,
            "text_count": len(self.texts),
        }


@dataclass
class DetectionResult:
    """Detection 子结果

    Attributes:
        success: 是否成功
        objects: 检测到的对象列表
        processing_time_ms: 处理耗时 (毫秒)
        error: 失败原因
        provider: 执行 Provider 名
    """
    success: bool = False
    objects: List[DetectedObject] = field(default_factory=list)
    processing_time_ms: float = 0.0
    error: Optional[str] = None
    provider: str = "unknown"

    @property
    def is_ok(self) -> bool:
        return self.success

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "objects": [o.to_dict() for o in self.objects],
            "processing_time_ms": round(self.processing_time_ms, 2),
            "error": self.error,
            "provider": self.provider,
            "object_count": len(self.objects),
        }


# ----------------------------------------------------------------------
# 顶层结果
# ----------------------------------------------------------------------

@dataclass
class PerceptionResult:
    """感知层统一结果

    字段:
        id:            结果唯一 ID
        source:        来源 (ocr / detection / mock / combined)
        timestamp:     处理时间戳
        success:       是否成功
        objects:       检测对象 (Detection 子结果, OCR 时为空)
        text:          识别文本 (OCR 子结果, Detection 时为空)
        confidence:    平均置信度 (0.0 ~ 1.0)
        metadata:      额外元数据
        processing_time: 总处理耗时 (秒)
        status:        处理状态 (ok / error / denied / ...)
        error:         失败原因
    """
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    source: str = "unknown"
    timestamp: float = field(default_factory=time.time)
    success: bool = False
    objects: List[DetectedObject] = field(default_factory=list)
    text: List[DetectedText] = field(default_factory=list)
    confidence: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    processing_time: float = 0.0
    status: str = PerceptionStatus.OK.value
    error: Optional[str] = None

    @property
    def is_ok(self) -> bool:
        """是否成功"""
        return self.success and self.status == PerceptionStatus.OK.value

    @property
    def is_error(self) -> bool:
        return not self.is_ok

    @property
    def text_content(self) -> str:
        """拼接全部文本 (用换行分隔)"""
        return "\n".join(t.content for t in self.text if t.content)

    @property
    def object_names(self) -> List[str]:
        """对象名列表"""
        return [o.name for o in self.objects]

    def to_dict(self) -> Dict[str, Any]:
        """转 dict (不含图像)"""
        return {
            "id": self.id,
            "source": self.source,
            "timestamp": self.timestamp,
            "success": self.success,
            "objects": [o.to_dict() for o in self.objects],
            "text": [t.to_dict() for t in self.text],
            "text_content": self.text_content,
            "confidence": round(self.confidence, 4),
            "metadata": self.metadata,
            "processing_time": round(self.processing_time, 4),
            "status": self.status,
            "error": self.error,
            "object_count": len(self.objects),
            "text_count": len(self.text),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "PerceptionResult":
        return cls(
            id=d.get("id", uuid.uuid4().hex),
            source=d.get("source", "unknown"),
            timestamp=d.get("timestamp", time.time()),
            success=d.get("success", False),
            objects=[DetectedObject.from_dict(o) for o in d.get("objects", [])],
            text=[DetectedText.from_dict(t) for t in d.get("text", [])],
            confidence=float(d.get("confidence", 0.0)),
            metadata=d.get("metadata", {}),
            processing_time=float(d.get("processing_time", 0.0)),
            status=d.get("status", PerceptionStatus.OK.value),
            error=d.get("error"),
        )

    # ── 工厂方法 ──────────────────────────────────────────────────
    @classmethod
    def create_ok(
        cls,
        source: str,
        objects: Optional[List[DetectedObject]] = None,
        text: Optional[List[DetectedText]] = None,
        processing_time: float = 0.0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "PerceptionResult":
        """构造成功结果

        自动计算平均置信度 (objects + text 全部置信度的均值)。
        """
        objs = objects or []
        txts = text or []
        confidences = [o.confidence for o in objs] + [t.confidence for t in txts]
        avg_conf = sum(confidences) / len(confidences) if confidences else 0.0
        return cls(
            source=source,
            status=PerceptionStatus.OK.value,
            success=True,
            objects=objs,
            text=txts,
            confidence=avg_conf,
            processing_time=processing_time,
            metadata=metadata or {},
        )

    @classmethod
    def create_error(
        cls,
        source: str,
        status: str,
        error: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "PerceptionResult":
        """构造失败结果"""
        return cls(
            source=source,
            status=status,
            error=error,
            success=False,
            metadata=metadata or {},
        )

    @classmethod
    def from_ocr(
        cls,
        ocr_result: OCRResult,
        source: str = PerceptionSource.OCR.value,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "PerceptionResult":
        """从 OCRResult 构造 PerceptionResult"""
        if not ocr_result.success:
            return cls.create_error(
                source=source,
                status=PerceptionStatus.ERROR.value,
                error=ocr_result.error or "OCR 失败",
                metadata=metadata,
            )
        return cls.create_ok(
            source=source,
            text=ocr_result.texts,
            processing_time=ocr_result.processing_time_ms / 1000.0,
            metadata={
                **(metadata or {}),
                "provider": ocr_result.provider,
            },
        )

    @classmethod
    def from_detection(
        cls,
        det_result: DetectionResult,
        source: str = PerceptionSource.DETECTION.value,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "PerceptionResult":
        """从 DetectionResult 构造 PerceptionResult"""
        if not det_result.success:
            return cls.create_error(
                source=source,
                status=PerceptionStatus.ERROR.value,
                error=det_result.error or "Detection 失败",
                metadata=metadata,
            )
        return cls.create_ok(
            source=source,
            objects=det_result.objects,
            processing_time=det_result.processing_time_ms / 1000.0,
            metadata={
                **(metadata or {}),
                "provider": det_result.provider,
            },
        )


# ----------------------------------------------------------------------
# 请求
# ----------------------------------------------------------------------

@dataclass
class PerceptionRequest:
    """感知请求参数

    Attributes:
        source: 感知来源 (ocr / detection / combined)
        image: 输入图像 (numpy ndarray, HxWxC, BGR)
        language: OCR 期望语言 (zh / en / mixed), 仅 OCR 生效
        min_confidence: 最小置信度阈值 (低于则过滤)
        max_objects: 最大返回对象数 (None=不限)
        region: 区域裁剪 {x, y, w, h} (在执行前裁剪图像)
        metadata: 附加元数据
    """
    source: str = PerceptionSource.OCR.value
    image: Any = None  # numpy.ndarray
    language: str = "zh"
    min_confidence: float = 0.0
    max_objects: Optional[int] = None
    region: Optional[Dict[str, int]] = None
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "language": self.language,
            "min_confidence": self.min_confidence,
            "max_objects": self.max_objects,
            "region": self.region,
            "metadata": self.metadata,
            "has_image": self.image is not None,
        }


__all__ = [
    "PerceptionSource",
    "PerceptionStatus",
    "BoundingBox",
    "DetectedObject",
    "DetectedText",
    "OCRResult",
    "DetectionResult",
    "PerceptionResult",
    "PerceptionRequest",
]
