"""
YHLZ Vision Understanding V1.0 - 理解层数据结构

职责:
    - 定义统一理解结果 (UnderstandingResult)
    - 子结构: UnderstandingSubject (主体) / SubjectPosition (位置)
    - 请求 (UnderstandingRequest)
    - 枚举: 理解来源 / 处理状态 / 场景类型
    - 不依赖任何外部库 (仅 stdlib + typing)
    - 不依赖 Vision Foundation / Perception (自包含, 便于独立测试)

设计原则:
    - 不可变 (frozen dataclass)
    - 类型注解完整
    - 兼容 JSON 序列化 (to_dict / from_dict)
    - 输入支持 numpy image / VisionFrame / PerceptionResult (在 Service 层适配)
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

class UnderstandingSource(str, Enum):
    """理解来源"""
    VLM = "vlm"                        # VLM 模型理解
    MOCK = "mock"                      # 测试用
    DESCRIBE = "describe"              # 场景描述
    QA = "qa"                          # 视觉问答
    COMBINED = "combined"              # 描述 + 问答联合


class UnderstandingStatus(str, Enum):
    """理解处理状态"""
    OK = "ok"                          # 成功
    ERROR = "error"                    # 通用错误
    PERMISSION_DENIED = "denied"       # 权限拒绝
    NO_PROVIDER = "no_provider"        # 无可用 Provider
    TIMEOUT = "timeout"                # 超时
    EMPTY_INPUT = "empty_input"        # 输入图像为空


class SceneType(str, Enum):
    """场景类型"""
    DESKTOP = "desktop"                # 桌面 / 电脑界面
    DOCUMENT = "document"              # 文档 / 文本
    IMAGE = "image"                    # 图片 / 照片
    WEB = "web"                        # 网页
    VIDEO = "video"                    # 视频画面
    GAME = "game"                      # 游戏画面
    EMPTY = "empty"                    # 空场景 / 纯色
    UNKNOWN = "unknown"                # 无法判断


# ----------------------------------------------------------------------
# 子结构
# ----------------------------------------------------------------------

@dataclass
class SubjectPosition:
    """主体位置 (像素坐标)

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
    def from_dict(cls, d: Dict[str, Any]) -> "SubjectPosition":
        return cls(
            x=int(d.get("x", 0)),
            y=int(d.get("y", 0)),
            w=int(d.get("w", 0)),
            h=int(d.get("h", 0)),
        )


@dataclass
class UnderstandingSubject:
    """理解出的主体 (场景中的人物 / 物品 / 元素)

    Attributes:
        name: 主体名 (如 'person' / 'window' / 'car')
        category: 类别 (如 'human' / 'ui' / 'vehicle')
        position: 位置 (可选)
        confidence: 置信度 (0.0 ~ 1.0)
    """
    name: str = ""
    category: str = ""
    position: Optional[SubjectPosition] = None
    confidence: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "category": self.category,
            "position": self.position.to_dict() if self.position else None,
            "confidence": round(self.confidence, 4),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "UnderstandingSubject":
        pos = d.get("position")
        return cls(
            name=d.get("name", ""),
            category=d.get("category", ""),
            position=SubjectPosition.from_dict(pos) if pos else None,
            confidence=float(d.get("confidence", 0.0)),
        )


# ----------------------------------------------------------------------
# 顶层结果
# ----------------------------------------------------------------------

