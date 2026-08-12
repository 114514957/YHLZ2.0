"""
YHLZ Vision Understanding V1.0 - VLM Adapter (基于 Provider)

职责:
    - 组合 VLMProvider (Mock / OpenAI 兼容)
    - 对外提供统一 understand 接口
    - 不绑定单一 VLM 模型

设计:
    - 通过 set_provider 切换底层模型
    - 默认注入 MockVLMProvider (测试模式)
    - 生产环境注入 OpenAICompatibleVLMProvider
"""
from __future__ import annotations

import logging
from typing import Optional

from backend.vision.understanding.base import BaseVLMAdapter
from backend.vision.understanding.providers.base import VLMProvider
from backend.vision.understanding.providers.mock_provider import MockVLMProvider

logger = logging.getLogger(__name__)


class VLMAdapter(BaseVLMAdapter):
    """VLM Adapter (生产可注入任意 VLMProvider)

    用法:
        # Mock 模式 (测试)
        adapter = VLMAdapter()

        # OpenAI 兼容 VLM 模式 (如 Qwen-VL)
        from backend.vision.understanding.providers.openai_vlm_provider import (
            OpenAICompatibleVLMProvider,
        )
        adapter = VLMAdapter(provider=OpenAICompatibleVLMProvider())

        # 运行时切换
        adapter.set_provider(MockVLMProvider())
    """

    name: str = "VLMAdapter"
    source: str = "vlm"

    def __init__(self, provider: Optional[VLMProvider] = None):
        # 默认 Mock, 保证无外部模型时也可工作
        super().__init__(provider=provider or MockVLMProvider())
        if provider is None:
            logger.debug("VLMAdapter 未指定 Provider, 使用 MockVLMProvider")

    def get_info(self) -> dict:
        info = super().get_info()
        info["default_provider"] = "mock"
        return info


__all__ = ["VLMAdapter"]
