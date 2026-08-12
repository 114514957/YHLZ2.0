"""
YHLZ Embodied AI V4.0 - 具身权限控制

职责:
    - 具身动作风险评估 (规则驱动: 关键词 → 风险等级)
    - 权限判定 (EmbodiedPermission: allowed / require_confirm / risk_level / reason)
    - 高风险动作必须确认 (require_confirm)
    - 默认拒绝 (embodied_enabled=False)

设计原则:
    - 默认安全: 任何具身动作必须授权
    - 配置驱动: 从 config 加载 (embodied_enabled / require_confirm_high_risk)
    - 规则可测试: 风险关键词静态表
    - 不直接调用 Environment (仅做策略判断)
    - 动作不得绕过安全层 (Service 在调用 Environment 前必须经 PermissionChecker)
"""
from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from backend.embodied.schema import EmbodiedAction

logger = logging.getLogger(__name__)


class EmbodiedPermissionError(Exception):
    """具身权限校验异常"""


# 高风险关键词 (命中即判定为高风险动作)
HIGH_RISK_KEYWORDS = [
    "reset", "shutdown", "delete", "destroy", "wipe", "format", "drop",
    "eject", "disconnect", "override", "bypass", "escalate",
    "重置", "关机", "删除", "销毁", "格式化", "卸载", "断开", "绕过", "提权",
]

# 中风险关键词 (未命中高风险时命中即判定为中风险)
MEDIUM_RISK_KEYWORDS = [
    "move", "pick", "place", "interact", "modify", "configure", "adjust",
    "控制", "移动", "拾取", "放置", "交互", "修改", "配置", "调整",
]


@dataclass
class EmbodiedPermission:
    """具身权限判定结果

    Attributes:
        allowed:         是否允许执行
        require_confirm: 是否需要用户确认 (高风险)
        risk_level:      评估后的风险等级
        reason:          判定原因
    """
    allowed: bool = False
    require_confirm: bool = False
    risk_level: str = "low"
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "allowed": self.allowed,
            "require_confirm": self.require_confirm,
            "risk_level": self.risk_level,
            "reason": self.reason,
        }


@dataclass
class EmbodiedPermissionConfig:
    """具身权限配置

    Attributes:
        embodied_enabled:            具身总开关 (默认 False, 安全优先)
        require_confirm_high_risk:   高风险动作是否需要确认 (默认 True)
    """
    embodied_enabled: bool = False
    require_confirm_high_risk: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "embodied_enabled": self.embodied_enabled,
            "require_confirm_high_risk": self.require_confirm_high_risk,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "EmbodiedPermissionConfig":
        return cls(
            embodied_enabled=d.get("embodied_enabled", False),
            require_confirm_high_risk=d.get("require_confirm_high_risk", True),
        )


class PermissionChecker:
    """具身权限校验器

    用法:
        checker = PermissionChecker()
        checker.load(embodied_enabled=True)
        perm = checker.evaluate(action)
    """

    def __init__(self, config: Optional[EmbodiedPermissionConfig] = None):
        self._lock = threading.RLock()
        self._config: EmbodiedPermissionConfig = config or EmbodiedPermissionConfig()

    @property
    def config(self) -> EmbodiedPermissionConfig:
        with self._lock:
            return self._config

    def load(self, **kwargs) -> None:
        """整体加载权限配置"""
        with self._lock:
            self._config = EmbodiedPermissionConfig(**kwargs)
        logger.info(
            f"具身权限配置已加载: enabled={self._config.embodied_enabled}, "
            f"require_confirm_high_risk={self._config.require_confirm_high_risk}"
        )

    def load_from_config(self, config: EmbodiedPermissionConfig) -> None:
        with self._lock:
            self._config = config

    def update(self, **kwargs) -> EmbodiedPermissionConfig:
        """字段级更新 (None 忽略)"""
        with self._lock:
            for key, value in kwargs.items():
                if value is None or not hasattr(self._config, key):
                    continue
                setattr(self._config, key, value)
            return self._config

    def reset(self) -> None:
        """重置为默认 (全部拒绝)"""
        with self._lock:
            self._config = EmbodiedPermissionConfig()
        logger.info("具身权限已重置为默认 (embodied_enabled=False)")

    def check_enabled(self) -> Tuple[bool, str]:
        """校验总开关"""
        with self._lock:
            cfg = self._config
        if not cfg.embodied_enabled:
            return False, "具身总开关未开启 (embodied_enabled=False)"
        return True, ""

    # ── 风险评估 ──────────────────────────────────────────────────
    @staticmethod
    def risk_of(action: EmbodiedAction) -> str:
        """规则驱动风险评估

        组合: action_type + intent + target + parameters + reason → 文本
        命中高风险关键词 → high; 否则命中中风险 → medium; 否则 low
        声明等级 high 时直接判定 high (宁高勿低)
        """
        text_parts = [
            action.action_type,
            action.intent,
            action.target,
            action.reason,
        ]
        try:
            text_parts.append(json.dumps(action.parameters, ensure_ascii=False))
        except (TypeError, ValueError):
            pass
        text = " ".join(text_parts).lower()

        if action.risk_level == "high":
            return "high"
        for kw in HIGH_RISK_KEYWORDS:
            if kw.lower() in text:
                return "high"
        for kw in MEDIUM_RISK_KEYWORDS:
            if kw.lower() in text:
                return "medium"
        return "low"

    # ── 权限判定 ──────────────────────────────────────────────────
    def evaluate(self, action: EmbodiedAction) -> EmbodiedPermission:
        """评估具身动作权限

        流程: 总开关 → 风险评估 → 确认要求
        """
        # 1. 总开关
        allowed, reason = self.check_enabled()
        if not allowed:
            return EmbodiedPermission(allowed=False, reason=reason)

        # 2. 风险评估
        risk = self.risk_of(action)

        # 3. 高风险 → 确认要求
        if risk == "high":
            require_confirm = self._config.require_confirm_high_risk
            if require_confirm:
                return EmbodiedPermission(
                    allowed=True, require_confirm=True, risk_level=risk,
                    reason="高风险动作: 需要用户确认后执行",
                )
            return EmbodiedPermission(
                allowed=True, require_confirm=False, risk_level=risk,
                reason="高风险动作但 require_confirm_high_risk=False, 直接放行",
            )

        return EmbodiedPermission(
            allowed=True, require_confirm=False, risk_level=risk,
            reason=f"风险评估通过 ({risk})",
        )

    def to_dict(self) -> Dict[str, Any]:
        return self._config.to_dict()


__all__ = [
    "EmbodiedPermission",
    "EmbodiedPermissionConfig",
    "EmbodiedPermissionError",
    "PermissionChecker",
    "HIGH_RISK_KEYWORDS",
    "MEDIUM_RISK_KEYWORDS",
]
