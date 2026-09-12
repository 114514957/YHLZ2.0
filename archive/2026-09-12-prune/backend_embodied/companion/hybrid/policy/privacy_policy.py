"""
YHLZ Embodied AI V6.8 - 隐私策略 (Privacy Policy)

职责:
    - 判定任务隐私等级
    - 高隐私 → 禁止云端 (本地铁律)

规则 (可解释):
    - privacy_level=high → cloud_allowed=False
    - 身份相关任务类型 → 隐私强制 high
    - 默认 medium → 允许云端 (受其他策略约束)

设计原则:
    - 纯规则 (无黑盒)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class PrivacyError(Exception):
    """隐私策略操作异常"""


# 身份相关任务 (可解释, 本地铁律)
IDENTITY_TASK_TYPES: list = [
    "identity_query",
    "permission_check",
    "memory_retrieval",
]

# 隐私等级 (可解释)
PRIVACY_LEVELS: list = ["high", "medium", "low"]

# 等级 → 云端允许 (可解释)
PRIVACY_CLOUD_ALLOWED: Dict[str, bool] = {
    "high": False,    # 高隐私: 禁止出本机
    "medium": True,   # 中隐私: 允许 (受其他约束)
    "low": True,      # 低隐私: 允许
}


class PrivacyPolicy:
    """隐私策略 (任务 → 云端允许判定)

    用法:
        policy = PrivacyPolicy()
        r = policy.evaluate(task_context)
    """

    def __init__(self, enabled: bool = True):
        self._lock = threading.RLock()
        self._enabled = bool(enabled)
        self._evaluate_count = 0
        self._block_count = 0

    # ── 判定主入口 ───────────────────────────────────────────────
    def evaluate(
        self,
        task_context: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """隐私评估

        Args:
            task_context: 任务上下文 (type/privacy_level)

        Returns:
            {
                'privacy_level', 'cloud_allowed', 'reason',
                'confidence', 'mode',
            }
        """
        with self._lock:
            ctx = task_context or {}
            if not self._enabled:
                return {
                    "privacy_level": "low",
                    "cloud_allowed": True,
                    "reason": "隐私策略停用",
                    "confidence": 0.5,
                    "mode": "rule_based",
                }
            ttype = str(ctx.get("type", ""))
            declared = str(ctx.get("privacy_level", "medium"))
            # 身份相关任务 → 隐私强制 high
            level = "high" if ttype in IDENTITY_TASK_TYPES else (
                declared if declared in PRIVACY_LEVELS
                else "medium"
            )
            allowed = PRIVACY_CLOUD_ALLOWED[level]
            self._evaluate_count += 1
            if not allowed:
                self._block_count += 1
            reason = (
                f"隐私等级 '{level}' 禁止云端调用"
                if not allowed else
                f"隐私等级 '{level}' 允许云端调用"
            )
            if ttype in IDENTITY_TASK_TYPES:
                reason = (
                    f"身份相关任务 '{ttype}' 强制本地, "
                    f"禁止云端"
                )
            return {
                "privacy_level": level,
                "cloud_allowed": allowed,
                "reason": reason,
                "confidence": 0.95 if level == "high" else 0.8,
                "mode": "rule_based",
            }

    # ── 查询 ─────────────────────────────────────────────────────
    def stats(self) -> Dict[str, Any]:
        """隐私策略统计"""
        with self._lock:
            return {
                "mode": "rule_based",
                "enabled": self._enabled,
                "evaluate_count": self._evaluate_count,
                "cloud_block_count": self._block_count,
                "identity_tasks": list(IDENTITY_TASK_TYPES),
            }

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            self._evaluate_count = 0
            self._block_count = 0
            return 0


__all__ = [
    "IDENTITY_TASK_TYPES",
    "PRIVACY_CLOUD_ALLOWED",
    "PRIVACY_LEVELS",
    "PrivacyError",
    "PrivacyPolicy",
]
