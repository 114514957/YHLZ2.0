"""
YHLZ Vision Memory V1.0 - 视觉记忆层数据结构

职责:
    - 定义统一视觉记忆记录 (VisualMemoryRecord)
    - 检索条件 (MemoryQuery)
    - 枚举: 记忆类型 / 重要程度 / 操作状态
    - 不依赖任何外部库 (仅 stdlib + typing)
    - 不依赖 Vision Foundation / Perception / Understanding (自包含, 便于独立测试)
    - 提供 UnderstandingResult → VisualMemoryRecord 的转换工厂方法 (import 延迟, 不硬依赖)

设计原则:
    - 不可变 (frozen dataclass)
    - 类型注解完整
    - 兼容 JSON 序列化 (to_dict / from_dict)
    - 只记忆结构化结果, 绝不保存原始图像
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

class MemoryType(str, Enum):
    """视觉记忆类型"""
    SCENE = "scene"                    # 场景记忆 (描述类理解结果)
    TEXT = "text"                      # 文字记忆 (OCR 结果)
    OBJECT = "object"                  # 对象记忆 (检测结果)
    QA = "qa"                          # 问答记忆 (视觉问答)
    COMBINED = "combined"              # 组合记忆 (感知+理解)


class MemoryImportance(str, Enum):
    """记忆重要程度"""
    LOW = "low"                        # 低
    MEDIUM = "medium"                  # 中 (默认)
    HIGH = "high"                      # 高


class MemoryStatus(str, Enum):
    """记忆操作状态"""
    OK = "ok"                          # 成功
    ERROR = "error"                    # 通用错误
    PERMISSION_DENIED = "denied"       # 权限拒绝
    NO_STORE = "no_store"              # 无可用存储
    EMPTY_INPUT = "empty_input"        # 输入为空
    NOT_FOUND = "not_found"            # 记录不存在


# ----------------------------------------------------------------------
# 顶层记录
# ----------------------------------------------------------------------

@dataclass
class VisualMemoryRecord:
    """视觉记忆记录

    字段:
        id:          记录唯一 ID
        memory_type: 记忆类型 (scene / text / object / qa / combined)
        source:      来源 (vlm / describe / qa / ocr / detection ...)
        timestamp:   记忆产生时间戳
        scene_type:  场景类型 (desktop / document / image / web / unknown ...)
        description: 记忆内容 (场景描述文本)
        subjects:    主体列表 (Dict, 兼容 UnderstandingSubject.to_dict())
        tags:        标签列表 (供检索)
        importance:  重要程度 (low / medium / high)
        confidence:  置信度 (0.0 ~ 1.0)
        metadata:    额外元数据
        created_at:  入库时间
        updated_at:  最后更新时间
    """
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    memory_type: str = MemoryType.SCENE.value
    source: str = "vlm"
    timestamp: float = field(default_factory=time.time)
    scene_type: str = "unknown"
    description: str = ""
    subjects: List[Dict[str, Any]] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    importance: str = MemoryImportance.MEDIUM.value
    confidence: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    # ── 序列化 ──────────────────────────────────────────────────
    def to_dict(self) -> Dict[str, Any]:
        """转 dict"""
        return {
            "id": self.id,
            "memory_type": self.memory_type,
            "source": self.source,
            "timestamp": self.timestamp,
            "scene_type": self.scene_type,
            "description": self.description,
            "subjects": self.subjects,
            "tags": self.tags,
            "importance": self.importance,
            "confidence": round(self.confidence, 4),
            "metadata": self.metadata,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "VisualMemoryRecord":
        """从 dict 构造"""
        now = time.time()
        return cls(
            id=d.get("id", uuid.uuid4().hex),
            memory_type=d.get("memory_type", MemoryType.SCENE.value),
            source=d.get("source", "vlm"),
            timestamp=float(d.get("timestamp", now)),
            scene_type=d.get("scene_type", "unknown"),
            description=d.get("description", ""),
            subjects=d.get("subjects", []) or [],
            tags=d.get("tags", []) or [],
            importance=d.get("importance", MemoryImportance.MEDIUM.value),
            confidence=float(d.get("confidence", 0.0)),
            metadata=d.get("metadata", {}) or {},
            created_at=float(d.get("created_at", now)),
            updated_at=float(d.get("updated_at", now)),
        )

    # ── 工厂方法 ──────────────────────────────────────────────────
    @classmethod
    def create(
        cls,
        description: str,
        memory_type: str = MemoryType.SCENE.value,
        source: str = "vlm",
        scene_type: str = "unknown",
        subjects: Optional[List[Dict[str, Any]]] = None,
        tags: Optional[List[str]] = None,
        importance: str = MemoryImportance.MEDIUM.value,
        confidence: float = 0.0,
        metadata: Optional[Dict[str, Any]] = None,
        timestamp: Optional[float] = None,
    ) -> "VisualMemoryRecord":
        """构造记忆记录

        Args:
            timestamp: 记忆产生时间戳 (None=当前时间)
        """
        now = time.time()
        ts = timestamp if timestamp is not None else now
        return cls(
            memory_type=memory_type,
            source=source,
            timestamp=ts,
            scene_type=scene_type,
            description=description,
            subjects=subjects or [],
            tags=tags or [],
            importance=importance,
            confidence=confidence,
            metadata=metadata or {},
            created_at=now,
            updated_at=now,
        )

    @classmethod
    def from_understanding_result(
        cls,
        result: Any,
        tags: Optional[List[str]] = None,
        importance: Optional[str] = None,
        memory_type: Optional[str] = None,
    ) -> "VisualMemoryRecord":
        """从 UnderstandingResult 转换 (只取结构化字段, 不保存图像)

        Args:
            result: UnderstandingResult 实例 (成功结果)
            tags: 自定义标签 (None=自动从主体名生成)
            importance: 重要程度 (None=中)
            memory_type: 记忆类型 (None=自动推断)
        """
        if memory_type is None:
            source = str(result.source)
            request_source = str((result.metadata or {}).get("source_request", ""))
            memory_type = (
                MemoryType.QA.value
                if source == "qa" or request_source == "qa"
                else MemoryType.SCENE.value
            )
        if tags is None:
            tags = result.subject_names if hasattr(result, "subject_names") else []
        if importance is None:
            importance = MemoryImportance.MEDIUM.value
        return cls(
            memory_type=memory_type,
            source=str(result.source),
            timestamp=float(getattr(result, "timestamp", time.time())),
            scene_type=str(result.scene_type),
            description=str(result.description),
            subjects=[s.to_dict() if hasattr(s, "to_dict") else s
                      for s in (result.subjects or [])],
            tags=list(tags),
            importance=importance,
            confidence=float(getattr(result, "confidence", 0.0)),
            metadata={
                **(result.metadata or {}),
                "result_id": result.id,
                "summary": result.summary,
            },
        )


# ----------------------------------------------------------------------
# 检索条件
# ----------------------------------------------------------------------

@dataclass
class MemoryQuery:
    """视觉记忆检索条件

    Attributes:
        time_from:   时间范围起点 (None=不限)
        time_to:     时间范围终点 (None=不限)
        scene_type:  场景类型过滤 (None=不限)
        tag:         标签过滤 (匹配 tags 列表, None=不限)
        keyword:     关键词过滤 (匹配 description, None=不限)
        importance:  重要程度过滤 (low / medium / high, None=不限)
        limit:       返回数量上限
        offset:      偏移量 (分页)
    """
    time_from: Optional[float] = None
    time_to: Optional[float] = None
    scene_type: Optional[str] = None
    tag: Optional[str] = None
    keyword: Optional[str] = None
    importance: Optional[str] = None
    limit: int = 20
    offset: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "time_from": self.time_from,
            "time_to": self.time_to,
            "scene_type": self.scene_type,
            "tag": self.tag,
            "keyword": self.keyword,
            "importance": self.importance,
            "limit": self.limit,
            "offset": self.offset,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "MemoryQuery":
        def _opt(key: str) -> Optional[float]:
            v = d.get(key)
            return float(v) if v is not None else None

        return cls(
            time_from=_opt("time_from"),
            time_to=_opt("time_to"),
            scene_type=d.get("scene_type"),
            tag=d.get("tag"),
            keyword=d.get("keyword"),
            importance=d.get("importance"),
            limit=int(d.get("limit", 20)),
            offset=int(d.get("offset", 0)),
        )


__all__ = [
    "MemoryType",
    "MemoryImportance",
    "MemoryStatus",
    "VisualMemoryRecord",
    "MemoryQuery",
]
