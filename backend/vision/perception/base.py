"""
YHLZ Vision Perception V1.0 - Adapter 基类 (实现通用逻辑)

职责:
    - 继承 OCRAdapter / DetectionAdapter 抽象基类
    - 提供通用辅助方法 (region 裁剪 / 异常隔离 / 时间统计)
    - 子类只需注入 Provider, 复用通用流程

设计原则:
    - 模板方法模式: base 控制流程, Provider 执行实际识别
    - 异常隔离: Provider 抛出的异常被捕获并转为错误结果
    - 不绑定单一库 (通过 Provider 切换)
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

from backend.vision.perception.interface import (
    DetectionAdapter,
    OCRAdapter,
    PerceptionOptions,
)
from backend.vision.perception.providers.base import (
    DetectionProvider,
    OCRProvider,
    ProviderError,
)
from backend.vision.perception.schema import (
    BoundingBox,
    DetectionResult,
    OCRResult,
)

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# BaseOCRAdapter
# ----------------------------------------------------------------------

class BaseOCRAdapter(OCRAdapter):
    """OCR Adapter 基类 - 模板方法模式

    子类只需:
        1. 在 __init__ 注入 OCRProvider
        2. (可选) 重写 _preprocess_image 进行图像预处理

    Base 负责:
        - 检查 Provider 可用性
        - region 裁剪
        - 异常捕获并转错误结果
        - 时间统计
    """

    name: str = "base_ocr"
    source: str = "ocr"

    def __init__(self, provider: Optional[OCRProvider] = None):
        self._provider = provider

    @property
    def provider(self) -> Optional[OCRProvider]:
        return self._provider

    def set_provider(self, provider: OCRProvider) -> None:
        """运行时替换 Provider"""
        self._provider = provider

    def is_available(self) -> bool:
        if self._provider is None:
            return False
        try:
            return self._provider.is_available()
        except Exception as e:
            logger.warning(f"[{self.name}] provider.is_available 异常: {e}")
            return False

    def recognize(
        self,
        image: Any,
        options: Optional[PerceptionOptions] = None,
    ) -> OCRResult:
        """执行 OCR (模板方法)

        流程:
            1. 校验输入
            2. 检查 Provider 可用性
            3. region 裁剪 (如指定)
            4. 调用 Provider.recognize_text
            5. 异常捕获并转错误结果
            6. 计算耗时
        """
        start = time.perf_counter()
        provider_name = self._provider.name if self._provider else "none"

        # 1. 输入校验
        if image is None:
            latency = (time.perf_counter() - start) * 1000
            logger.warning(f"[{self.name}] 输入图像为空")
            return OCRResult(
                success=False,
                error="输入图像为空",
                processing_time_ms=latency,
                provider=provider_name,
            )

        # 2. Provider 校验
        if self._provider is None:
            latency = (time.perf_counter() - start) * 1000
            return OCRResult(
                success=False,
                error="未配置 OCR Provider",
                processing_time_ms=latency,
                provider="none",
            )
        if not self.is_available():
            latency = (time.perf_counter() - start) * 1000
            return OCRResult(
                success=False,
                error=f"OCR Provider {provider_name} 不可用",
                processing_time_ms=latency,
                provider=provider_name,
            )

        # 3. region 裁剪
        opts = options or PerceptionOptions()
        try:
            processed = self._preprocess_image(image, opts)
        except Exception as e:
            latency = (time.perf_counter() - start) * 1000
            logger.error(f"[{self.name}] 图像预处理异常: {e}", exc_info=True)
            return OCRResult(
                success=False,
                error=f"图像预处理异常: {type(e).__name__}: {e}",
                processing_time_ms=latency,
                provider=provider_name,
            )

        # 4. 调用 Provider
        try:
            texts = self._provider.recognize_text(processed, opts)
            latency = (time.perf_counter() - start) * 1000

            # 应用 min_confidence 过滤
            if opts.min_confidence > 0:
                texts = [t for t in texts if t.confidence >= opts.min_confidence]

            logger.debug(
                f"[{self.name}] OCR 成功 texts={len(texts)} latency={latency:.1f}ms"
            )
            return OCRResult(
                success=True,
                texts=texts,
                processing_time_ms=latency,
                provider=provider_name,
            )
        except ProviderError as e:
            latency = (time.perf_counter() - start) * 1000
            logger.error(f"[{self.name}] OCR Provider 错误: {e}")
            return OCRResult(
                success=False,
                error=f"Provider 错误: {e}",
                processing_time_ms=latency,
                provider=provider_name,
            )
        except Exception as e:
            latency = (time.perf_counter() - start) * 1000
            logger.error(f"[{self.name}] OCR 异常: {e}", exc_info=True)
            return OCRResult(
                success=False,
                error=f"OCR 异常: {type(e).__name__}: {e}",
                processing_time_ms=latency,
                provider=provider_name,
            )

    def _preprocess_image(self, image: Any, options: PerceptionOptions) -> Any:
        """图像预处理 (子类可重写)

        默认实现: 应用 region 裁剪 (如指定)
        """
        if options is None:
            return image
        # 这里不复用 region (已在 PerceptionRequest 层处理), 仅做扩展点
        return image

    def get_info(self) -> Dict[str, Any]:
        info = super().get_info()
        if self._provider:
            info["provider"] = self._provider.get_info()
        return info


# ----------------------------------------------------------------------
# BaseDetectionAdapter
# ----------------------------------------------------------------------

class BaseDetectionAdapter(DetectionAdapter):
    """Detection Adapter 基类 - 模板方法模式

    子类只需:
        1. 在 __init__ 注入 DetectionProvider
        2. (可选) 重写 _preprocess_image
    """

    name: str = "base_detection"
    source: str = "detection"

    def __init__(self, provider: Optional[DetectionProvider] = None):
        self._provider = provider

    @property
    def provider(self) -> Optional[DetectionProvider]:
        return self._provider

    def set_provider(self, provider: DetectionProvider) -> None:
        self._provider = provider

    def is_available(self) -> bool:
        if self._provider is None:
            return False
        try:
            return self._provider.is_available()
        except Exception as e:
            logger.warning(f"[{self.name}] provider.is_available 异常: {e}")
            return False

    def detect(
        self,
        image: Any,
        options: Optional[PerceptionOptions] = None,
    ) -> DetectionResult:
        """执行 Detection (模板方法)

        流程:
            1. 校验输入
            2. 检查 Provider 可用性
            3. 调用 Provider.detect_objects
            4. 异常捕获并转错误结果
            5. 计算耗时
        """
        start = time.perf_counter()
        provider_name = self._provider.name if self._provider else "none"

        if image is None:
            latency = (time.perf_counter() - start) * 1000
            return DetectionResult(
                success=False,
                error="输入图像为空",
                processing_time_ms=latency,
                provider=provider_name,
            )

        if self._provider is None:
            latency = (time.perf_counter() - start) * 1000
            return DetectionResult(
                success=False,
                error="未配置 Detection Provider",
                processing_time_ms=latency,
                provider="none",
            )
        if not self.is_available():
            latency = (time.perf_counter() - start) * 1000
            return DetectionResult(
                success=False,
                error=f"Detection Provider {provider_name} 不可用",
                processing_time_ms=latency,
                provider=provider_name,
            )

        opts = options or PerceptionOptions()
        try:
            processed = self._preprocess_image(image, opts)
        except Exception as e:
            latency = (time.perf_counter() - start) * 1000
            logger.error(f"[{self.name}] 图像预处理异常: {e}", exc_info=True)
            return DetectionResult(
                success=False,
                error=f"图像预处理异常: {type(e).__name__}: {e}",
                processing_time_ms=latency,
                provider=provider_name,
            )

        try:
            objects = self._provider.detect_objects(processed, opts)
            latency = (time.perf_counter() - start) * 1000

            # 应用 min_confidence 过滤
            if opts.min_confidence > 0:
                objects = [o for o in objects if o.confidence >= opts.min_confidence]
            # 应用 max_objects
            if opts.max_objects is not None:
                objects = objects[:opts.max_objects]

            logger.debug(
                f"[{self.name}] Detection 成功 objects={len(objects)} "
                f"latency={latency:.1f}ms"
            )
            return DetectionResult(
                success=True,
                objects=objects,
                processing_time_ms=latency,
                provider=provider_name,
            )
        except ProviderError as e:
            latency = (time.perf_counter() - start) * 1000
            logger.error(f"[{self.name}] Detection Provider 错误: {e}")
            return DetectionResult(
                success=False,
                error=f"Provider 错误: {e}",
                processing_time_ms=latency,
                provider=provider_name,
            )
        except Exception as e:
            latency = (time.perf_counter() - start) * 1000
            logger.error(f"[{self.name}] Detection 异常: {e}", exc_info=True)
            return DetectionResult(
                success=False,
                error=f"Detection 异常: {type(e).__name__}: {e}",
                processing_time_ms=latency,
                provider=provider_name,
            )

    def _preprocess_image(self, image: Any, options: PerceptionOptions) -> Any:
        return image

    def get_info(self) -> Dict[str, Any]:
        info = super().get_info()
        if self._provider:
            info["provider"] = self._provider.get_info()
        return info


__all__ = ["BaseOCRAdapter", "BaseDetectionAdapter"]
