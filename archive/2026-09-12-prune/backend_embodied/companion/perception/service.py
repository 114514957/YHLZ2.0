"""
YHLZ Embodied AI V6.2 - 感知服务 (Perception Service)

职责:
    - 统一编排: 权限 → 适配器 → 验证 → 事件 → 记忆候选 → 成长
    - 流程:
      Raw Input → Perception → Verification → Meaning Extraction
      → Memory Candidate → Storage
    - 多模态输入隔离: 视觉不能直接进入人格/长期记忆/行动

安全网关:
    - 未授权 → 拒绝 (不调用 Adapter)
    - 未验证 → 不进入 Memory
    - 感知事件仅作为 Memory Candidate (经 Reflection 后才存储)

设计原则:
    - Service 是唯一对外 API 入口
    - 权限校验短路 (不调用 Adapter)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

from backend.embodied.companion.perception.audit import (
    PerceptionAudit,
)
from backend.embodied.companion.perception.manager import (
    PerceptionManager,
)
from backend.embodied.companion.perception.permission import (
    PerceptionPermission,
)
from backend.embodied.companion.perception.schema import (
    DetectionResult,
    OCRResult,
    PerceptionEvent,
)
from backend.embodied.companion.perception.verification import (
    PerceptionVerifier,
)

logger = logging.getLogger(__name__)


class PerceptionServiceError(Exception):
    """感知服务操作异常"""


class PerceptionService:
    """感知服务 (权限 + 采集 + 验证 + 记忆候选编排)

    用法:
        svc = PerceptionService(manager, permission, verifier)
        frame = svc.vision_ocr()
        event = svc.perception_receive(source="camera", ...)
        ok = svc.perception_verify(event)
    """

    def __init__(
        self,
        manager: Optional[PerceptionManager] = None,
        permission: Optional[PerceptionPermission] = None,
        verifier: Optional[PerceptionVerifier] = None,
        audit: Optional[PerceptionAudit] = None,
    ):
        self._lock = threading.RLock()
        self._manager = manager or PerceptionManager()
        self._permission = permission or PerceptionPermission()
        self._verifier = verifier or PerceptionVerifier()
        self._audit = audit or PerceptionAudit()
        self._events: List[Dict[str, Any]] = []
        self._memory_candidates: List[Dict[str, Any]] = []

    # ── 视觉能力 (OCR / Detection, 经权限) ─────────────────────
    def vision_ocr(self, image: Any = None,
                   adapter_name: Optional[str] = None) -> Dict[str, Any]:
        """OCR (经权限校验, 未授权短路)"""
        with self._lock:
            allowed, reason = self._permission.check("ocr")
            if not allowed:
                self._audit.record(
                    action="permission", detail=f"OCR 拒绝: {reason}",
                )
                return {
                    "status": "PERMISSION_DENIED",
                    "reason": reason,
                    "mode": "rule_based",
                }
            frame = self._manager.ocr(image, adapter_name)
            self._audit.record(
                action="ocr", detail=frame.get("status", ""),
                ref_id=frame.get("frame_id", ""),
            )
            return frame

    def vision_detect(self, image: Any = None,
                      adapter_name: Optional[str] = None) -> Dict[str, Any]:
        """目标检测 (经权限校验, 未授权短路)"""
        with self._lock:
            allowed, reason = self._permission.check("detection")
            if not allowed:
                self._audit.record(
                    action="permission", detail=f"检测拒绝: {reason}",
                )
                return {
                    "status": "PERMISSION_DENIED",
                    "reason": reason,
                    "mode": "rule_based",
                }
            frame = self._manager.detect(image, adapter_name)
            self._audit.record(
                action="detect", detail=frame.get("status", ""),
                ref_id=frame.get("frame_id", ""),
            )
            return frame

    # ── 感知事件 (统一接收) ──────────────────────────────────────
    def perception_receive(
        self,
        source: str,
        content: Dict[str, Any],
        confidence: float = 0.0,
        ptype: str = "vision",
    ) -> Dict[str, Any]:
        """接收感知事件 (不直接进入 Memory)

        Returns:
            事件 dict (含 event_id)
        """
        with self._lock:
            try:
                event = PerceptionEvent.create(
                    source=source, content=content,
                    confidence=confidence, ptype=ptype,
                )
            except Exception as e:
                return {
                    "status": "INVALID",
                    "error": str(e),
                    "mode": "rule_based",
                }
            event_dict = event.to_dict()
            event_dict["event_id"] = event.event_id
            self._events.append(dict(event_dict))
            self._audit.record(
                action="receive", detail=source,
                ref_id=event.event_id,
            )
            return event_dict

    def perception_verify(
        self, event_id: str,
    ) -> Dict[str, Any]:
        """验证感知事件 (Verification Gateway)

        通过 → 生成 Memory Candidate (不直接存储)
        """
        with self._lock:
            event_dict = self._get_event(event_id)
            if event_dict is None:
                return {"status": "NOT_FOUND",
                        "error": f"事件不存在: {event_id}",
                        "mode": "rule_based"}
            event = PerceptionEvent(
                event_id=event_id,
                ptype=event_dict["type"],
                source=event_dict["source"],
                content=event_dict["content"],
                confidence=event_dict["confidence"],
                timestamp=event_dict["timestamp"],
            )
            ok, reason, result = self._verifier.verify(event)
            self._audit.record(
                action="verify", detail=reason,
                ref_id=event_id,
            )
            if ok:
                self._audit.record(
                    action="approve", ref_id=event_id,
                    detail="感知已验证通过",
                )
                candidate = self._to_memory_candidate(event_dict)
                self._memory_candidates.append(candidate)
                self._audit.record(
                    action="memory", ref_id=event_id,
                    detail="生成记忆候选 (经 Reflection 后存储)",
                )
                return {
                    "status": "APPROVED",
                    "approved": True,
                    "reason": reason,
                    "memory_candidate": candidate,
                    "verification": result,
                    "mode": "rule_based",
                }
            self._audit.record(
                action="reject", ref_id=event_id,
                detail=reason,
            )
            return {
                "status": "REJECTED",
                "approved": False,
                "reason": reason,
                "verification": result,
                "mode": "rule_based",
            }

    # ── 记忆候选 (隔离网关) ──────────────────────────────────────
    def _to_memory_candidate(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """感知事件 → 记忆候选 (经 Verification 后)"""
        content = event.get("content", {})
        kind = content.get("kind", "unknown")
        summary = content.get("text", "") or str(content.get(
            "objects", []),
        )[:80]
        return {
            "candidate_id": "mc_" + uuid.uuid4().hex[:8],
            "source": event.get("source", "vision"),
            "event_id": event.get("event_id", ""),
            "kind": kind,
            "summary": summary[:120],
            "confidence": event.get("confidence", 0.0),
            "timestamp": time.time(),
            "status": "PENDING_REFLECTION",
        }

    def memory_candidates(self) -> Dict[str, Any]:
        """记忆候选 (只读, 未存储)"""
        with self._lock:
            return {
                "mode": "rule_based",
                "total": len(self._memory_candidates),
                "candidates": [
                    dict(c) for c in self._memory_candidates
                ],
            }

    def promote_candidate(self, candidate_id: str) -> Dict[str, Any]:
        """记忆候选 → 经历 (经 Reflection 批准后, 仅测试/内部)"""
        with self._lock:
            for c in self._memory_candidates:
                if c["candidate_id"] == candidate_id:
                    c["status"] = "PROMOTED"
                    return dict(c)
            return {"status": "NOT_FOUND",
                    "error": f"候选不存在: {candidate_id}"}

    # ── 查询 ─────────────────────────────────────────────────────
    def stats(self) -> Dict[str, Any]:
        """感知统计"""
        with self._lock:
            return {
                "mode": "rule_based",
                "event_count": len(self._events),
                "memory_candidate_count": len(self._memory_candidates),
                "verification": self._verifier.stats(),
                "permission": self._permission.to_dict(),
                "manager": self._manager.snapshot(),
            }

    def audit_report(self, limit: int = 100) -> Dict[str, Any]:
        """感知审计"""
        return self._audit.report(limit=limit)

    def _get_event(self, event_id: str) -> Optional[Dict[str, Any]]:
        """查询事件"""
        for e in self._events:
            if e.get("event_id") == event_id:
                return dict(e)
        return None

    def clear(self) -> Dict[str, Any]:
        """清空 (测试隔离)"""
        with self._lock:
            n_events = len(self._events)
            n_cands = len(self._memory_candidates)
            n_hist = self._verifier.clear()
            n_audit = self._audit.clear()
            self._events.clear()
            self._memory_candidates.clear()
            return {
                "events": n_events,
                "candidates": n_cands,
                "verification_history": n_hist,
                "audit": n_audit,
            }


__all__ = [
    "PerceptionService",
    "PerceptionServiceError",
]
