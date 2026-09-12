"""
YHLZ Vision Understanding V1.0 - Understanding Service

职责:
    - 统一对外 API (Interface 层)
    - 组合 Manager + Permission + Logger
    - 流程: 权限校验 → 理解 → 日志记录 → 返回 UnderstandingResult
    - 可选组合 VisionService (截屏后理解) / PerceptionService (感知上下文)

架构位置:
    Interface (FastAPI / 外部调用 / Agent Tool)
        ↓
    Service (本模块)
        ↓
    Manager → Adapter → Provider

设计原则:
    - 单一入口: 所有理解操作经 Service
    - 权限优先: 处理前先校验权限 (understanding_enabled)
    - 日志完整: 记录开始/成功/失败/耗时/异常
    - 配置驱动: 从 config 加载权限与参数
    - 可测试: 提供完整 Mock 注入接口
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List, Optional

from backend.vision.understanding.interface import UnderstandingOptions
from backend.vision.understanding.logger import UnderstandingLogger
from backend.vision.understanding.manager import (
    UnderstandingManager,
    get_manager,
    reset_manager,
)
from backend.vision.understanding.permission import (
    PermissionChecker,
    UnderstandingPermission,
)
from backend.vision.understanding.schema import (
    UnderstandingRequest,
    UnderstandingResult,
    UnderstandingSource,
    UnderstandingStatus,
)

logger = logging.getLogger(__name__)


class UnderstandingServiceError(Exception):
    """Understanding Service 操作异常"""


class UnderstandingService:
    """理解统一服务

    用法:
        svc = UnderstandingService()
        svc.load_config(config_dict)
        result = svc.understand(UnderstandingRequest(image=img))

    流程:
        1. 权限校验 (PermissionChecker)
        2. 图像预处理 (region 裁剪)
        3. 调用 Manager 路由到 Adapter
        4. 日志记录
        5. 返回 UnderstandingResult

    可选流程:
        - 从 VisionService 获取屏幕截图后理解 (capture_screen_and_understand)
        - 结合 PerceptionService 感知结果作为上下文 (可选)
    """

    def __init__(
        self,
        manager: Optional[UnderstandingManager] = None,
        permission: Optional[PermissionChecker] = None,
        ulog: Optional[UnderstandingLogger] = None,
        vision_service: Optional[Any] = None,
        perception_service: Optional[Any] = None,
    ):
        self._lock = threading.RLock()
        self._manager: UnderstandingManager = manager or UnderstandingManager()
        self._permission: PermissionChecker = permission or PermissionChecker()
        self._ulog: UnderstandingLogger = ulog or UnderstandingLogger()
        self._vision_service = vision_service  # 可选, 用于截图
        self._perception_service = perception_service  # 可选, 感知上下文
        self._initialized = False

    # ── 依赖注入 ──────────────────────────────────────────────────
    def set_manager(self, manager: UnderstandingManager) -> None:
        with self._lock:
            self._manager = manager

    def set_permission(self, permission: PermissionChecker) -> None:
        with self._lock:
            self._permission = permission

    def set_logger(self, ulog: UnderstandingLogger) -> None:
        with self._lock:
            self._ulog = ulog

    def set_vision_service(self, vision_service: Any) -> None:
        """注入 VisionService (用于截屏后理解)"""
        with self._lock:
            self._vision_service = vision_service

    def set_perception_service(self, perception_service: Any) -> None:
        """注入 PerceptionService (用于感知上下文)"""
        with self._lock:
            self._perception_service = perception_service

    @property
    def manager(self) -> UnderstandingManager:
        return self._manager

    @property
    def permission(self) -> PermissionChecker:
        return self._permission

    @property
    def ulog(self) -> UnderstandingLogger:
        return self._ulog

    @property
    def vision_service(self) -> Optional[Any]:
        return self._vision_service

    @property
    def perception_service(self) -> Optional[Any]:
        return self._perception_service

    # ── 配置 ──────────────────────────────────────────────────────
    def load_config(self, config: Dict[str, Any]) -> None:
        """从 dict 加载配置 (权限 + 默认注册)"""
        with self._lock:
            perm = UnderstandingPermission.from_dict(config)
            self._permission.load_from_permission(perm)
            self._manager.register_defaults(include_mock=True)
            self._initialized = True
        logger.info(f"UnderstandingService 配置已加载: {perm.to_dict()}")

    def load_permission(self, permission: UnderstandingPermission) -> None:
        self._permission.load_from_permission(permission)

    def update_permission(self, **kwargs) -> UnderstandingPermission:
        return self._permission.update(**kwargs)

    def get_permission(self) -> Dict[str, Any]:
        return self._permission.to_dict()

    def reset_permission(self) -> None:
        self._permission.reset()

    # ── 核心理解 ──────────────────────────────────────────────────
    def understand(self, request: UnderstandingRequest) -> UnderstandingResult:
        """执行视觉理解 (完整流程)

        流程:
            1. 日志记录开始
            2. 权限校验
            3. 图像预处理 (region 裁剪)
            4. 构造 Options (prompt / question)
            5. 调用 Manager 路由到 Adapter
            6. 日志记录成功/失败

        Args:
            request: 理解请求 (source + image + prompt/question)

        Returns:
            UnderstandingResult
        """
        import time as _time

        # 1. 日志开始
        self._ulog.log_start(
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
            result = UnderstandingResult.create_error(
                source=request.source,
                status=UnderstandingStatus.PERMISSION_DENIED.value,
                error=reason,
                metadata=request.to_dict(),
            )
            result.processing_time = latency / 1000.0
            self._ulog.log_fail(
                source=request.source,
                adapter="none",
                status=UnderstandingStatus.PERMISSION_DENIED.value,
                error=reason,
                latency_ms=latency,
            )
            return result

        # 3. 图像预处理 (region 裁剪)
        image = request.image
        if request.region is not None:
            image = self._crop_region(image, request.region)

        # 4. 构造 Options
        options = UnderstandingOptions(
            prompt=request.prompt,
            question=request.question,
            language=request.language,
            max_tokens=request.max_tokens,
            temperature=request.temperature,
        )

        # 5. 路由到 VLM Adapter
        try:
            result = self._manager.understand(
                image,
                prompt=options.prompt,
                options=options,
            )
        except Exception as e:
            logger.error(f"[Understanding] Manager 理解异常: {e}", exc_info=True)
            latency = (_time.perf_counter() - start) * 1000
            result = UnderstandingResult.create_error(
                source=request.source,
                status=UnderstandingStatus.ERROR.value,
                error=f"理解异常: {type(e).__name__}: {e}",
                metadata=request.to_dict(),
            )
            result.processing_time = latency / 1000.0
            self._ulog.log_fail(
                source=request.source,
                adapter="unknown",
                status=UnderstandingStatus.ERROR.value,
                error=result.error or "",
                latency_ms=latency,
            )
            return result

        # 补全元数据与耗时
        total_latency = (_time.perf_counter() - start) * 1000
        result.processing_time = total_latency / 1000.0
        result.metadata = {
            **(result.metadata or {}),
            **(request.metadata or {}),
            "source_request": request.source,
        }

        # 6. 日志记录
        provider = (result.metadata or {}).get("provider", "unknown")
        if result.is_ok:
            self._ulog.log_success(
                source=request.source,
                adapter="VLMAdapter",
                result_id=result.id,
                latency_ms=total_latency,
                provider=provider,
                scene_type=result.scene_type,
                subject_count=len(result.subjects),
                confidence=result.confidence,
            )
        else:
            self._ulog.log_fail(
                source=request.source,
                adapter="VLMAdapter",
                status=result.status,
                error=result.error or "未知错误",
                latency_ms=total_latency,
                provider=provider,
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
    def understand_image(
        self,
        image: Any,
        prompt: Optional[str] = None,
        language: str = "zh",
        max_tokens: int = 512,
        region: Optional[Dict[str, int]] = None,
    ) -> UnderstandingResult:
        """对图片执行视觉理解 (describe 模式)"""
        req = UnderstandingRequest(
            source=UnderstandingSource.DESCRIBE.value,
            image=image,
            prompt=prompt,
            language=language,
            max_tokens=max_tokens,
            region=region,
        )
        return self.understand(req)

    def describe_scene(
        self,
        image: Any,
        language: str = "zh",
        region: Optional[Dict[str, int]] = None,
    ) -> UnderstandingResult:
        """场景描述 (describe 模式)"""
        return self.understand_image(
            image=image,
            prompt=None,
            language=language,
            region=region,
        )

    def answer_visual(
        self,
        image: Any,
        question: str,
        language: str = "zh",
        max_tokens: int = 512,
        region: Optional[Dict[str, int]] = None,
    ) -> UnderstandingResult:
        """视觉问答 (qa 模式)"""
        req = UnderstandingRequest(
            source=UnderstandingSource.QA.value,
            image=image,
            question=question,
            language=language,
            max_tokens=max_tokens,
            region=region,
        )
        return self.understand(req)

    def capture_screen_and_understand(
        self,
        mode: str = "describe",      # describe / qa
        region: Optional[Dict[str, int]] = None,
        language: str = "zh",
        question: Optional[str] = None,
    ) -> UnderstandingResult:
        """截图后理解屏幕 (需要注入 VisionService)

        Args:
            mode: 理解模式 (describe / qa)
            region: 区域截图 (None=全屏)
            language: 输出语言
            question: 视觉问答问题 (qa 模式)
        """
        if self._vision_service is None:
            return UnderstandingResult.create_error(
                source=mode,
                status=UnderstandingStatus.ERROR.value,
                error="未注入 VisionService, 无法截屏",
            )

        try:
            from backend.vision.schema import VisionCaptureRequest, VisionSource
            from backend.vision.service import VisionService

            if not isinstance(self._vision_service, VisionService):
                return UnderstandingResult.create_error(
                    source=mode,
                    status=UnderstandingStatus.ERROR.value,
                    error="vision_service 类型不正确",
                )

            cap_req = VisionCaptureRequest(
                source=VisionSource.SCREEN.value,
                region=region,
            )
            cap_result = self._vision_service.capture(cap_req)
            if not cap_result.is_ok:
                return UnderstandingResult.create_error(
                    source=mode,
                    status=cap_result.frame.status,
                    error=f"截图失败: {cap_result.frame.error}",
                )

            image = cap_result.frame.image
            if mode == "qa":
                return self.answer_visual(image, question or "这张图片里有什么?", language)
            return self.describe_scene(image, language)
        except Exception as e:
            logger.error(f"截图理解异常: {e}", exc_info=True)
            return UnderstandingResult.create_error(
                source=mode,
                status=UnderstandingStatus.ERROR.value,
                error=f"截图理解异常: {type(e).__name__}: {e}",
            )

    def understand_with_perception(
        self,
        image: Any,
        prompt: Optional[str] = None,
        language: str = "zh",
    ) -> UnderstandingResult:
        """感知 + 理解: 先跑 Perception, 感知结果拼入提示词 (需要注入 PerceptionService)

        可选增强: 无 PerceptionService 时退化为普通 describe。
        """
        if self._perception_service is None:
            logger.debug("未注入 PerceptionService, 退化为普通理解")
            return self.describe_scene(image, language)

        try:
            from backend.vision.perception.schema import (
                PerceptionRequest,
                PerceptionSource,
            )
            from backend.vision.perception.service import PerceptionService

            if not isinstance(self._perception_service, PerceptionService):
                return self.describe_scene(image, language)

            perm = self._perception_service.get_permission()
            if not (perm.get("perception_enabled") and perm.get("ocr_enabled")):
                logger.debug("感知权限未开启, 退化为普通理解")
                return self.describe_scene(image, language)

            p_req = PerceptionRequest(
                source=PerceptionSource.OCR.value,
                image=image,
            )
            p_result = self._perception_service.perceive(p_req)
            context = ""
            if p_result.is_ok and p_result.text:
                context = "\n画面中的文字内容:\n" + p_result.text_content

            effective_prompt = prompt or "请描述这张图片的场景。"
            if context:
                effective_prompt = effective_prompt + context
            return self.understand_image(image, prompt=effective_prompt, language=language)
        except Exception as e:
            logger.error(f"感知+理解异常, 退化为普通理解: {e}", exc_info=True)
            return self.describe_scene(image, language)

    # ── Adapter 管理 ──────────────────────────────────────────────
    def list_adapters(self) -> List[Dict[str, Any]]:
        return self._manager.list_adapters()

    # ── 日志查询 ──────────────────────────────────────────────────
    def get_logs(
        self,
        source: Optional[str] = None,
        adapter: Optional[str] = None,
        event: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        entries = self._ulog.query(
            source=source, adapter=adapter, event=event, limit=limit
        )
        return [e.to_dict() for e in entries]

    def get_log_stats(self) -> Dict[str, Any]:
        return self._ulog.stats()

    def clear_logs(self) -> int:
        return self._ulog.clear()

    # ── 状态 ──────────────────────────────────────────────────────
    def status(self) -> Dict[str, Any]:
        return {
            "version": "1.0.0",
            "initialized": self._initialized,
            "permission": self._permission.to_dict(),
            "manager": self._manager.status(),
            "log_stats": self._ulog.stats(),
            "has_vision_service": self._vision_service is not None,
            "has_perception_service": self._perception_service is not None,
        }


# ── 全局单例 ─────────────────────────────────────────────────────
_global_service: Optional[UnderstandingService] = None
_service_lock = threading.Lock()


def get_service() -> UnderstandingService:
    """获取全局 UnderstandingService 单例"""
    global _global_service
    with _service_lock:
        if _global_service is None:
            mgr = get_manager()
            _global_service = UnderstandingService(manager=mgr)
        return _global_service


def reset_service() -> None:
    """重置全局 Service (测试用)"""
    global _global_service
    with _service_lock:
        _global_service = None
    reset_manager()


__all__ = [
    "UnderstandingService",
    "UnderstandingServiceError",
    "get_service",
    "reset_service",
]
