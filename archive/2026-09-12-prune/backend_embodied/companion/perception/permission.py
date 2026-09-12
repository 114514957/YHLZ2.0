"""
YHLZ Embodied AI V6.2 - 感知权限 (Perception Permission)

职责:
    - 感知权限校验 (默认拒绝)
    - 摄像头/OCR/检测必须显式授权

流程:
    请求 → check → (allowed, reason)
    - allowed=False → 拒绝 (不调用 Adapter, 短路)

设计原则:
    - 默认拒绝 (高权限感知)
    - 权限校验不抛异常 (返回布尔 + 原因)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Dict, Tuple

logger = logging.getLogger(__name__)


class PermissionError(Exception):
    """感知权限操作异常"""


class PerceptionPermission:
    """感知权限检查器

    用法:
        perm = PerceptionPermission()
        allowed, reason = perm.check(perception_type="ocr")
    """

    def __init__(
        self,
        enabled: bool = False,
        vision_enabled: bool = False,
        ocr_enabled: bool = False,
        detection_enabled: bool = False,
        permission_required: bool = True,
    ):
        self._lock = threading.RLock()
        self._enabled = bool(enabled)
        self._vision_enabled = bool(vision_enabled)
        self._ocr_enabled = bool(ocr_enabled)
        self._detection_enabled = bool(detection_enabled)
        self._permission_required = bool(permission_required)

    # ── 校验 ─────────────────────────────────────────────────────
    def check(self, perception_type: str) -> Tuple[bool, str]:
        """检查权限

        Args:
            perception_type: 感知类型 (vision/ocr/detection)

        Returns:
            (allowed, reason)
        """
        with self._lock:
            if perception_type not in ("vision", "ocr", "detection"):
                return False, f"非法感知类型: {perception_type}"
            # 总开关
            if not self._enabled:
                return False, "感知总开关关闭 (默认拒绝)"
            # 分项开关
            if perception_type == "vision" and not self._vision_enabled:
                return False, "视觉感知未授权 (默认关闭)"
            if perception_type == "ocr" and not self._ocr_enabled:
                return False, "OCR 未授权 (默认关闭)"
            if perception_type == "detection" and \
                    not self._detection_enabled:
                return False, "目标检测未授权 (默认关闭)"
            return True, "已授权"

    # ── 配置 ─────────────────────────────────────────────────────
    def update(self, **kwargs) -> Dict[str, Any]:
        """更新权限配置"""
        with self._lock:
            for key, value in kwargs.items():
                if key in ("enabled", "vision_enabled",
                           "ocr_enabled", "detection_enabled",
                           "permission_required"):
                    setattr(self, f"_{key}", bool(value))
            return self.to_dict()

    def to_dict(self) -> Dict[str, Any]:
        """权限状态"""
        with self._lock:
            return {
                "mode": "rule_based",
                "enabled": self._enabled,
                "vision_enabled": self._vision_enabled,
                "ocr_enabled": self._ocr_enabled,
                "detection_enabled": self._detection_enabled,
                "permission_required": self._permission_required,
                "default": "拒绝",
            }


__all__ = [
    "PerceptionPermission",
    "PermissionError",
]
