"""
YHLZ Embodied AI V8.0 - 身份规则 (Identity Rules)

职责:
    - 身份不可变字段定义与校验
    - 身份修改信号检测 (中英文)
    - 外部行为不得写入身份 (Identity First)

设计原则:
    - 规则全部可解释
    - 纯规则校验 (无黑盒)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class IdentityRulesError(Exception):
    """身份规则操作异常"""


# 身份保护字段 (可解释, 中英文)
IDENTITY_PROTECTED_FIELDS: list = [
    "mission", "core_value", "base_personality",
    "safety_rules", "permission",
    "使命", "价值观", "人格", "安全规则", "权限",
]

# 身份修改信号 (可解释, 中英文)
IDENTITY_CHANGE_SIGNALS: list = [
    "修改使命", "修改价值观", "修改人格", "修改安全规则",
    "修改权限", "更改身份", "更新核心价值", "写入身份",
    "覆盖身份", "change mission", "modify personality",
    "update core_value", "override identity",
]


class IdentityRules:
    """身份规则 (Identity First 执行层)

    用法:
        rules = IdentityRules()
        r = rules.check_change({"mission": "x"}, identity)
        r = rules.check_result("修改人格", "cloud")
    """

    def __init__(self, enabled: bool = True):
        self._lock = threading.RLock()
        self._enabled = bool(enabled)
        self._check_count = 0
        self._block_count = 0

    # ── 变更校验 ─────────────────────────────────────────────────
    def check_change(
        self,
        change: Dict[str, Any],
        identity_state: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """身份字段变更校验

        Args:
            change: 拟变更字段 {field: value}
            identity_state: 当前身份状态 (冲突检测)

        Returns:
            {
                'ok', 'reason', 'blocked_fields', 'mode',
            }
        """
        with self._lock:
            self._check_count += 1
            if not self._enabled:
                return {
                    "mode": "rule_based",
                    "ok": True,
                    "reason": "身份规则停用",
                    "blocked_fields": [],
                }
            blocked = []
            for field in (change or {}):
                if field in IDENTITY_PROTECTED_FIELDS:
                    blocked.append(field)
            if blocked:
                self._block_count += 1
                return {
                    "mode": "rule_based",
                    "ok": False,
                    "reason": f"身份保护字段禁止变更: "
                              f"{blocked}",
                    "blocked_fields": blocked,
                }
            # 与现有身份冲突 (表现层字段也需审批)
            conflicts = []
            identity = identity_state or {}
            for field, new_value in (change or {}).items():
                current = identity.get(field)
                if current is not None and \
                        current != new_value and \
                        field in ("dimensions",
                                  "communication_style"):
                    conflicts.append(field)
            return {
                "mode": "rule_based",
                "ok": not conflicts,
                "reason": (
                    f"表现层字段变更需审批: {conflicts}"
                    if conflicts else
                    "身份规则通过: 无保护字段变更"
                ),
                "blocked_fields": blocked,
                "conflict_fields": conflicts,
            }

    # ── 结果校验 (外部结果不得写入身份) ─────────────────────────
    def check_result(
        self,
        result_text: str,
        source: str = "unknown",
    ) -> Dict[str, Any]:
        """外部结果身份检查

        Args:
            result_text: 结果文本 (云端/表达/成长)
            source: 来源 (cloud/expression/growth/...)

        Returns:
            {
                'ok', 'reason', 'matched_signals', 'mode',
            }
        """
        with self._lock:
            self._check_count += 1
            text = str(result_text or "")
            matched = [
                s for s in IDENTITY_CHANGE_SIGNALS
                if s in text
            ]
            # 字段名 + 修改意图 (英文)
            change_words = ["change", "modify", "update",
                            "override", "set", "delete",
                            "修改", "更改", "更新", "写入",
                            "覆盖"]
            for field in IDENTITY_PROTECTED_FIELDS:
                if field in text and any(
                    w in text for w in change_words
                ):
                    matched.append(field)
            if matched:
                self._block_count += 1
                return {
                    "mode": "rule_based",
                    "ok": False,
                    "reason": (
                        f"来源 '{source}' 含身份修改信号: "
                        f"{matched}"
                    ),
                    "matched_signals": matched,
                }
            return {
                "mode": "rule_based",
                "ok": True,
                "reason": f"来源 '{source}' 不涉及身份修改",
                "matched_signals": [],
            }

    # ── 查询 ─────────────────────────────────────────────────────
    def stats(self) -> Dict[str, Any]:
        """身份规则统计"""
        with self._lock:
            return {
                "mode": "rule_based",
                "enabled": self._enabled,
                "check_count": self._check_count,
                "block_count": self._block_count,
                "protected_fields": list(
                    IDENTITY_PROTECTED_FIELDS,
                ),
            }

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            self._check_count = 0
            self._block_count = 0
            return 0


__all__ = [
    "IDENTITY_CHANGE_SIGNALS",
    "IDENTITY_PROTECTED_FIELDS",
    "IdentityRules",
    "IdentityRulesError",
]
