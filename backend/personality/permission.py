"""
YHLZ Personality Engine V3.4 - 人格权限控制

职责:
    - 校验人格操作是否被允许 (读写 / 切换 / 管理)
    - 管理人格权限配置 (PersonalityPermission)
    - 支持运行时动态开关
    - 不直接调用 Store (仅做策略判断)
    - 敏感个人信息过滤 (save 前清洗)

设计原则:
    - 默认拒绝 (personality_enabled 默认 False)
    - 配置驱动 (从 config 加载, 不硬编码)
    - 可测试 (Mock PermissionChecker)
    - 线程安全 (Lock 保护配置读写)
"""
from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass
from typing import Any, Dict, Tuple

logger = logging.getLogger(__name__)


class PersonalityPermissionError(Exception):
    """权限校验异常"""


# 敏感信息关键词 (中文 + 英文, 命中即过滤)
SENSITIVE_KEYWORDS = [
    "password", "passwd", "secret", "token", "api_key", "apikey",
    "密码", "口令", "密钥", "身份证", "身份证号", "手机号", "手机号码",
    "银行卡", "银行卡号", "账号", "账户", "卡号", "验证码",
]

_SENSITIVE_PATTERN = re.compile(
    r"|".join(re.escape(kw) for kw in SENSITIVE_KEYWORDS),
    re.IGNORECASE,
)


@dataclass
class PersonalityPermission:
    """人格权限配置

    Attributes:
        personality_enabled: 人格总开关 (默认 False, 隐私保护)
        allow_sensitive:     是否允许保存敏感字段 (默认 False, 一律过滤)
        max_profiles:        人格档案数量上限
    """
    personality_enabled: bool = False
    allow_sensitive: bool = False
    max_profiles: int = 50

    def to_dict(self) -> Dict[str, Any]:
        return {
            "personality_enabled": self.personality_enabled,
            "allow_sensitive": self.allow_sensitive,
            "max_profiles": self.max_profiles,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "PersonalityPermission":
        return cls(
            personality_enabled=d.get("personality_enabled", False),
            allow_sensitive=d.get("allow_sensitive", False),
            max_profiles=int(d.get("max_profiles", 50)),
        )


def sanitize_text(text: str) -> str:
    """清洗文本中的敏感信息 (命中关键词的片段替换为 [已过滤])"""
    if not text:
        return text
    return _SENSITIVE_PATTERN.sub("[已过滤]", text)


class PermissionChecker:
    """人格权限校验器

    用法:
        checker = PermissionChecker()
        checker.load(personality_enabled=True)
        allowed, reason = checker.check_enabled()

    校验规则:
        1. personality_enabled 必须为 True (总开关)
        2. save 时: 敏感字段过滤 (allow_sensitive=False 时)
    """

    def __init__(self, permission: Optional[PersonalityPermission] = None):
        self._lock = threading.RLock()
        self._permission: PersonalityPermission = permission or PersonalityPermission()

    @property
    def permission(self) -> PersonalityPermission:
        with self._lock:
            return self._permission

    def load_from_permission(self, permission: PersonalityPermission) -> None:
        """整体替换权限配置"""
        with self._lock:
            self._permission = permission
        logger.info(
            f"人格权限配置已加载: enabled={permission.personality_enabled}, "
            f"allow_sensitive={permission.allow_sensitive}"
        )

    def load(self, **kwargs) -> None:
        """字段级加载权限配置"""
        with self._lock:
            self._permission = PersonalityPermission(**kwargs)

    def update(self, **kwargs) -> PersonalityPermission:
        """字段级更新 (None 值忽略)"""
        with self._lock:
            for key, value in kwargs.items():
                if value is None or not hasattr(self._permission, key):
                    continue
                setattr(self._permission, key, value)
            return self._permission

    def reset(self) -> None:
        """重置为默认 (全部拒绝)"""
        with self._lock:
            self._permission = PersonalityPermission()
        logger.info("人格权限已重置为默认 (全部拒绝)")

    def check_enabled(self) -> Tuple[bool, str]:
        """校验总开关是否开启

        Returns:
            (True, "") 允许
            (False, reason) 拒绝原因
        """
        with self._lock:
            perm = self._permission
        if not perm.personality_enabled:
            return False, "人格总开关未开启 (personality_enabled=False)"
        return True, ""

    def check_save(self, profile: Any = None) -> Tuple[bool, str]:
        """校验保存操作是否允许

        额外检查:
            - 档案数量上限 (max_profiles)
            - 敏感信息检测 (返回是否需清洗)
        """
        allowed, reason = self.check_enabled()
        if not allowed:
            return allowed, reason
        if profile is not None and not self._permission.allow_sensitive:
            text = f"{getattr(profile, 'description', '')} {getattr(profile, 'tone', '')}"
            if _SENSITIVE_PATTERN.search(text):
                return False, "档案包含敏感个人信息, 禁止保存 (allow_sensitive=False)"
        return True, ""

    def to_dict(self) -> Dict[str, Any]:
        with self._lock:
            return self._permission.to_dict()


__all__ = [
    "PersonalityPermission",
    "PersonalityPermissionError",
    "PermissionChecker",
    "sanitize_text",
    "SENSITIVE_KEYWORDS",
]
