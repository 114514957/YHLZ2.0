"""
YHLZ Vision Action V1.0 - 行动权限控制

职责:
    - 行动风险评估 (规则驱动: 关键词 → 风险等级)
    - 权限判定 (ActionPermission: allowed / require_confirm / risk_level / reason)
    - 高风险行动必须确认 (require_confirm)
    - 默认拒绝 (action_enabled=False)

设计原则:
    - 默认安全: 任何真实动作必须授权
    - 配置驱动: 从 config 加载 (action_enabled / require_confirm_high_risk)
    - 规则可测试: 风险关键词静态表
    - 不直接调用 Executor (仅做策略判断)
"""
from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from backend.action.schema import ActionRequest, RiskLevel

logger = logging.getLogger(__name__)


class ActionPermissionError(Exception):
    """行动权限校验异常"""


# 高风险关键词 (命中即判定为高风险行动)
HIGH_RISK_KEYWORDS = [
    "delete", "remove", "format", "wipe", "shutdown", "reboot", "restart",
    "reset", "clear", "send", "transfer", "pay", "payment", "refund", "uninstall",
    "删除", "移除", "格式化", "清空", "关机", "重启", "重置", "发送", "转账",
    "支付", "退款", "卸载", "注销",
]

# 中风险关键词 (未命中高风险时命中即判定为中风险)
MEDIUM_RISK_KEYWORDS = [
    "config", "configuration", "system", "account", "install", "update",
    "download", "import", "export", "modify", "overwrite",
    "配置", "系统", "账户", "安装", "更新", "下载", "导入", "导出", "修改", "覆盖",
]


@dataclass
class ActionPermission:
    """行动权限判定结果

    Attributes:
        allowed:         是否允许执行
        require_confirm: 是否需要用户确认 (高风险)
        risk_level:      评估后的风险等级
        reason:          判定原因
    """
    allowed: bool = False
    require_confirm: bool = False
    risk_level: str = RiskLevel.LOW.value
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "allowed": self.allowed,
            "require_confirm": self.require_confirm,
            "risk_level": self.risk_level,
            "reason": self.reason,
        }


@dataclass
class ActionPermissionConfig:
    """行动权限配置

    Attributes:
        action_enabled:            行动总开关 (默认 False, 安全优先)
        require_confirm_high_risk: 高风险行动是否需要确认 (默认 True)
    """
    action_enabled: bool = False
    require_confirm_high_risk: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action_enabled": self.action_enabled,
            "require_confirm_high_risk": self.require_confirm_high_risk,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ActionPermissionConfig":
        return cls(
            action_enabled=d.get("action_enabled", False),
            require_confirm_high_risk=d.get("require_confirm_high_risk", True),
        )


class PermissionChecker:
    """行动权限校验器

    用法:
        checker = PermissionChecker()
        checker.load(action_enabled=True)
        perm = checker.evaluate(request)
    """

    def __init__(self, config: Optional[ActionPermissionConfig] = None):
        self._lock = threading.RLock()
        self._config: ActionPermissionConfig = config or ActionPermissionConfig()

    @property
    def config(self) -> ActionPermissionConfig:
        with self._lock:
            return self._config

    def load(self, **kwargs) -> None:
        """整体加载权限配置"""
        with self._lock:
            self._config = ActionPermissionConfig(**kwargs)
        logger.info(
            f"行动权限配置已加载: enabled={self._config.action_enabled}, "
            f"require_confirm_high_risk={self._config.require_confirm_high_risk}"
        )

    def load_from_config(self, config: ActionPermissionConfig) -> None:
        with self._lock:
            self._config = config

    def update(self, **kwargs) -> ActionPermissionConfig:
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
            self._config = ActionPermissionConfig()
        logger.info("行动权限已重置为默认 (action_enabled=False)")

    def check_enabled(self) -> Tuple[bool, str]:
        """校验总开关"""
        with self._lock:
            cfg = self._config
        if not cfg.action_enabled:
            return False, "行动总开关未开启 (action_enabled=False)"
        return True, ""

    # ── 风险评估 ──────────────────────────────────────────────────
    @staticmethod
    def risk_of(request: ActionRequest) -> str:
        """规则驱动风险评估

        组合: action_type + target + parameters + reason → 文本
        命中高风险关键词 → high; 否则命中中风险 → medium; 否则 low
        声明等级 high 时直接判定 high (宁高勿低)
        """
        text_parts = [
            request.action_type,
            request.target,
            request.reason,
        ]
        try:
            text_parts.append(json.dumps(request.parameters, ensure_ascii=False))
        except (TypeError, ValueError):
            pass
        text = " ".join(text_parts).lower()

        if request.risk_level == RiskLevel.HIGH.value:
            return RiskLevel.HIGH.value
        for kw in HIGH_RISK_KEYWORDS:
            if kw.lower() in text:
                return RiskLevel.HIGH.value
        for kw in MEDIUM_RISK_KEYWORDS:
            if kw.lower() in text:
                return RiskLevel.MEDIUM.value
        return RiskLevel.LOW.value

    # ── 权限判定 ──────────────────────────────────────────────────
    def evaluate(self, request: ActionRequest) -> ActionPermission:
        """评估行动请求权限

        流程: 总开关 → 风险评估 → 确认要求
        """
        # 1. 总开关
        allowed, reason = self.check_enabled()
        if not allowed:
            return ActionPermission(allowed=False, reason=reason)

        # 2. 风险评估
        risk = self.risk_of(request)

        # 3. 高风险 → 确认要求
        if risk == RiskLevel.HIGH.value:
            require_confirm = self._config.require_confirm_high_risk
            if require_confirm:
                return ActionPermission(
                    allowed=True, require_confirm=True, risk_level=risk,
                    reason="高风险行动: 需要用户确认后执行",
                )
            return ActionPermission(
                allowed=True, require_confirm=False, risk_level=risk,
                reason="高风险行动但 require_confirm_high_risk=False, 直接放行",
            )

        return ActionPermission(
            allowed=True, require_confirm=False, risk_level=risk,
            reason=f"风险评估通过 ({risk})",
        )

    def to_dict(self) -> Dict[str, Any]:
        return self._config.to_dict()


__all__ = [
    "ActionPermission",
    "ActionPermissionConfig",
    "ActionPermissionError",
    "PermissionChecker",
    "HIGH_RISK_KEYWORDS",
    "MEDIUM_RISK_KEYWORDS",
]
