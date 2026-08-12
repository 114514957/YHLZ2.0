"""
YHLZ Embodied AI V6.3 - Tesseract OCR 适配器 (Tesseract OCR Adapter)

职责:
    - 真实 OCR 引擎 (pytesseract), 替代 Mock OCR
    - 与 Mock 同一 PerceptionAdapter 接口 (行为一致)
    - 无 pytesseract / 无 tesseract 可执行 → is_available=False
      (测试 skipIf, 不导致系统失败)

输出 (OCRResult 扩展):
    {text, confidence, source: "tesseract", timestamp}
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

from backend.embodied.companion.perception.interface import (
    PerceptionAdapter,
)
from backend.embodied.companion.perception.schema import (
    DetectionResult,
    OCRResult,
)

logger = logging.getLogger(__name__)


class TesseractOCRAdapter(PerceptionAdapter):
    """Tesseract OCR 适配器

    依赖:
        - pytesseract 包
        - tesseract 可执行文件 (pytesseract.get_tesseract_version)
    """

    name = "tesseract_ocr"
    source = "tesseract"

    def __init__(self, tesseract_cmd: str = ""):
        self._tesseract_cmd = str(tesseract_cmd)
        self._pytesseract = None
        self._available = False
        self._try_load()

    def _try_load(self) -> None:
        """尝试加载 pytesseract (不可用则标记不可用)"""
        try:
            import pytesseract  # type: ignore
            if self._tesseract_cmd:
                pytesseract.pytesseract.tesseract_cmd = \
                    self._tesseract_cmd
            # 验证 tesseract 可执行存在
            pytesseract.get_tesseract_version()
            self._pytesseract = pytesseract
            self._available = True
        except Exception as e:
            logger.info(f"[Perception] Tesseract 不可用: {e}")
            self._available = False

    def is_available(self) -> bool:
        """无 pytesseract / 无 tesseract → False"""
        return self._available

    def ocr(self, image: Any = None,
            metadata: Optional[Dict[str, Any]] = None) -> OCRResult:
        """执行 OCR (真实引擎)"""
        if not self._available:
            raise RuntimeError("Tesseract 不可用")
        if image is None:
            raise ValueError("Tesseract OCR 需要图像输入")
        try:
            text = self._pytesseract.image_to_string(image)
            conf_data = self._pytesseract.image_to_data(
                image, output_type=self._pytesseract.Output.DICT,
            )
            confidences = [
                int(c) for c in conf_data.get("conf", [])
                if str(c).isdigit() and int(c) >= 0
            ]
            avg_conf = (
                sum(confidences) / len(confidences) / 100.0
                if confidences else 0.5
            )
            return OCRResult(
                text=text.strip(),
                confidence=max(0.0, min(1.0, avg_conf)),
            )
        except Exception as e:
            raise RuntimeError(f"Tesseract OCR 失败: {e}")

    def detect(self, image: Any = None,
               metadata: Optional[Dict[str, Any]] = None
               ) -> DetectionResult:
        """Tesseract 不做目标检测 (返回空)"""
        return DetectionResult(objects=[], confidence=0.0)

    def get_info(self) -> Dict[str, Any]:
        """适配器信息 (含引擎状态)"""
        info = super().get_info()
        info["source"] = "tesseract"
        return info


__all__ = ["TesseractOCRAdapter"]
