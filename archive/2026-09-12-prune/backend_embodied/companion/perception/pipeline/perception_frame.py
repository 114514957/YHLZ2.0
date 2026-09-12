"""
YHLZ Embodied AI V6.3 - 感知帧 (Perception Frame)

职责:
    - Agent Pipeline 感知输入单元:
      {type: "vision", content, verified: true, meaning, timestamp}
    - 校验 (结构/值域)

设计原则:
    - 帧数据可校验 (可解释)
    - 纯规则, 无黑盒
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class FrameError(Exception):
    """感知帧操作异常"""


# 帧类型白名单 (可解释)
FRAME_TYPES: list = ["vision", "audio", "text"]


class PerceptionFrame:
    """感知帧 (管道输入单元)

    用法:
        frame = PerceptionFrame.create(
            content={"kind": "ocr", "text": "任务清单"},
            meaning="用户屏幕显示任务清单",
        )
    """

    def __init__(
        self,
        frame_id: Optional[str] = None,
        ftype: str = "vision",
        content: Optional[Dict[str, Any]] = None,
        verified: bool = False,
        meaning: str = "",
        timestamp: Optional[float] = None,
    ):
        self._lock = threading.RLock()
        self.frame_id = frame_id or "pf_" + uuid.uuid4().hex[:8]
        self.type = ftype
        self.content = dict(content) if isinstance(content, dict) \
            else {}
        self.verified = bool(verified)
        self.meaning = str(meaning)
        self.timestamp = timestamp if timestamp is not None \
            else time.time()

    # ── 校验 ─────────────────────────────────────────────────────
    def validate(self) -> tuple:
        """校验帧 (可解释)"""
        with self._lock:
            if self.type not in FRAME_TYPES:
                return False, f"非法帧类型: {self.type}"
            if not isinstance(self.content, dict):
                return False, "content 必须是 dict"
            return True, "帧校验通过"

    # ── 序列化 ───────────────────────────────────────────────────
    def to_dict(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "type": self.type,
                "content": dict(self.content),
                "verified": self.verified,
                "meaning": self.meaning,
                "timestamp": self.timestamp,
            }

    @classmethod
    def create(cls, content: Dict[str, Any],
               meaning: str = "", verified: bool = False,
               ftype: str = "vision") -> "PerceptionFrame":
        """创建帧 (校验类型)"""
        frame = cls(
            ftype=ftype, content=content,
            verified=verified, meaning=meaning,
        )
        ok, reason = frame.validate()
        if not ok:
            raise FrameError(reason)
        return frame


__all__ = [
    "FRAME_TYPES",
    "FrameError",
    "PerceptionFrame",
]
