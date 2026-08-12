"""
YHLZ Embodied AI V8.0 - 智能调度策略 (Intelligence Policy)

职责:
    - 云端权限隔离 (云端模型不拥有最高权限)
    - 外部模型结果检查 (Identity/Core Value/Permission 禁止修改)

流程:
    Cloud Result → Validator → Constitution Check → Apply

设计原则:
    - 纯规则 (可解释)
    - 云端结果默认临时
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class IntelligencePolicyError(Exception):
    """智能调度策略操作异常"""


# 云端禁止修改字段 (可解释)
CLOUD_PROTECTED_FIELDS: list = [
    "mission", "core_value", "permission",
    "safety_rules", "base_personality",
    "使命", "价值观", "权限", "安全规则", "人格",
    "核心价值", "身份", "identity",
]

# 云端修改信号 (可解释)
CLOUD_CHANGE_SIGNALS: list = [
    "change", "modify", "update", "override", "set",
    "delete", "write", "修改", "更改", "更新", "写入",
    "覆盖",
]


class IntelligencePolicy:
    """智能调度策略 (云端隔离)

    用法:
        policy = IntelligencePolicy()
        r = policy.check_cloud(cloud_result)
    """

    def __init__(self, enabled: bool = True):
        self._lock = threading.RLock()
        self._enabled = bool(enabled)
        self._check_count = 0
        self._block_count = 0

    # ── 云端检查主入口 ───────────────────────────────────────────
    def check_cloud(
        self,
        result: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """云端结果隔离检查

        Args:
            result: 云端结果 {content/result/provider}

        Returns:
            {
                'ok', 'reason', 'matched', 'temporary',
                'mode',
            }
        """
        with self._lock:
            self._check_count += 1
            result = result or {}
            text = " ".join([
                str(result.get("content", "")),
                str(result.get("result", "")),
                str(result.get("reason", "")),
            ])
            if not self._enabled:
                return {
                    "mode": "rule_based",
                    "ok": True,
                    "reason": "智能调度策略停用",
                    "matched": [],
                    "temporary": True,
                }
            # 1. 身份字段 + 修改信号 → 阻断
            matched = []
            for signal in CLOUD_CHANGE_SIGNALS:
                if signal in text:
                    for field in CLOUD_PROTECTED_FIELDS:
                        if field in text:
                            matched.append(
                                f"{field}({signal})",
                            )
            if matched:
                self._block_count += 1
                return {
                    "mode": "rule_based",
                    "ok": False,
                    "reason": f"云端结果试图修改保护字段: "
                              f"{matched}",
                    "matched": matched,
                    "temporary": True,
                }
            # 2. 云端结果默认临时
            provider = str(result.get("provider", ""))
            temporary = bool(result.get("temporary", True))
            if provider == "cloud" and not temporary:
                self._block_count += 1
                return {
                    "mode": "rule_based",
                    "ok": False,
                    "reason": "云端结果未标记临时, 拒绝直接"
                              "应用",
                    "matched": [],
                    "temporary": False,
                }
            return {
                "mode": "rule_based",
                "ok": True,
                "reason": "云端结果隔离通过 (临时/无身份"
                          "修改)",
                "matched": [],
                "temporary": temporary,
            }

    # ── 本地检查 ─────────────────────────────────────────────────
    def check_local(
        self,
        action_text: str,
    ) -> Dict[str, Any]:
        """本地行为权限检查"""
        with self._lock:
            self._check_count += 1
            text = str(action_text or "")
            for field in CLOUD_PROTECTED_FIELDS:
                if field in text and any(
                    s in text for s in CLOUD_CHANGE_SIGNALS
                ):
                    self._block_count += 1
                    return {
                        "mode": "rule_based",
                        "ok": False,
                        "reason": f"行为涉及保护字段 '{field}'",
                        "matched": [field],
                        "temporary": True,
                    }
            return {
                "mode": "rule_based",
                "ok": True,
                "reason": "本地行为权限通过",
                "matched": [],
                "temporary": True,
            }

    # ── 查询 ─────────────────────────────────────────────────────
    def stats(self) -> Dict[str, Any]:
        """智能调度策略统计"""
        with self._lock:
            return {
                "mode": "rule_based",
                "enabled": self._enabled,
                "check_count": self._check_count,
                "block_count": self._block_count,
            }

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            self._check_count = 0
            self._block_count = 0
            return 0


__all__ = [
    "CLOUD_CHANGE_SIGNALS",
    "CLOUD_PROTECTED_FIELDS",
    "IntelligencePolicy",
    "IntelligencePolicyError",
]