@dataclass
class UnderstandingResult:
    """理解层统一结果

    字段:
        id:              结果唯一 ID
        source:          来源 (vlm / mock / describe / qa / combined)
        timestamp:       处理时间戳
        success:         是否成功
        scene_type:      场景类型 (desktop / document / image / web / unknown ...)
        description:     场景描述文本
        subjects:        主体列表
        summary:         简短摘要 (1 句)
        confidence:      平均置信度 (0.0 ~ 1.0)
        metadata:        额外元数据
        processing_time: 总处理耗时 (秒)
        status:          处理状态
        error:           失败原因
    """
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    source: str = UnderstandingSource.VLM.value
    timestamp: float = field(default_factory=time.time)
    success: bool = False
    scene_type: str = SceneType.UNKNOWN.value
    description: str = ""
    subjects: List[UnderstandingSubject] = field(default_factory=list)
    summary: str = ""
    confidence: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    processing_time: float = 0.0
    status: str = UnderstandingStatus.OK.value
    error: Optional[str] = None

    @property
    def is_ok(self) -> bool:
        """是否成功"""
        return self.success and self.status == UnderstandingStatus.OK.value

    @property
    def is_error(self) -> bool:
        return not self.is_ok

    @property
    def subject_names(self) -> List[str]:
        """主体名列表"""
        return [s.name for s in self.subjects]

    def to_dict(self) -> Dict[str, Any]:
        """转 dict"""
        return {
            "id": self.id,
            "source": self.source,
            "timestamp": self.timestamp,
            "success": self.success,
            "scene_type": self.scene_type,
            "description": self.description,
            "subjects": [s.to_dict() for s in self.subjects],
            "summary": self.summary,
            "confidence": round(self.confidence, 4),
            "metadata": self.metadata,
            "processing_time": round(self.processing_time, 4),
            "status": self.status,
            "error": self.error,
            "subject_count": len(self.subjects),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "UnderstandingResult":
        return cls(
            id=d.get("id", uuid.uuid4().hex),
            source=d.get("source", UnderstandingSource.VLM.value),
            timestamp=d.get("timestamp", time.time()),
            success=d.get("success", False),
            scene_type=d.get("scene_type", SceneType.UNKNOWN.value),
            description=d.get("description", ""),
            subjects=[UnderstandingSubject.from_dict(s) for s in d.get("subjects", [])],
            summary=d.get("summary", ""),
            confidence=float(d.get("confidence", 0.0)),
            metadata=d.get("metadata", {}),
            processing_time=float(d.get("processing_time", 0.0)),
            status=d.get("status", UnderstandingStatus.OK.value),
            error=d.get("error"),
        )

    # ── 工厂方法 ──────────────────────────────────────────────────
    @classmethod
    def create_ok(
        cls,
        source: str,
        scene_type: str,
        description: str = "",
        subjects: Optional[List[UnderstandingSubject]] = None,
        summary: str = "",
        confidence: float = 0.0,
        processing_time: float = 0.0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "UnderstandingResult":
        """构造成功结果"""
        return cls(
            source=source,
            status=UnderstandingStatus.OK.value,
            success=True,
            scene_type=scene_type,
            description=description,
            subjects=subjects or [],
            summary=summary,
            confidence=confidence,
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
    ) -> "UnderstandingResult":
        """构造失败结果"""
        return cls(
            source=source,
            status=status,
            error=error,
            success=False,
            metadata=metadata or {},
        )

    def with_processing_time(self, seconds: float) -> "UnderstandingResult":
        """设置处理耗时并返回自身 (链式调用)"""
        self.processing_time = seconds
        return self


# ----------------------------------------------------------------------
# 请求
# ----------------------------------------------------------------------

@dataclass
class UnderstandingRequest:
    """理解请求参数

    Attributes:
        source: 理解来源 (vlm / describe / qa / combined)
        image: 输入图像 (numpy ndarray, HxWxC, BGR)
        prompt: 自定义提示词 (None=使用内置模板)
        question: 视觉问答问题 (source=qa 时必填)
        language: 输出语言 (zh / en)
        max_tokens: 最大输出 token 数
        temperature: 采样温度
        region: 区域裁剪 {x, y, w, h}
        metadata: 附加元数据
    """
    source: str = UnderstandingSource.VLM.value
    image: Any = None  # numpy.ndarray
    prompt: Optional[str] = None
    question: Optional[str] = None
    language: str = "zh"
    max_tokens: int = 512
    temperature: float = 0.3
    region: Optional[Dict[str, int]] = None
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "language": self.language,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "region": self.region,
            "metadata": self.metadata,
            "has_image": self.image is not None,
            "has_question": bool(self.question),
        }


__all__ = [
    "UnderstandingSource",
    "UnderstandingStatus",
    "SceneType",
    "SubjectPosition",
    "UnderstandingSubject",
    "UnderstandingResult",
    "UnderstandingRequest",
]
