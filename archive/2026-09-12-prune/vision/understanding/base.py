"""
YHLZ Vision Understanding V1.0 - Adapter 基类 (实现通用逻辑)

职责:
    - 继承 VLMAdapter 抽象基类
    - 提供通用辅助方法 (异常隔离 / 时间统计)
    - 子类只需注入 Provider, 复用通用流程

设计原则:
    - 模板方法模式: base 控制流程, Provider 执行实际理解
    - 异常隔离: Provider 抛出的异常被捕获并转为错误结果
    - 不绑定单一模型 (通过 Provider 切换)
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

from backend.vision.understanding.interface import (
    UnderstandingOptions,
    VLMAdapter,
)
from backend.vision.understanding.providers.base import ProviderError, VLMProvider
from backend.vision.understanding.schema import (
    UnderstandingResult,
    UnderstandingStatus,
)

logger = logging.getLogger(__name__)


def _error_result(
    source: str,
    error: str,
    provider: str = "unknown",
    status: str = UnderstandingStatus.ERROR.value,
    processing_time: float = 0.0,
) -> UnderstandingResult:
    """构造错误 UnderstandingResult (附耗时)"""
    return UnderstandingResult.create_error(
        source=source,
        status=status,
        error=error,
        metadata={"provider": provider},
    ).with_processing_time(processing_time)


class BaseVLMAdapter(VLMAdapter):
    """VLM Adapter 基类 - 模板方法模式

    子类只需:
        1. 在 __init__ 注入 VLMProvider
        2. (可选) 重写 _preprocess_image 进行图像预处理

    Base 负责:
        - 检查 Provider 可用性
        - 异常捕获并转错误结果
        - 时间统计
        - 超时保护 (options.timeout)
    """

    name: str = "base_vlm"
    source: str = "vlm"

    def __init__(self, provider: Optional[VLMProvider] = None):
        self._provider = provider

    @property
    def provider(self) -> Optional[VLMProvider]:
        return self._provider

    def set_provider(self, provider: VLMProvider) -> None:
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

    def understand(
        self,
        image: Any,
        prompt: Optional[str] = None,
        options: Optional[UnderstandingOptions] = None,
    ) -> UnderstandingResult:
        """执行视觉理解 (模板方法)

        流程:
            1. 校验输入
            2. 检查 Provider 可用性
            3. 调用 Provider.understand
            4. 异常捕获并转错误结果
            5. 计算耗时
        """
        start = time.perf_counter()
        provider_name = self._provider.name if self._provider else "none"

        # 1. 输入校验
        if image is None:
            latency = (time.perf_counter() - start) * 1000
            logger.warning(f"[{self.name}] 输入图像为空")
            return _error_result(
                self.source,
                "输入图像为空",
                provider=provider_name,
                status=UnderstandingStatus.EMPTY_INPUT.value,
                processing_time=latency / 1000.0,
            )

        # 2. Provider 校验
        if self._provider is None:
            latency = (time.perf_counter() - start) * 1000
            return _error_result(
                self.source,
                "未配置 VLM Provider",
                provider="none",
                status=UnderstandingStatus.NO_PROVIDER.value,
                processing_time=latency / 1000.0,
            )
        if not self.is_available():
            latency = (time.perf_counter() - start) * 1000
            return _error_result(
                self.source,
                f"VLM Provider {provider_name} 不可用",
                provider=provider_name,
                status=UnderstandingStatus.NO_PROVIDER.value,
                processing_time=latency / 1000.0,
            )

        opts = options or UnderstandingOptions()

        # 3. 预处理
        try:
            processed = self._preprocess_image(image, opts)
        except Exception as e:
            latency = (time.perf_counter() - start) * 1000
            logger.error(f"[{self.name}] 图像预处理异常: {e}", exc_info=True)
            return _error_result(
                self.source,
                f"图像预处理异常: {type(e).__name__}: {e}",
                provider=provider_name,
                processing_time=latency / 1000.0,
            )

        # 4. 调用 Provider (带超时保护)
        try:
            result = self._call_provider(processed, prompt, opts)
            latency = (time.perf_counter() - start) * 1000
            if result is None or not isinstance(result, UnderstandingResult):
                result = _error_result(
                    self.source,
                    "Provider 返回空结果",
                    provider=provider_name,
                )
            result.processing_time = latency / 1000.0
            logger.debug(
                f"[{self.name}] 理解成功 scene_type={result.scene_type} "
                f"latency={latency:.1f}ms"
            )
            return result
        except ProviderError as e:
            latency = (time.perf_counter() - start) * 1000
            logger.error(f"[{self.name}] VLM Provider 错误: {e}")
            return _error_result(
                self.source,
                f"Provider 错误: {e}",
                provider=provider_name,
                processing_time=latency / 1000.0,
            )
        except Exception as e:
            latency = (time.perf_counter() - start) * 1000
            logger.error(f"[{self.name}] 理解异常: {e}", exc_info=True)
            return _error_result(
                self.source,
                f"理解异常: {type(e).__name__}: {e}",
                provider=provider_name,
                processing_time=latency / 1000.0,
            )

    def _call_provider(
        self,
        image: Any,
        prompt: Optional[str],
        options: UnderstandingOptions,
    ) -> UnderstandingResult:
        """调用 Provider (子类可重写实现超时 / 重试策略)"""
        return self._provider.understand(image, prompt, options)

    def _preprocess_image(self, image: Any, options: UnderstandingOptions) -> Any:
        """图像预处理 (子类可重写)"""
        return image

    def get_info(self) -> Dict[str, Any]:
        info = super().get_info()
        if self._provider:
            info["provider"] = self._provider.get_info()
        return info


__all__ = ["BaseVLMAdapter"]
