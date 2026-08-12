"""
YHLZ Embodied AI V6.4 - 多模态经验对象 (Multimodal Experience)

职责:
    - 统一多模态经验结构:
      {id, source, modalities[], meaning, confidence, impact, provenance}
    - 支持: vision / audio / text / interaction
    - 禁止各模态记忆独立发展 (统一对象)

设计原则:
    - 单一经验对象 (多模态统一)
    - 经验必须含 Provenance (可追溯)
    - 纯规则 (无黑盒)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

from backend.embodied.companion.experience.provenance import (
    Provenance,
)

logger = logging.getLogger(__name__)


class MultimodalError(Exception):
    """多模态经验操作异常"""


# 模态白名单 (可解释)
MODALITIES: List[str] = ["vision", "audio", "text", "interaction"]

# 来源白名单 (可解释)
EXPERIENCE_SOURCES: List[str] = [
    "vision", "audio", "text", "interaction",
    "creative", "reflection", "memory_gate",
]


class MultimodalExperience:
    """多模态经验对象 (统一结构)

    用法:
        exp = MultimodalExperience.create(
            source="vision",
            modalities=["vision"],
            meaning="用户屏幕显示任务清单",
            confidence=0.9,
            impact="任务安排参考",
            provenance=prov,
        )
    """

    def __init__(
        self,
        experience_id: Optional[str] = None,
        source: str = "",
        modalities: Optional[List[str]] = None,
        meaning: str = "",
        confidence: float = 0.0,
        impact: str = "",
        provenance: Optional[Dict[str, Any]] = None,
        timestamp: Optional[float] = None,
    ):
        self._lock = threading.RLock()
        self.experience_id = experience_id or \
            "mexp_" + uuid.uuid4().hex[:8]
        self.source = str(source)
        self.modalities = list(modalities or [])
        self.meaning = str(meaning)
        self.confidence = float(confidence)
        self.impact = str(impact)
        self.provenance = dict(provenance or {})
        self.timestamp = timestamp if timestamp is not None \
            else time.time()

    # ── 校验 ─────────────────────────────────────────────────────
    def validate(self) -> tuple:
        """校验经验对象 (可解释)"""
        with self._lock:
            if self.source not in EXPERIENCE_SOURCES:
                return False, f"非法来源: {self.source}"
            if not self.modalities:
                return False, "modalities 不能为空"
            bad_mods = [
                m for m in self.modalities
                if m not in MODALITIES
            ]
            if bad_mods:
                return False, f"非法模态: {bad_mods}"
            if not (0.0 <= self.confidence <= 1.0):
                return False, (
                    f"confidence 必须在 [0,1], 当前: "
                    f"{self.confidence}"
                )
            if not self.provenance:
                return False, "经验必须包含 provenance"
            return True, "经验对象校验通过"

    # ── 序列化 ───────────────────────────────────────────────────
    def to_dict(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "id": self.experience_id,
                "source": self.source,
                "modalities": list(self.modalities),
                "meaning": self.meaning,
                "confidence": round(self.confidence, 4),
                "impact": self.impact,
                "provenance": dict(self.provenance),
                "timestamp": self.timestamp,
            }

    @classmethod
    def create(
        cls,
        source: str,
        modalities: List[str],
        meaning: str,
        confidence: float = 0.0,
        impact: str = "",
        provenance: Optional[Dict[str, Any]] = None,
    ) -> "MultimodalExperience":
        """创建并校验经验对象"""
        exp = cls(
            source=source, modalities=modalities,
            meaning=meaning, confidence=confidence,
            impact=impact, provenance=provenance,
        )
        ok, reason = exp.validate()
        if not ok:
            raise MultimodalError(reason)
        return exp


__all__ = [
    "EXPERIENCE_SOURCES",
    "MODALITIES",
    "MultimodalError",
    "MultimodalExperience",
]
