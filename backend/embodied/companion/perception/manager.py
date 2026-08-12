"""
YHLZ Embodied AI V6.2 - 感知管理器 (Perception Manager)

职责:
    - 适配器注册 / 路由 / 单例
    - Adapter 异常 → 结构化错误结果 (不外抛)

设计原则:
    - Manager 不直接暴露给外部 (经 Service)
    - 适配器可替换 (注册表)
    - 异常隔离: Adapter 抛异常, Manager 捕获转错误帧
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import uuid
from typing import Any, Dict, List, Optional

from backend.embodied.companion.perception.interface import (
    PerceptionAdapter,
    PerceptionAdapterError,
)
from backend.embodied.companion.perception.schema import (
    DetectionResult,
    OCRResult,
)

logger = logging.getLogger(__name__)


class ManagerError(Exception):
    """感知管理器操作异常"""


class PerceptionManager:
    """感知管理器 (适配器注册 + 路由)

    用法:
        mgr = PerceptionManager()
        mgr.register(OCRMockAdapter(), role="ocr")
        result = mgr.ocr(adapter_name="ocr_mock")
    """

    def __init__(self, default_ocr: Optional[str] = None,
                 default_detect: Optional[str] = None):
        self._lock = threading.RLock()
        self._adapters: Dict[str, PerceptionAdapter] = {}
        self._default_ocr = default_ocr
        self._default_detect = default_detect

    # ── 注册 ─────────────────────────────────────────────────────
    def register(self, adapter: PerceptionAdapter) -> None:
        """注册适配器 (按 name)"""
        with self._lock:
            if adapter is None or not getattr(adapter, "name", ""):
                raise ManagerError("适配器无效")
            self._adapters[adapter.name] = adapter

    def unregister(self, name: str) -> bool:
        """注销适配器"""
        with self._lock:
            return self._adapters.pop(name, None) is not None

    def get(self, name: str) -> Optional[PerceptionAdapter]:
        """查询适配器"""
        with self._lock:
            return self._adapters.get(name)

    def names(self) -> List[str]:
        """适配器清单"""
        with self._lock:
            return list(self._adapters.keys())

    # ── 路由 ─────────────────────────────────────────────────────
    def _resolve(self, role: str, name: Optional[str],
                 default: Optional[str]) -> Optional[PerceptionAdapter]:
        """解析适配器: 指定名 → 默认 → 首个可用"""
        with self._lock:
            if name:
                return self._adapters.get(name)
            if default:
                return self._adapters.get(default)
            for adapter in self._adapters.values():
                if adapter.is_available():
                    return adapter
            return None

    # ── 执行 (Adapter 异常隔离) ──────────────────────────────────
    def ocr(self, image: Any = None,
            adapter_name: Optional[str] = None,
            metadata: Optional[Dict[str, Any]] = None) -> Dict:
        """执行 OCR (异常 → 错误帧)"""
        with self._lock:
            adapter = self._resolve(
                "ocr", adapter_name, self._default_ocr,
            )
            if adapter is None:
                return self._error_frame("ocr", "无可用 OCR 适配器")
            try:
                result = adapter.ocr(image, metadata)
                frame = result.to_dict()
                frame["adapter"] = adapter.name
                frame["frame_id"] = "ocr_" + uuid.uuid4().hex[:6]
                frame["status"] = "success"
                return frame
            except Exception as e:
                logger.warning(f"[Perception] OCR 失败: {e}")
                return self._error_frame("ocr", str(e))

    def detect(self, image: Any = None,
               adapter_name: Optional[str] = None,
               metadata: Optional[Dict[str, Any]] = None) -> Dict:
        """执行检测 (异常 → 错误帧)"""
        with self._lock:
            adapter = self._resolve(
                "detect", adapter_name, self._default_detect,
            )
            if adapter is None:
                return self._error_frame("detect", "无可用检测适配器")
            try:
                result = adapter.detect(image, metadata)
                frame = result.to_dict()
                frame["adapter"] = adapter.name
                frame["frame_id"] = "det_" + uuid.uuid4().hex[:6]
                frame["status"] = "success"
                return frame
            except Exception as e:
                logger.warning(f"[Perception] 检测失败: {e}")
                return self._error_frame("detect", str(e))

    @staticmethod
    def _error_frame(kind: str, error: str) -> Dict[str, Any]:
        """结构化错误帧"""
        return {
            "type": "object" if kind == "detect" else "ocr",
            "status": "error",
            "error": error,
            "frame_id": kind[:3] + "_" + uuid.uuid4().hex[:6],
        }

    # ── 查询 ─────────────────────────────────────────────────────
    def snapshot(self) -> Dict[str, Any]:
        """适配器状态快照"""
        with self._lock:
            return {
                "mode": "rule_based",
                "adapters": [
                    {"name": a.name, "source": a.source,
                     "available": a.is_available()}
                    for a in self._adapters.values()
                ],
                "default_ocr": self._default_ocr,
                "default_detect": self._default_detect,
            }

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = len(self._adapters)
            self._adapters.clear()
            return n


__all__ = [
    "ManagerError",
    "PerceptionManager",
]
