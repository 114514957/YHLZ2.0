"""
YHLZ Vision Memory V1.0 - 视觉记忆权限控制

职责:
    - 校验记忆操作是否被允许 (保存 / 查询 / 删除)
    - 管理记忆权限配置 (MemoryPermission)
    - 支持运行时动态开关
    - 不直接调用 Store (仅做策略判断)

设计原则:
    - 默认拒绝 (vision_memory_enabled 默认 False)
    - 配置驱动 (从 config 加载, 不硬编码)
    - 可测试 (Mock PermissionChecker)
    - 线程安全 (Lock 保护配置读写)
    - 只记忆结构化结果, 绝不保存原始图像 (allow_raw_image_save 默认 False)

与 Understanding / Perception 权限的关系:
    - 记忆层独立权限 (不依赖其他子模块 PermissionChecker)
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Any, Dict, Tuple

logger = logging.getLogger(__name__)


class MemoryPermissionError(Exception):
    """权限校验异常"""


@dataclass
class MemoryPermission:
    """视觉记忆权限配置

    Attributes:
        vision_memory_enabled: 视觉记忆总开关 (默认 False, 隐私保护)
        allow_raw_image_save:  是否允许保存原始图像 (默认 False, 永不保存图片)
        default_importance:    默认重要程度 (low / medium / high)
        max_query_limit:       单次查询返回上限
    """
    vision_memory_enabled: bool = False
    allow_raw_image_save: bool = False
    default_importance: str = "medium"
    max_query_limit: int = 100

    def to_dict(self) -> Dict[str, Any]:
        return {
            "vision_memory_enabled": self.vision_memory_enabled,
            "allow_raw_image_save": self.allow_raw_image_save,
            "default_importance": self.default_importance,
            "max_query_limit": self.max_query_limit,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "MemoryPermission":
        return cls(
            vision_memory_enabled=d.get("vision_memory_enabled", False),
            allow_raw_image_save=d.get("allow_raw_image_save", False),
            default_importance=d.get("default_importance", "medium"),
            max_query_limit=int(d.get("max_query_limit", 100)),
        )


class PermissionChecker:
    """视觉记忆权限校验器

    用法:
        checker = PermissionChecker()
        checker.load(vision_memory_enabled=True)
        allowed, reason = checker.check_save()

    校验规则:
        1. vision_memory_enabled 必须为 True (总开关)
        2. 保存操作禁止携带原始图像数据 (metadata 中 image 字段)
    """

    def __init__(self, permission: Optional[MemoryPermission] = None):
        self._lock = threading.RLock()
        self._permission: MemoryPermission = permission or MemoryPermission()

    @property
    def permission(self) -> MemoryPermission:
        with self._lock:
            return self._permission

    def load_from_permission(self, permission: MemoryPermission) -> None:
        """整体替换权限配置"""
        with self._lock:
            self._permission = permission
        logger.info(
            f"视觉记忆权限配置已加载: enabled={permission.vision_memory_enabled}, "
            f"allow_raw_image_save={permission.allow_raw_image_save}"
        )

    def load(self, **kwargs) -> None:
        """字段级加载权限配置"""
        with self._lock:
            self._permission = MemoryPermission(**kwargs)

    def update(self, **kwargs) -> MemoryPermission:
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
            self._permission = MemoryPermission()
        logger.info("视觉记忆权限已重置为默认 (全部拒绝)")

    def check_enabled(self) -> Tuple[bool, str]:
        """校验总开关是否开启

        Returns:
            (True, "") 允许
            (False, reason) 拒绝原因
        """
        with self._lock:
            perm = self._permission
        if not perm.vision_memory_enabled:
            return False, "视觉记忆总开关未开启 (vision_memory_enabled=False)"
        return True, ""

    def check_save(self, record: Any = None) -> Tuple[bool, str]:
        """校验保存操作是否允许

        额外检查:
            - 保存内容不得包含原始图像数据
        """
        allowed, reason = self.check_enabled()
        if not allowed:
            return allowed, reason
        if record is not None:
            metadata = getattr(record, "metadata", None) or {}
            if "image" in metadata or "raw_image" in metadata:
                return False, "禁止保存原始图像数据 (只记忆结构化结果)"
        return True, ""

    def to_dict(self) -> Dict[str, Any]:
        with self._lock:
            return self._permission.to_dict()


__all__ = [
    "MemoryPermission",
    "MemoryPermissionError",
    "PermissionChecker",
]
