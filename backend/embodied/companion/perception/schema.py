"""
YHLZ Embodied AI V6.2 - 感知数据模型 (Perception Schema)

职责:
    - 统一感知数据模型:
      PerceptionEvent {type, source, content, confidence, timestamp}
      OCRResult {type: "ocr", text, confidence}
      DetectionResult {type: "object", objects, confidence}
    - 校验 (Schema Check, 供 Verification Gateway)

设计原则:
    - 数据模型可校验 (可解释)
    - 纯规则, 无黑盒
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class SchemaError(Exception):
    """感知数据模型操作异常"""


# 感知类型白名单 (可解释)
PERCEPTION_TYPES: List[str] = ["vision", "audio", "text"]

# 感知来源白名单 (可解释)
PERCEPTION_SOURCES: List[str] = ["camera", "screen", "mic",
                                  "user_input", "mock"]

# 感知结果类型 (可解释)
PERCEPTION_KINDS: List[str] = ["ocr", "object"]


class PerceptionEvent:
    """感知事件 (统一数据模型)

    用法:
        event = PerceptionEvent.create(
            source="camera", content={"kind": "ocr",
                                      "text": "你好"},
            confidence=0.9,
        )
    """

    def __init__(
        self,
        event_id: Optional[str] = None,
        ptype: str = "vision",
        source: str = "mock",
        content: Optional[Dict[str, Any]] = None,
        confidence: float = 0.0,
        timestamp: Optional[float] = None,
    ):
        self._lock = threading.RLock()
        self.event_id = event_id or "pe_" + uuid.uuid4().hex[:8]
        self.type = ptype
        self.source = source
        self._content_raw = content
        self.content = dict(content) if isinstance(content, dict) \
            else {}
        self.confidence = confidence
        self.timestamp = timestamp if timestamp is not None \
            else time.time()

    # ── 校验 ─────────────────────────────────────────────────────
    def validate(self) -> tuple:
        """校验事件 (Schema Check)

        Returns:
            (ok: bool, reason: str)
        """
        with self._lock:
            if self.type not in PERCEPTION_TYPES:
                return False, f"非法感知类型: {self.type}"
            if self.source not in PERCEPTION_SOURCES:
                return False, f"非法感知来源: {self.source}"
            if not (0.0 <= self.confidence <= 1.0):
                return False, (
                    f"confidence 必须在 [0,1], 当前: "
                    f"{self.confidence}"
                )
            if not isinstance(self._content_raw, dict):
                return False, "content 必须是 dict"
            return True, "校验通过"

    # ── 序列化 ───────────────────────────────────────────────────
    def to_dict(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "type": self.type,
                "source": self.source,
                "content": dict(self.content),
                "confidence": round(self.confidence, 4),
                "timestamp": self.timestamp,
            }

    # ── 构造 ─────────────────────────────────────────────────────
    @classmethod
    def create(
        cls,
        source: str,
        content: Dict[str, Any],
        confidence: float = 0.0,
        ptype: str = "vision",
    ) -> "PerceptionEvent":
        """创建并校验感知事件"""
        event = cls(
            ptype=ptype, source=source,
            content=content, confidence=confidence,
        )
        ok, reason = event.validate()
        if not ok:
            raise SchemaError(reason)
        return event


class OCRResult:
    """OCR 结果 {type: "ocr", text, confidence}"""

    def __init__(self, text: str, confidence: float = 0.0):
        if not (0.0 <= confidence <= 1.0):
            raise SchemaError(
                f"confidence 必须在 [0,1], 当前: {confidence}"
            )
        self.text = str(text)
        self.confidence = float(confidence)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": "ocr",
            "text": self.text,
            "confidence": round(self.confidence, 4),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "OCRResult":
        return cls(
            text=d.get("text", ""),
            confidence=float(d.get("confidence", 0.0)),
        )


class DetectionResult:
    """检测结果 {type: "object", objects, confidence}"""

    def __init__(self, objects: Optional[List[Dict[str, Any]]] = None,
                 confidence: float = 0.0):
        if not (0.0 <= confidence <= 1.0):
            raise SchemaError(
                f"confidence 必须在 [0,1], 当前: {confidence}"
            )
        self.objects = list(objects or [])
        self.confidence = float(confidence)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "objects": [dict(o) for o in self.objects],
            "confidence": round(self.confidence, 4),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "DetectionResult":
        return cls(
            objects=[dict(o) for o in d.get("objects", []) or []],
            confidence=float(d.get("confidence", 0.0)),
        )


__all__ = [
    "DetectionResult",
    "OCRResult",
    "PERCEPTION_KINDS",
    "PERCEPTION_SOURCES",
    "PERCEPTION_TYPES",
    "PerceptionEvent",
    "SchemaError",
]
