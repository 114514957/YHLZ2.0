"""
YHLZ Vision Understanding V1.0 - 权限控制

职责:
    - 校验理解请求是否被允许
    - 管理理解权限配置 (UnderstandingPermission)
    - 支持运行时动态开关
    - 不直接调用 Adapter (仅做策略判断)

设计原则:
    - 默认拒绝 (understanding_enabled 默认 False)
    - 配置驱动 (从 config 加载, 不硬编码)
    - 可测试 (Mock PermissionChecker)
    - 线程安全 (Lock 保护配置读写)

与 Vision / Perception 权限的关系:
    - 理解层独立权限 (不依赖 Vision / Perception PermissionChecker)
    - 但视觉权限 + 理解权限必须都开启才能执行 (Service 层组合校验)
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from backend.vision.understanding.schema import UnderstandingRequest

logger = logging.getLogger(__name__)


class UnderstandingPermissionError(Exception):
    """权限校验异常"""


@dataclass
class UnderstandingPermission:
    """理解权限配置

    Attributes:
        understanding_enabled: 理解总开关 (默认 False, 隐私保护)
        allow_image_save: 是否允许保存原始图像 (默认 False)
        max_image_size: 最大图像尺寸 (像素, 超过则缩放)
        save_policy: 保存策略: memory / disk / off
    """
    understanding_enabled: bool = False
    allow_image_save: bool = False
    max_image_size: int = 1920
    save_policy: str = "memory"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "understanding_enabled": self.understanding_enabled,
            "allow_image_save": self.allow_image_save,
            "max_image_size": self.max_image_size,
            "save_policy": self.save_policy,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "UnderstandingPermission":
        return cls(
            understanding_enabled=d.get("understanding_enabled", False),
            allow_image_save=d.get("allow_image_save", False),
            max_image_size=int(d.get("max_image_size", 1920)),
            save_policy=d.get("save_policy", "memory"),
        )


class PermissionChecker:
    """理解权限校验器

    用法:
        checker = PermissionChecker()
        checker.load(understanding_enabled=True)
        allowed, reason = checker.check(request)

    校验规则:
        1. understanding_enabled 必须为 True (总开关)
        2. 输入图像不可为空
    """

    def __init__(self, permission: Optional[UnderstandingPermission] = None):
        self._lock = threading.RLock()
        self._permission: UnderstandingPermission = (
            permission or UnderstandingPermission()
        )

    @property
    def permission(self) -> UnderstandingPermission:
        with self._lock:
            return self._permission

    def load_from_permission(self, permission: UnderstandingPermission) -> None:
        """整体替换权限配置"""
        with self._lock:
            self._permission = permission
        logger.info(
            f"理解权限配置已加载: understanding={permission.understanding_enabled}, "
            f"allow_image_save={permission.allow_image_save}"
        )

    def load(self, **kwargs) -> None:
        """字段级加载权限配置"""
        with self._lock:
            self._permission = UnderstandingPermission(**kwargs)

    def update(self, **kwargs) -> UnderstandingPermission:
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
            self._permission = UnderstandingPermission()
        logger.info("理解权限已重置为默认 (全部拒绝)")

    def check(self, request: UnderstandingRequest) -> Tuple[bool, str]:
        """校验请求是否允许执行

        不抛异常, 仅返回 (allowed, reason)。

        Args:
            request: 理解请求

        Returns:
            (True, "") 允许
            (False, reason) 拒绝原因
        """
        with self._lock:
            perm = self._permission

        if not perm.understanding_enabled:
            return False, "理解总开关未开启 (understanding_enabled=False)"

        if request.image is None:
            return False, "输入图像为空"

        return True, ""

    def to_dict(self) -> Dict[str, Any]:
        with self._lock:
            return self._permission.to_dict()


__all__ = [
    "UnderstandingPermission",
    "UnderstandingPermissionError",
    "PermissionChecker",
]
