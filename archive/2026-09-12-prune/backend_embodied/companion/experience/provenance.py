"""
YHLZ Embodied AI V6.4 - 经验来源链 (Memory Provenance)

职责:
    - 经验来源链 (可追溯):
      {origin, source_event, verification_score,
       reflection_reason, approved_by, timestamp}
    - 任何 Experience 必须包含 Provenance

设计原则:
    - 来源透明 (经验可追溯)
    - 纯规则 (无黑盒)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ProvenanceError(Exception):
    """经验来源操作异常"""


# 批准方白名单 (可解释)
APPROVERS: List[str] = ["memory_gate", "reflection", "user", "system"]


class Provenance:
    """经验来源链

    用法:
        prov = Provenance.create(
            origin="vision",
            source_event="pe_xxx",
            verification_score=0.9,
            reflection_reason="综合评估通过",
            approved_by="memory_gate",
        )
    """

    def __init__(
        self,
        provenance_id: Optional[str] = None,
        origin: str = "",
        source_event: str = "",
        verification_score: float = 0.0,
        reflection_reason: str = "",
        approved_by: str = "memory_gate",
        timestamp: Optional[float] = None,
    ):
        self._lock = threading.RLock()
        self.provenance_id = provenance_id or \
            "prov_" + uuid.uuid4().hex[:8]
        self.origin = str(origin)
        self.source_event = str(source_event)
        self.verification_score = verification_score
        self.reflection_reason = str(reflection_reason)
        self.approved_by = str(approved_by)
        self.timestamp = timestamp if timestamp is not None \
            else time.time()

    # ── 校验 ─────────────────────────────────────────────────────
    def validate(self) -> tuple:
        """校验来源链 (可解释)"""
        with self._lock:
            if not self.origin:
                return False, "origin 不能为空"
            if not (0.0 <= self.verification_score <= 1.0):
                return False, (
                    f"verification_score 必须在 [0,1], "
                    f"当前: {self.verification_score}"
                )
            if self.approved_by not in APPROVERS:
                return False, f"非法批准方: {self.approved_by}"
            return True, "来源链校验通过"

    # ── 序列化 ───────────────────────────────────────────────────
    def to_dict(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "provenance_id": self.provenance_id,
                "origin": self.origin,
                "source_event": self.source_event,
                "verification_score": round(
                    self.verification_score, 4,
                ),
                "reflection_reason": self.reflection_reason,
                "approved_by": self.approved_by,
                "timestamp": self.timestamp,
            }

    @classmethod
    def create(
        cls,
        origin: str,
        source_event: str = "",
        verification_score: float = 0.0,
        reflection_reason: str = "",
        approved_by: str = "memory_gate",
    ) -> "Provenance":
        """创建并校验来源链"""
        prov = cls(
            origin=origin, source_event=source_event,
            verification_score=verification_score,
            reflection_reason=reflection_reason,
            approved_by=approved_by,
        )
        ok, reason = prov.validate()
        if not ok:
            raise ProvenanceError(reason)
        return prov


__all__ = [
    "APPROVERS",
    "Provenance",
    "ProvenanceError",
]
