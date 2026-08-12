"""
YHLZ Embodied AI V8.0 - 安全策略 (Safety Policy)

职责:
    - 危险行为阻断 (Safety First)
    - 风险分级 (low/medium/high)

规则 (可解释):
    - 危险关键词 → 高风险 → 阻断
    - 风险分级: 非法/伤害类 = high; 绕过/泄露类 = high;
      模糊风险 = medium; 无风险 = low
    - high 风险必须阻断; medium 需要人工确认

设计原则:
    - 纯规则 (无黑盒)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class SafetyPolicyError(Exception):
    """安全策略操作异常"""


# 高风险关键词 (可解释, 直接阻断)
HIGH_RISK_KEYWORDS: list = [
    "非法", "伤害", "攻击", "破坏系统", "绕过安全",
    "泄露", "隐私", "删除全部记忆", "关闭身份守护",
    "hack", "bypass", "steal",
]

# 中风险关键词 (可解释, 需人工确认)
MEDIUM_RISK_KEYWORDS: list = [
    "修改配置", "调整策略", "批量删除", "覆盖数据",
    "change config", "bulk delete",
]

# 风险等级 (可解释)
RISK_LEVELS: list = ["low", "medium", "high"]


class SafetyPolicy:
    """安全策略 (危险行为阻断)

    用法:
        policy = SafetyPolicy()
        r = policy.check("绕过安全检查")
    """

    def __init__(self, enabled: bool = True):
        self._lock = threading.RLock()
        self._enabled = bool(enabled)
        self._check_count = 0
        self._block_count = 0

    # ── 检查主入口 ───────────────────────────────────────────────
    def check(
        self,
        action_text: str,
    ) -> Dict[str, Any]:
        """行为安全检查

        Args:
            action_text: 行为/结果文本

        Returns:
            {
                'allowed', 'risk_level', 'reason',
                'matched', 'mode',
            }
        """
        with self._lock:
            text = str(action_text or "")
            if not self._enabled:
                return {
                    "mode": "rule_based",
                    "allowed": True,
                    "risk_level": "low",
                    "reason": "安全策略停用",
                    "matched": [],
                }
            self._check_count += 1
            high = [k for k in HIGH_RISK_KEYWORDS if k in text]
            medium = [k for k in MEDIUM_RISK_KEYWORDS
                      if k in text]
            if high:
                self._block_count += 1
                return {
                    "mode": "rule_based",
                    "allowed": False,
                    "risk_level": "high",
                    "reason": f"高风险行为阻断: {high}",
                    "matched": high,
                }
            if medium:
                return {
                    "mode": "rule_based",
                    "allowed": False,
                    "risk_level": "medium",
                    "reason": f"中风险需人工确认: {medium}",
                    "matched": medium,
                }
            return {
                "mode": "rule_based",
                "allowed": True,
                "risk_level": "low",
                "reason": "行为安全: 无风险信号",
                "matched": [],
            }

    # ── 查询 ─────────────────────────────────────────────────────
    def stats(self) -> Dict[str, Any]:
        """安全策略统计"""
        with self._lock:
            return {
                "mode": "rule_based",
                "enabled": self._enabled,
                "check_count": self._check_count,
                "block_count": self._block_count,
                "risk_levels": list(RISK_LEVELS),
            }

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            self._check_count = 0
            self._block_count = 0
            return 0


__all__ = [
    "HIGH_RISK_KEYWORDS",
    "MEDIUM_RISK_KEYWORDS",
    "RISK_LEVELS",
    "SafetyPolicy",
    "SafetyPolicyError",
]
