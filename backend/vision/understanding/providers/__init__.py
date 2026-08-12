"""
YHLZ Vision Understanding V1.0 - Provider 层

VLM (Mock / OpenAI 兼容) 的抽象与实现。
Adapter 不直接调用这些模型, 而是通过 Provider 间接调用。
"""
from __future__ import annotations

from backend.vision.understanding.providers.base import (
    VLMProvider,
    ProviderError,
    build_prompt,
)
from backend.vision.understanding.providers.mock_provider import MockVLMProvider

__all__ = [
    "VLMProvider",
    "ProviderError",
    "build_prompt",
    "MockVLMProvider",
]
