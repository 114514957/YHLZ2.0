"""
YHLZ Vision Perception V1.0 - 权限控制

职责:
    - 校验感知请求是否被允许
    - 管理感知权限配置 (PerceptionPermission)
    - 支持运行时动态开关
    - 不直接调用 Adapter (仅做策略判断)

设计原则:
    - 默认拒绝 (perception_enabled / ocr_enabled / detection_enabled 默认 False)
    - 配置驱动 (从 config 加载, 不硬编码)
    - 可测试 (Mock PermissionChecker)
    - 线程安全 (Lock 保护配置读写)

与 Vision PermissionChecker 的关系:
    - 感知层独立权限 (不依赖 Vision PermissionChecker)
    - 但视觉权限 + 感知权限必须都开启才能执行 (Service 层组合校验)
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Any, Dict, Optional

from backend.vision.perception.schema import PerceptionRequest, PerceptionSource

logger = logging.getLogger(__name__)


class PerceptionPermissionError(Exception):
    """权限校验异常"""


@dataclass
class PerceptionPermission:
    """感知权限配置

    控制感知各能力的开关。

    Attributes:
        perception_enabled: 感知总开关 (默认 False)
        ocr_enabled: OCR 开关 (默认 False)
        detection_enabled: Detection 开关 (默认 False)
        allow_image_save: 是否允许保存原始图像 (默认 False, 隐私保护)
        max_image_size: 最大图像尺寸 (像素, 超过则缩放)
        min_confidence: 全局最小置信度阈值 (低于则过滤结果)
        save_policy: 保存策略: memory / disk / off
    """
    perception_enabled: bool = False
    ocr_enabled: bool = False
    detection_enabled: bool = False
    allow_image_save: bool = False
    max_image_size: int = 1920
    min_confidence: float = 0.0
    save_policy: str = "memory"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "perception_enabled": self.perception_enabled,
            "ocr_enabled": self.ocr_enabled,
            "detection_enabled": self.detection_enabled,
            "allow_image_save": self.allow_image_save,
            "max_image_size": self.max_image_size,
            "min_confidence": self.min_confidence,
            "save_policy": self.save_policy,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "PerceptionPermission":
        return cls(
            perception_enabled=d.get("perception_enabled", False),
            ocr_enabled=d.get("ocr_enabled", False),
            detection_enabled=d.get("detection_enabled", False),
            allow_image_save=d.get("allow_image_save", False),
            max_image_size=int(d.get("max_image_size", 1920)),
            min_confidence=float(d.get("min_confidence", 0.0)),
            save_policy=d.get("save_policy", "memory"),
        )


class PermissionChecker:
    """感知权限检查器

    用法:
        checker = PermissionChecker()
        checker.load_from_dict(config_dict)
        ok, reason = checker.check(request)
        if not ok:
            return error_result

    线程安全: 内部用 Lock 保护配置读写。
    """

    def __init__(self, permission: Optional[PerceptionPermission] = None):
        self._lock = threading.RLock()
        self._permission: PerceptionPermission = permission or PerceptionPermission()

    @property
    def permission(self) -> PerceptionPermission:
        """获取当前权限配置 (副本)"""
        with self._lock:
            return PerceptionPermission(**self._permission.__dict__)

    def load_from_dict(self, d: Dict[str, Any]) -> None:
        """从 dict 加载权限配置"""
        with self._lock:
            self._permission = PerceptionPermission.from_dict(d)
        logger.info(
            f"感知权限配置已加载: perception={self._permission.perception_enabled}, "
            f"ocr={self._permission.ocr_enabled}, "
            f"detection={self._permission.detection_enabled}"
        )

    def load_from_permission(self, permission: PerceptionPermission) -> None:
        """从 PerceptionPermission 对象加载"""
        with self._lock:
            self._permission = PerceptionPermission(**permission.__dict__)
        logger.info(
            f"感知权限配置已加载: perception={permission.perception_enabled}, "
            f"ocr={permission.ocr_enabled}, detection={permission.detection_enabled}"
        )

    def update(self, **kwargs) -> PerceptionPermission:
        """更新部分权限字段, 返回更新后的配置"""
        with self._lock:
            current = self._permission.__dict__
            current.update(kwargs)
            self._permission = PerceptionPermission(**current)
            result = PerceptionPermission(**current)
        logger.info(f"感知权限已更新: {kwargs}")
        return result

    def reset(self) -> None:
        """重置为默认配置 (全部拒绝)"""
        with self._lock:
            self._permission = PerceptionPermission()
        logger.info("感知权限已重置为默认 (全部拒绝)")

    def check(self, request: PerceptionRequest) -> tuple:
        """校验感知请求

        Args:
            request: 感知请求

        Returns:
            (allowed: bool, reason: str)
            - allowed=True 表示通过
            - allowed=False 表示拒绝, reason 描述原因
        """
        with self._lock:
            perm = self._permission

        # 1. 总开关
        if not perm.perception_enabled:
            return False, "感知总开关未开启 (perception_enabled=False)"

        # 2. 来源开关
        source = request.source
        if source == PerceptionSource.OCR.value:
            if not perm.ocr_enabled:
                return False, "OCR 权限未开启 (ocr_enabled=False)"
        elif source == PerceptionSource.DETECTION.value:
            if not perm.detection_enabled:
                return False, "Detection 权限未开启 (detection_enabled=False)"
        elif source == PerceptionSource.COMBINED.value:
            # 联合感知需要 OCR + Detection 都开启
            if not perm.ocr_enabled and not perm.detection_enabled:
                return False, "联合感知需要 OCR 或 Detection 至少开启一项"
        elif source == PerceptionSource.MOCK.value:
            # Mock 模式始终允许 (测试用)
            pass
        else:
            return False, f"未知感知来源: {source}"

        # 3. 输入校验
        if request.image is None:
            return False, "输入图像为空"

        # 4. region 校验
        if request.region is not None:
            region = request.region
            if not all(k in region for k in ("x", "y", "w", "h")):
                return False, "区域参数不完整 (需含 x, y, w, h)"
            if region["w"] <= 0 or region["h"] <= 0:
                return False, "区域尺寸非法 (w/h 必须大于 0)"
            if region["w"] > perm.max_image_size or region["h"] > perm.max_image_size:
                return False, f"区域尺寸超出限制 (max {perm.max_image_size}px)"

        return True, "ok"

    def check_source(self, source: str) -> tuple:
        """校验来源是否被允许 (不检查请求细节)"""
        with self._lock:
            perm = self._permission
        if not perm.perception_enabled:
            return False, "感知总开关未开启"
        if source == PerceptionSource.OCR.value:
            return (perm.ocr_enabled, "OCR 已开启" if perm.ocr_enabled else "OCR 未开启")
        if source == PerceptionSource.DETECTION.value:
            return (perm.detection_enabled,
                    "Detection 已开启" if perm.detection_enabled else "Detection 未开启")
        if source == PerceptionSource.COMBINED.value:
            ok = perm.ocr_enabled or perm.detection_enabled
            return (ok, "联合感知可用" if ok else "OCR/Detection 均未开启")
        if source == PerceptionSource.MOCK.value:
            return True, "mock 模式"
        return False, f"未知来源: {source}"

    def to_dict(self) -> Dict[str, Any]:
        """导出权限配置"""
        with self._lock:
            return self._permission.to_dict()


__all__ = [
    "PerceptionPermission",
    "PerceptionPermissionError",
    "PermissionChecker",
]
