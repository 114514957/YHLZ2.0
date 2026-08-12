"""
YHLZ Vision Perception V1.0 - Perception Manager

职责:
    - 管理 OCR / Detection Adapter 生命周期 (注册/注销/查询)
    - 路由感知请求到对应 Adapter
    - 不直接对外暴露 (Service 调用)
    - 提供统一感知接口

架构位置:
    Service → Manager → Adapter → Provider

设计原则:
    - 注册表模式: 多 Adapter 共存
    - 默认注册 OCR / Detection / Mock Adapter
    - 线程安全 (Lock)
    - 可重置 (测试隔离)
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List, Optional

from backend.vision.perception.adapters.detection_adapter import DetectionAdapter
from backend.vision.perception.adapters.ocr_adapter import OCRAdapter
from backend.vision.perception.interface import (
    DetectionAdapter as DetectionAdapterABC,
    OCRAdapter as OCRAdapterABC,
    PerceptionOptions,
)
from backend.vision.perception.schema import (
    DetectionResult,
    OCRResult,
    PerceptionSource,
)

logger = logging.getLogger(__name__)


class PerceptionManagerError(Exception):
    """Perception Manager 操作异常"""


class PerceptionManager:
    """感知管理器

    用法:
        mgr = PerceptionManager()
        mgr.register_defaults()
        ocr_result = mgr.recognize_ocr(image, options)
        det_result = mgr.detect(image, options)

    职责:
        - OCR / Detection Adapter 注册表
        - 路由感知请求到对应 Adapter
        - 不做权限校验 (Service 层负责)
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._ocr_adapters: Dict[str, OCRAdapterABC] = {}
        self._detection_adapters: Dict[str, DetectionAdapterABC] = {}
        self._default_registered = False

    # ── 注册管理 ──────────────────────────────────────────────────
    def register_ocr_adapter(
        self,
        name: str,
        adapter: OCRAdapterABC,
        override: bool = False,
    ) -> None:
        """注册 OCR Adapter

        Args:
            name: Adapter 名 (如 'paddleocr' / 'tesseract' / 'mock')
            adapter: OCRAdapter 实例
            override: 是否覆盖已注册的同名 Adapter
        """
        with self._lock:
            if name in self._ocr_adapters and not override:
                raise PerceptionManagerError(
                    f"OCR Adapter {name} 已注册, override=False"
                )
            self._ocr_adapters[name] = adapter
            logger.info(f"已注册 OCR Adapter: name={name} class={adapter.__class__.__name__}")

    def register_detection_adapter(
        self,
        name: str,
        adapter: DetectionAdapterABC,
        override: bool = False,
    ) -> None:
        """注册 Detection Adapter"""
        with self._lock:
            if name in self._detection_adapters and not override:
                raise PerceptionManagerError(
                    f"Detection Adapter {name} 已注册, override=False"
                )
            self._detection_adapters[name] = adapter
            logger.info(
                f"已注册 Detection Adapter: name={name} class={adapter.__class__.__name__}"
            )

    def unregister_ocr_adapter(self, name: str) -> bool:
        with self._lock:
            if name in self._ocr_adapters:
                self._ocr_adapters.pop(name)
                logger.info(f"已注销 OCR Adapter: name={name}")
                return True
            return False

    def unregister_detection_adapter(self, name: str) -> bool:
        with self._lock:
            if name in self._detection_adapters:
                self._detection_adapters.pop(name)
                logger.info(f"已注销 Detection Adapter: name={name}")
                return True
            return False

    # ── 查询 ──────────────────────────────────────────────────────
    def get_ocr_adapter(self, name: str) -> Optional[OCRAdapterABC]:
        with self._lock:
            return self._ocr_adapters.get(name)

    def get_detection_adapter(self, name: str) -> Optional[DetectionAdapterABC]:
        with self._lock:
            return self._detection_adapters.get(name)

    def get_default_ocr_adapter(self) -> Optional[OCRAdapterABC]:
        """获取默认 OCR Adapter (第一个注册的)"""
        with self._lock:
            if not self._ocr_adapters:
                return None
            return next(iter(self._ocr_adapters.values()))

    def get_default_detection_adapter(self) -> Optional[DetectionAdapterABC]:
        with self._lock:
            if not self._detection_adapters:
                return None
            return next(iter(self._detection_adapters.values()))

    def list_ocr_adapters(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [a.get_info() for a in self._ocr_adapters.values()]

    def list_detection_adapters(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [a.get_info() for a in self._detection_adapters.values()]

    def list_ocr_names(self) -> List[str]:
        with self._lock:
            return list(self._ocr_adapters.keys())

    def list_detection_names(self) -> List[str]:
        with self._lock:
            return list(self._detection_adapters.keys())

    def has_ocr_adapter(self, name: str) -> bool:
        with self._lock:
            return name in self._ocr_adapters

    def has_detection_adapter(self, name: str) -> bool:
        with self._lock:
            return name in self._detection_adapters

    # ── 执行 ──────────────────────────────────────────────────────
    def recognize_ocr(
        self,
        image: Any,
        options: Optional[PerceptionOptions] = None,
        adapter_name: Optional[str] = None,
    ) -> OCRResult:
        """执行 OCR

        Args:
            image: numpy ndarray
            options: 感知选项
            adapter_name: 指定 Adapter (None=默认第一个)
        """
        with self._lock:
            adapter = (
                self._ocr_adapters.get(adapter_name)
                if adapter_name
                else self.get_default_ocr_adapter()
            )

        if adapter is None:
            return OCRResult(
                success=False,
                error=f"无可用 OCR Adapter (requested={adapter_name or 'default'})",
                provider="none",
            )

        try:
            return adapter.recognize(image, options)
        except Exception as e:
            logger.error(
                f"[Manager] OCR Adapter {adapter.name} 异常: {e}", exc_info=True
            )
            return OCRResult(
                success=False,
                error=f"Manager 捕获异常: {type(e).__name__}: {e}",
                provider=getattr(adapter, "name", "unknown"),
            )

    def detect(
        self,
        image: Any,
        options: Optional[PerceptionOptions] = None,
        adapter_name: Optional[str] = None,
    ) -> DetectionResult:
        """执行 Detection"""
        with self._lock:
            adapter = (
                self._detection_adapters.get(adapter_name)
                if adapter_name
                else self.get_default_detection_adapter()
            )

        if adapter is None:
            return DetectionResult(
                success=False,
                error=f"无可用 Detection Adapter (requested={adapter_name or 'default'})",
                provider="none",
            )

        try:
            return adapter.detect(image, options)
        except Exception as e:
            logger.error(
                f"[Manager] Detection Adapter {adapter.name} 异常: {e}", exc_info=True
            )
            return DetectionResult(
                success=False,
                error=f"Manager 捕获异常: {type(e).__name__}: {e}",
                provider=getattr(adapter, "name", "unknown"),
            )

    # ── 默认注册 ──────────────────────────────────────────────────
    def register_defaults(
        self,
        include_mock: bool = True,
        prefer_providers: Optional[List[str]] = None,
    ) -> None:
        """注册默认 Adapter

        Args:
            include_mock: 是否包含 Mock Adapter (测试环境必需)
            prefer_providers: 偏好 Provider 顺序 (['paddleocr', 'tesseract'])
                              第一个可用的会被注册为默认
        """
        with self._lock:
            if self._default_registered:
                return

            # OCR: 优先尝试 prefer_providers, 失败回退 Mock
            ocr_provider = self._select_ocr_provider(prefer_providers)
            if ocr_provider is not None:
                adapter = OCRAdapter(provider=ocr_provider)
                self._ocr_adapters["default"] = adapter
                logger.info(f"默认注册 OCRAdapter (provider={ocr_provider.name})")
            elif include_mock:
                self._ocr_adapters["mock"] = OCRAdapter()  # 默认 Mock
                logger.info("默认注册 Mock OCRAdapter")

            # Detection: 优先尝试 YOLO, 失败回退 Mock
            det_provider = self._select_detection_provider()
            if det_provider is not None:
                adapter = DetectionAdapter(provider=det_provider)
                self._detection_adapters["default"] = adapter
                logger.info(f"默认注册 DetectionAdapter (provider={det_provider.name})")
            elif include_mock:
                self._detection_adapters["mock"] = DetectionAdapter()
                logger.info("默认注册 Mock DetectionAdapter")

            self._default_registered = True

    def _select_ocr_provider(self, prefer_providers: Optional[List[str]] = None):
        """选择第一个可用的 OCR Provider (None=无可用, 由 Mock 兜底)"""
        from backend.vision.perception.providers.paddleocr_provider import PaddleOCRProvider
        from backend.vision.perception.providers.tesseract_provider import TesseractProvider

        order = prefer_providers or ["paddleocr", "tesseract"]
        for name in order:
            try:
                if name == "paddleocr":
                    p = PaddleOCRProvider()
                    if p.is_available():
                        return p
                elif name == "tesseract":
                    p = TesseractProvider()
                    if p.is_available():
                        return p
            except Exception as e:
                logger.warning(f"OCR Provider {name} 加载失败: {e}")
        return None

    def _select_detection_provider(self):
        """选择第一个可用的 Detection Provider"""
        from backend.vision.perception.providers.yolo_provider import YOLOProvider

        try:
            p = YOLOProvider()
            if p.is_available():
                return p
        except Exception as e:
            logger.warning(f"Detection Provider yolo 加载失败: {e}")
        return None

    # ── 状态 ──────────────────────────────────────────────────────
    def status(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "ocr_adapters_count": len(self._ocr_adapters),
                "detection_adapters_count": len(self._detection_adapters),
                "ocr_adapters": self.list_ocr_adapters(),
                "detection_adapters": self.list_detection_adapters(),
                "default_registered": self._default_registered,
            }

    def reset(self) -> None:
        """清空所有注册"""
        with self._lock:
            self._ocr_adapters.clear()
            self._detection_adapters.clear()
            self._default_registered = False


# ── 全局单例 ─────────────────────────────────────────────────────
_global_manager: Optional[PerceptionManager] = None
_manager_lock = threading.Lock()


def get_manager() -> PerceptionManager:
    """获取全局 PerceptionManager 单例"""
    global _global_manager
    with _manager_lock:
        if _global_manager is None:
            _global_manager = PerceptionManager()
            _global_manager.register_defaults(include_mock=True)
        return _global_manager


def reset_manager() -> None:
    """重置全局 Manager (测试用)"""
    global _global_manager
    with _manager_lock:
        if _global_manager is not None:
            _global_manager.reset()
        _global_manager = None


__all__ = [
    "PerceptionManager",
    "PerceptionManagerError",
    "get_manager",
    "reset_manager",
]
