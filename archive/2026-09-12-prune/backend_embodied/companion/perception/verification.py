"""
YHLZ Embodied AI V6.2 - 感知验证网关 (Perception Verification)

职责:
    - 所有感知必须经过验证网关
    - 流程: Schema Check → Source Check → Confidence Check →
      Approved Perception
    - 低可信输入不能进入 Memory

设计原则:
    - 验证不通过 → 拒绝 (不进入 Memory)
    - 每步校验可解释 (reason)
    - 纯规则, 无黑盒
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import uuid
from typing import Any, Dict, List

from backend.embodied.companion.perception.schema import (
    PerceptionEvent,
)

logger = logging.getLogger(__name__)


class VerificationError(Exception):
    """感知验证操作异常"""


class PerceptionVerifier:
    """感知验证网关

    用法:
        verifier = PerceptionVerifier(min_confidence=0.5)
        ok, reason, event = verifier.verify(event)
    """

    def __init__(self, min_confidence: float = 0.5,
                 trusted_sources: List[str] = None):
        if not (0.0 <= min_confidence <= 1.0):
            raise VerificationError(
                f"min_confidence 必须在 [0,1], 当前: "
                f"{min_confidence}"
            )
        self._lock = threading.RLock()
        self._min_confidence = float(min_confidence)
        self._trusted_sources = list(trusted_sources or [
            "camera", "screen", "mock",
        ])
        self._history: List[Dict[str, Any]] = []

    # ── 验证主流程 ───────────────────────────────────────────────
    def verify(
        self, event: PerceptionEvent,
    ) -> tuple:
        """验证感知事件 (Schema → Source → Confidence)

        Args:
            event: 感知事件

        Returns:
            (ok: bool, reason: str, result: dict)
        """
        with self._lock:
            steps: List[Dict[str, Any]] = []
            # 1. Schema Check
            ok, reason = event.validate()
            steps.append({"step": "schema_check", "ok": ok,
                          "reason": reason})
            if not ok:
                return self._finish(False, steps)
            # 2. Source Check
            source_ok, source_reason = self._source_check(event)
            steps.append({"step": "source_check", "ok": source_ok,
                          "reason": source_reason})
            if not source_ok:
                return self._finish(False, steps)
            # 3. Confidence Check
            conf_ok, conf_reason = self._confidence_check(event)
            steps.append({"step": "confidence_check", "ok": conf_ok,
                          "reason": conf_reason})
            if not conf_ok:
                return self._finish(False, steps)
            # 4. Approved
            steps.append({"step": "approved", "ok": True,
                          "reason": "感知已验证通过"})
            return self._finish(True, steps, event)

    def _source_check(self, event: PerceptionEvent) -> tuple:
        """来源检查: 可信来源白名单"""
        if event.source in self._trusted_sources:
            return True, f"来源可信: {event.source}"
        return False, f"来源不可信: {event.source}"

    def _confidence_check(self, event: PerceptionEvent) -> tuple:
        """置信度检查"""
        if event.confidence >= self._min_confidence:
            return True, (
                f"置信度 {event.confidence} ≥ "
                f"最低 {self._min_confidence}"
            )
        return False, (
            f"置信度 {event.confidence} < 最低 "
            f"{self._min_confidence}, 低可信输入不能进入 Memory"
        )

    def _finish(self, ok: bool, steps: List[Dict[str, Any]],
                event: PerceptionEvent = None) -> tuple:
        """完成验证 (记录历史)"""
        result = {
            "verification_id": "ver_" + uuid.uuid4().hex[:8],
            "approved": ok,
            "steps": steps,
            "event": event.to_dict() if event else None,
            "mode": "rule_based",
        }
        self._history.append(result)
        if ok:
            return True, "感知已验证通过", result
        failed = next(
            (s for s in reversed(steps) if not s["ok"]),
            steps[-1],
        )
        return False, failed["reason"], result

    # ── 查询 ─────────────────────────────────────────────────────
    def stats(self) -> Dict[str, Any]:
        """验证统计"""
        with self._lock:
            history = list(self._history)
        approved = sum(1 for h in history if h["approved"])
        return {
            "mode": "rule_based",
            "input_count": len(history),
            "approved_count": approved,
            "rejected_count": len(history) - approved,
            "min_confidence": self._min_confidence,
        }

    def history(self, limit: int = 20) -> List[Dict[str, Any]]:
        """验证历史"""
        with self._lock:
            recent = list(reversed(self._history))
            if limit > 0:
                recent = recent[:limit]
            return [dict(h) for h in recent]

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = len(self._history)
            self._history.clear()
            return n


__all__ = [
    "PerceptionVerifier",
    "VerificationError",
]
