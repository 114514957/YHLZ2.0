"""
YHLZ Vision Perception V1.0 - Perception Service

职责:
    - 统一对外 API (Interface 层)
    - 组合 Manager + Permission + Logger
    - 流程: 权限校验 → 感知 → 日志记录 → 返回 PerceptionResult
    - 可选组合 VisionService 提供 VisionFrame (截图后感知)

架构位置:
    Interface (FastAPI / 外部调用 / Agent Tool)
        ↓
    Service (本模块)
        ↓
    Manager → Adapter → Provider

设计原则:
    - 单一入口: 所有感知操作经 Service
    - 权限优先: 处理前先校验权限 (perception + 来源权限)
    - 日志完整: 记录开始/成功/失败/耗时/异常
    - 配置驱动: 从 config 加载权限与参数
    - 可测试: 提供完整 Mock 注入接口
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List, Optional

from backend.vision.perception.interface import PerceptionOptions
from backend.vision.perception.logger import PerceptionLogger
from backend.vision.perception.manager import (
    PerceptionManager,
    get_manager,
    reset_manager,
)
from backend.vision.perception.permission import (
    PermissionChecker,
    PerceptionPermission,
)
from backend.vision.perception.schema import (
    DetectionResult,
    OCRResult,
    PerceptionRequest,
    PerceptionResult,
    PerceptionSource,
    PerceptionStatus,
)

logger = logging.getLogger(__name__)


class PerceptionServiceError(Exception):
    """Perception Service 操作异常"""


class PerceptionService:
    """感知统一服务

    用法:
        svc = PerceptionService()
        svc.load_config(config_dict)
        result = svc.perceive(PerceptionRequest(source="ocr", image=img))

    流程:
        1. 权限校验 (PermissionChecker)
        2. 图像预处理 (region 裁剪)
        3. 调用 Manager 路由到 Adapter
        4. 日志记录
        5. 返回 PerceptionResult

    可选流程:
        - 从 VisionService 获取屏幕截图后感知 (capture_then_perceive)
    """

    def __init__(
        self,
        manager: Optional[PerceptionManager] = None,
        permission: Optional[PermissionChecker] = None,
        plog: Optional[PerceptionLogger] = None,
        vision_service: Optional[Any] = None,
    ):
        self._lock = threading.RLock()
        self._manager: PerceptionManager = manager or PerceptionManager()
        self._permission: PermissionChecker = permission or PermissionChecker()
        self._plog: PerceptionLogger = plog or PerceptionLogger()
        self._vision_service = vision_service  # 可选, 用于截图
        self._initialized = False

    # ── 依赖注入 ──────────────────────────────────────────────────
    def set_manager(self, manager: PerceptionManager) -> None:
        with self._lock:
            self._manager = manager

    def set_permission(self, permission: PermissionChecker) -> None:
        with self._lock:
            self._permission = permission

    def set_logger(self, plog: PerceptionLogger) -> None:
        with self._lock:
            self._plog = plog

    def set_vision_service(self, vision_service: Any) -> None:
        """注入 VisionService (用于截图后感知)"""
        with self._lock:
            self._vision_service = vision_service

    @property
    def manager(self) -> PerceptionManager:
        return self._manager

    @property
    def permission(self) -> PermissionChecker:
        return self._permission

    @property
    def plog(self) -> PerceptionLogger:
        return self._plog

    @property
    def vision_service(self) -> Optional[Any]:
        return self._vision_service

    # ── 配置 ──────────────────────────────────────────────────────
    def load_config(self, config: Dict[str, Any]) -> None:
        """从 dict 加载配置 (权限 + 默认注册)"""
        with self._lock:
            perm = PerceptionPermission.from_dict(config)
            self._permission.load_from_permission(perm)
            self._manager.register_defaults(include_mock=True)
            self._initialized = True
        logger.info(f"PerceptionService 配置已加载: {perm.to_dict()}")

    def load_permission(self, permission: PerceptionPermission) -> None:
        self._permission.load_from_permission(permission)

    def update_permission(self, **kwargs) -> PerceptionPermission:
        return self._permission.update(**kwargs)

    def get_permission(self) -> Dict[str, Any]:
        return self._permission.to_dict()

    def reset_permission(self) -> None:
        self._permission.reset()

    # ── 核心感知 ──────────────────────────────────────────────────
    def perceive(self, request: PerceptionRequest) -> PerceptionResult:
        """执行感知 (完整流程)

        流程:
            1. 日志记录开始
            2. 权限校验
            3. 图像预处理 (region 裁剪)
            4. 调用 Manager 路由到 Adapter
            5. 构造 PerceptionResult
            6. 日志记录成功/失败

        Args:
            request: 感知请求 (source + image + options)

        Returns:
            PerceptionResult
        """
        import time as _time

        # 1. 日志开始
        self._plog.log_start(
            source=request.source,
            adapter="unknown",
            provider="unknown",
            metadata=request.to_dict(),
        )

        start = _time.perf_counter()

        # 2. 权限校验
        allowed, reason = self._permission.check(request)
        if not allowed:
            latency = (_time.perf_counter() - start) * 1000
            result = PerceptionResult.create_error(
                source=request.source,
                status=PerceptionStatus.PERMISSION_DENIED.value,
                error=reason,
                metadata=request.to_dict(),
            )
            self._plog.log_fail(
                source=request.source,
                adapter="none",
                status=PerceptionStatus.PERMISSION_DENIED.value,
                error=reason,
                latency_ms=latency,
            )
            return result

        # 3. 图像预处理 (region 裁剪)
        image = request.image
        if request.region is not None:
            image = self._crop_region(image, request.region)

        # 4. 构造 Options
        options = PerceptionOptions(
            language=request.language,
            min_confidence=max(
                request.min_confidence,
                self._permission.permission.min_confidence,
            ),
            max_objects=request.max_objects,
        )

        # 5. 路由到对应 Adapter
        source = request.source
        if source == PerceptionSource.OCR.value or source == PerceptionSource.MOCK.value:
            sub_result = self._manager.recognize_ocr(image, options)
            result = PerceptionResult.from_ocr(
                sub_result,
                source=source if source != PerceptionSource.MOCK.value else PerceptionSource.MOCK.value,
                metadata=request.to_dict(),
            )
        elif source == PerceptionSource.DETECTION.value:
            sub_result = self._manager.detect(image, options)
            result = PerceptionResult.from_detection(
                sub_result,
                source=source,
                metadata=request.to_dict(),
            )
        elif source == PerceptionSource.COMBINED.value:
            result = self._perceive_combined(image, options, request)
        else:
            latency = (_time.perf_counter() - start) * 1000
            result = PerceptionResult.create_error(
                source=source,
                status=PerceptionStatus.ERROR.value,
                error=f"未知感知来源: {source}",
                metadata=request.to_dict(),
            )
            self._plog.log_fail(
                source=source,
                adapter="none",
                status=PerceptionStatus.ERROR.value,
                error=result.error or "",
                latency_ms=latency,
            )
            return result

        # 补全总耗时
        total_latency = (_time.perf_counter() - start) * 1000
        result.processing_time = total_latency / 1000.0
        result.metadata = {**(result.metadata or {}), **(request.metadata or {})}

        # 6. 日志记录
        if result.is_ok:
            self._plog.log_success(
                source=source,
                adapter=result.metadata.get("provider", "unknown"),
                result_id=result.id,
                latency_ms=total_latency,
                provider=result.metadata.get("provider", "unknown"),
                object_count=len(result.objects),
                text_count=len(result.text),
                confidence=result.confidence,
            )
        else:
            self._plog.log_fail(
                source=source,
                adapter="unknown",
                status=result.status,
                error=result.error or "未知错误",
                latency_ms=total_latency,
            )

        return result

    def _perceive_combined(
        self,
        image: Any,
        options: PerceptionOptions,
        request: PerceptionRequest,
    ) -> PerceptionResult:
        """执行联合感知 (OCR + Detection)"""
        import time as _time
        start = _time.perf_counter()

        ocr_result = self._manager.recognize_ocr(image, options)
        det_result = self._manager.detect(image, options)

        latency = (_time.perf_counter() - start) * 1000

        if not ocr_result.success and not det_result.success:
            return PerceptionResult.create_error(
                source=PerceptionSource.COMBINED.value,
                status=PerceptionStatus.ERROR.value,
                error=f"OCR 与 Detection 均失败: ocr={ocr_result.error}, det={det_result.error}",
                metadata=request.to_dict(),
            )

        # 合并结果
        from backend.vision.perception.schema import (
            DetectedObject,
            DetectedText,
        )
        objects: List[DetectedObject] = (
            det_result.objects if det_result.success else []
        )
        texts: List[DetectedText] = (
            ocr_result.texts if ocr_result.success else []
        )

        # 应用 max_objects
        if options.max_objects is not None:
            objects = objects[:options.max_objects]

        result = PerceptionResult.create_ok(
            source=PerceptionSource.COMBINED.value,
            objects=objects,
            text=texts,
            processing_time=latency / 1000.0,
            metadata={
                **(request.metadata or {}),
                "ocr_provider": ocr_result.provider,
                "detection_provider": det_result.provider,
                "ocr_success": ocr_result.success,
                "detection_success": det_result.success,
            },
        )
        return result

    def _crop_region(self, image: Any, region: Dict[str, int]) -> Any:
        """裁剪图像区域"""
        try:
            x, y, w, h = region["x"], region["y"], region["w"], region["h"]
            h_img, w_img = image.shape[:2]
            x = max(0, min(x, w_img - 1))
            y = max(0, min(y, h_img - 1))
            x2 = min(x + w, w_img)
            y2 = min(y + h, h_img)
            return image[y:y2, x:x2]
        except Exception as e:
            logger.warning(f"区域裁剪失败, 返回原图: {e}")
            return image

    # ── 快捷方法 ──────────────────────────────────────────────────
    def recognize_ocr(
        self,
        image: Any,
        language: str = "zh",
        min_confidence: float = 0.0,
        region: Optional[Dict[str, int]] = None,
    ) -> PerceptionResult:
        """快捷 OCR 识别"""
        req = PerceptionRequest(
            source=PerceptionSource.OCR.value,
            image=image,
            language=language,
            min_confidence=min_confidence,
            region=region,
        )
        return self.perceive(req)

    def detect_objects(
        self,
        image: Any,
        min_confidence: float = 0.0,
        max_objects: Optional[int] = None,
        region: Optional[Dict[str, int]] = None,
    ) -> PerceptionResult:
        """快捷目标检测"""
        req = PerceptionRequest(
            source=PerceptionSource.DETECTION.value,
            image=image,
            min_confidence=min_confidence,
            max_objects=max_objects,
            region=region,
        )
        return self.perceive(req)

    def perceive_combined(
        self,
        image: Any,
        language: str = "zh",
        min_confidence: float = 0.0,
        max_objects: Optional[int] = None,
    ) -> PerceptionResult:
        """快捷联合感知"""
        req = PerceptionRequest(
            source=PerceptionSource.COMBINED.value,
            image=image,
            language=language,
            min_confidence=min_confidence,
            max_objects=max_objects,
        )
        return self.perceive(req)

    def capture_screen_and_perceive(
        self,
        mode: str = "ocr",          # ocr / detection / combined
        region: Optional[Dict[str, int]] = None,
        language: str = "zh",
    ) -> PerceptionResult:
        """截图后感知屏幕 (需要注入 VisionService)

        Args:
            mode: 感知模式 (ocr / detection / combined)
            region: 区域截图 (None=全屏)
            language: OCR 期望语言
        """
        if self._vision_service is None:
            return PerceptionResult.create_error(
                source=mode,
                status=PerceptionStatus.ERROR.value,
                error="未注入 VisionService, 无法截屏",
            )

        try:
            from backend.vision.schema import VisionCaptureRequest, VisionSource
            from backend.vision.service import VisionService

            if not isinstance(self._vision_service, VisionService):
                return PerceptionResult.create_error(
                    source=mode,
                    status=PerceptionStatus.ERROR.value,
                    error="vision_service 类型不正确",
                )

            cap_req = VisionCaptureRequest(
                source=VisionSource.SCREEN.value,
                region=region,
            )
            cap_result = self._vision_service.capture(cap_req)
            if not cap_result.is_ok:
                return PerceptionResult.create_error(
                    source=mode,
                    status=cap_result.frame.status,
                    error=f"截图失败: {cap_result.frame.error}",
                )

            source_map = {
                "ocr": PerceptionSource.OCR.value,
                "detection": PerceptionSource.DETECTION.value,
                "combined": PerceptionSource.COMBINED.value,
            }
            req = PerceptionRequest(
                source=source_map.get(mode, PerceptionSource.OCR.value),
                image=cap_result.frame.image,
                language=language,
            )
            return self.perceive(req)

        except Exception as e:
            logger.error(f"截图感知异常: {e}", exc_info=True)
            return PerceptionResult.create_error(
                source=mode,
                status=PerceptionStatus.ERROR.value,
                error=f"截图感知异常: {type(e).__name__}: {e}",
            )

    # ── Adapter 管理 ──────────────────────────────────────────────
    def list_ocr_adapters(self) -> List[Dict[str, Any]]:
        return self._manager.list_ocr_adapters()

    def list_detection_adapters(self) -> List[Dict[str, Any]]:
        return self._manager.list_detection_adapters()

    # ── 日志查询 ──────────────────────────────────────────────────
    def get_logs(
        self,
        source: Optional[str] = None,
        adapter: Optional[str] = None,
        event: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        entries = self._plog.query(
            source=source, adapter=adapter, event=event, limit=limit
        )
        return [e.to_dict() for e in entries]

    def get_log_stats(self) -> Dict[str, Any]:
        return self._plog.stats()

    def clear_logs(self) -> int:
        return self._plog.clear()

    # ── 状态 ──────────────────────────────────────────────────────
    def status(self) -> Dict[str, Any]:
        return {
            "version": "1.0.0",
            "initialized": self._initialized,
            "permission": self._permission.to_dict(),
            "manager": self._manager.status(),
            "log_stats": self._plog.stats(),
            "has_vision_service": self._vision_service is not None,
        }


# ── 全局单例 ─────────────────────────────────────────────────────
_global_service: Optional[PerceptionService] = None
_service_lock = threading.Lock()


def get_service() -> PerceptionService:
    """获取全局 PerceptionService 单例"""
    global _global_service
    with _service_lock:
        if _global_service is None:
            mgr = get_manager()
            _global_service = PerceptionService(manager=mgr)
        return _global_service


def reset_service() -> None:
    """重置全局 Service (测试用)"""
    global _global_service
    with _service_lock:
        _global_service = None
    reset_manager()


__all__ = [
    "PerceptionService",
    "PerceptionServiceError",
    "get_service",
    "reset_service",
]
