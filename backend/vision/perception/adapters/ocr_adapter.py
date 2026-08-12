"""
YHLZ Vision Perception V1.0 - OCR Adapter (基于 Provider)

职责:
    - 组合 OCRProvider (PaddleOCR / Tesseract / Mock)
    - 对外提供统一 recognize 接口
    - 不绑定单一 OCR 库

设计:
    - 通过 set_provider 切换底层库
    - 默认注入 MockOCRProvider (测试模式)
    - 生产环境注入 PaddleOCRProvider / TesseractProvider
"""
from __future__ import annotations

import logging
from typing import Optional

from backend.vision.perception.base import BaseOCRAdapter
from backend.vision.perception.providers.base import OCRProvider
from backend.vision.perception.providers.mock_provider import MockOCRProvider

logger = logging.getLogger(__name__)


class OCRAdapter(BaseOCRAdapter):
    """OCR Adapter (生产可注入任意 OCRProvider)

    用法:
        # Mock 模式 (测试)
        adapter = OCRAdapter()

        # PaddleOCR 模式
        from backend.vision.perception.providers.paddleocr_provider import PaddleOCRProvider
        adapter = OCRAdapter(provider=PaddleOCRProvider())

        # 运行时切换
        adapter.set_provider(TesseractProvider())
    """

    name: str = "OCRAdapter"
    source: str = "ocr"

    def __init__(self, provider: Optional[OCRProvider] = None):
        # 默认 Mock, 保证无外部库时也可工作
        super().__init__(provider=provider or MockOCRProvider())
        if provider is None:
            logger.debug("OCRAdapter 未指定 Provider, 使用 MockOCRProvider")

    def get_info(self) -> dict:
        info = super().get_info()
        info["default_provider"] = "mock"
        return info


__all__ = ["OCRAdapter"]
