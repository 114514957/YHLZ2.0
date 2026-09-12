"""
YHLZ Embodied AI V6.5 - 变更验证器 (Change Validator)

职责:
    - 验证成长变更 (Before / Change / Reason / After / Verification)
    - 与 Identity Guard 协同: 变更必须可验证

设计原则:
    - 纯规则验证 (无黑盒)
    - 变更需含 reason (可追溯)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ValidatorError(Exception):
    """变更验证操作异常"""


class ChangeValidator:
    """变更验证器

    用法:
        validator = ChangeValidator()
        result = validator.validate(before, after, reason)
    """

    def __init__(self, max_changes: int = 50):
        if max_changes <= 0:
            raise ValidatorError(
                f"max_changes 必须 > 0, 当前: {max_changes}"
            )
        self._lock = threading.RLock()
        self._max = int(max_changes)
        self._history: List[Dict[str, Any]] = []

    # ── 验证主入口 ───────────────────────────────────────────────
    def validate(
        self,
        before: Dict[str, Any],
        after: Dict[str, Any],
        reason: str = "",
        now: Optional[float] = None,
    ) -> Dict[str, Any]:
        """验证变更

        Args:
            before: 变更前状态
            after: 变更后状态
            reason: 变更原因 (必填)

        Returns:
            {
                'validation_id', 'ok', 'reason',
                'changed_fields': [...], 'protected_touched':
                bool, 'mode',
            }
        """
        with self._lock:
            now = now if now is not None else time.time()
            if not reason.strip():
                return self._finish(
                    False, "变更原因不能为空", [], now,
                )
            changed = []
            protected_touched = False
            for key in set(list(before.keys()) + list(after.keys())):
                if before.get(key) != after.get(key):
                    changed.append(key)
            from backend.embodied.companion.identity.identity_guard import (
                PROTECTED_FIELDS,
            )
            protected_touched = any(
                f in changed for f in PROTECTED_FIELDS
            )
            if protected_touched:
                return self._finish(
                    False, f"变更触及保护字段: {changed}",
                    changed, now,
                )
            return self._finish(
                True, f"变更验证通过 ({len(changed)} 处变化)",
                changed, now,
            )

    def _finish(self, ok: bool, reason: str,
                changed: List[str],
                now: float) -> Dict[str, Any]:
        result = {
            "validation_id": "cv_" + uuid.uuid4().hex[:8],
            "ok": ok,
            "reason": reason,
            "changed_fields": list(changed),
            "mode": "rule_based",
            "validated_at": now,
        }
        self._history.append(result)
        if len(self._history) > self._max:
            self._history = self._history[-self._max:]
        return dict(result)

    # ── 查询 ─────────────────────────────────────────────────────
    def stats(self) -> Dict[str, Any]:
        """验证统计"""
        with self._lock:
            history = list(self._history)
        passed = sum(1 for h in history if h["ok"])
        return {
            "mode": "rule_based",
            "validation_count": len(history),
            "passed_count": passed,
            "rejected_count": len(history) - passed,
        }

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = len(self._history)
            self._history.clear()
            return n


__all__ = [
    "ChangeValidator",
    "ValidatorError",
]
