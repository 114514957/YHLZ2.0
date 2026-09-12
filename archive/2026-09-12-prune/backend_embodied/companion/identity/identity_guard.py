"""
YHLZ Embodied AI V6.5 - 身份守护 (Identity Guard)

职责:
    - 核心保护模块
    - 保护: Personality / Core Values / Mission / Safety Rules
    - 任何变化必须经过 Identity Guard

原则:
    - 核心身份不可自动修改
    - 拦截记录 (可审计)

设计原则:
    - 纯规则检查 (无黑盒)
    - 拦截可解释
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class GuardError(Exception):
    """身份守护操作异常"""


# 保护字段 (可解释)
PROTECTED_FIELDS: List[str] = [
    "mission",            # 使命
    "core_value",         # 核心价值观
    "base_personality",   # 基础人格
    "safety_rules",       # 安全规则
    "permission",         # 权限
]


class IdentityGuard:
    """身份守护器

    用法:
        guard = IdentityGuard()
        ok, reason = guard.check(change, identity_state)
    """

    def __init__(self, enabled: bool = True):
        self._lock = threading.RLock()
        self._enabled = bool(enabled)
        self._intercepts: List[Dict[str, Any]] = []
        self._approvals: List[Dict[str, Any]] = []

    # ── 检查 ─────────────────────────────────────────────────────
    def check(
        self,
        change: Dict[str, Any],
        identity_state: Optional[Dict[str, Any]] = None,
        now: Optional[float] = None,
    ) -> tuple:
        """检查变更是否安全

        Args:
            change: 变更字段 dict {field: new_value}
            identity_state: 当前身份状态

        Returns:
            (ok: bool, reason: str)
        """
        with self._lock:
            now = now if now is not None else time.time()
            if not self._enabled:
                self._intercepts.append({
                    "guard_id": "ig_" + uuid.uuid4().hex[:8],
                    "change": dict(change),
                    "ok": True,
                    "reason": "身份守护停用",
                    "timestamp": now,
                })
                return True, "身份守护停用 (不拦截)"
            identity = identity_state or {}
            # 1. 保护字段直接拒绝
            for field in change:
                if field in PROTECTED_FIELDS:
                    self._intercepts.append({
                        "guard_id": "ig_" + uuid.uuid4().hex[:8],
                        "change": dict(change),
                        "ok": False,
                        "reason": f"保护字段 '{field}' 禁止变更",
                        "timestamp": now,
                    })
                    return False, f"保护字段 '{field}' 禁止变更"
            # 2. 与现有身份值冲突
            for field, new_value in change.items():
                current = identity.get(field)
                if current is not None and current != new_value and \
                        field in ("dimensions", "communication_style"):
                    # 表现层字段允许变更 (经审批)
                    continue
            self._approvals.append({
                "guard_id": "ig_" + uuid.uuid4().hex[:8],
                "change": dict(change),
                "ok": True,
                "reason": "变更不触及保护字段",
                "timestamp": now,
            })
            return True, "变更不触及保护字段"

    # ── 查询 ─────────────────────────────────────────────────────
    def stats(self) -> Dict[str, Any]:
        """守护统计"""
        with self._lock:
            return {
                "mode": "rule_based",
                "enabled": self._enabled,
                "intercept_count": len(self._intercepts),
                "approval_count": len(self._approvals),
            }

    def intercepts(self, limit: int = 20) -> List[Dict[str, Any]]:
        """拦截记录"""
        with self._lock:
            recent = list(reversed(self._intercepts))
            if limit > 0:
                recent = recent[:limit]
            return [dict(i) for i in recent]

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = len(self._intercepts) + len(self._approvals)
            self._intercepts.clear()
            self._approvals.clear()
            return n


__all__ = [
    "PROTECTED_FIELDS",
    "GuardError",
    "IdentityGuard",
]
