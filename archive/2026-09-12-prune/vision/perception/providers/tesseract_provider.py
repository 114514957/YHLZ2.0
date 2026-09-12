"""
YHLZ Vision Perception V1.0 - Tesseract Provider

职责:
    - 封装 pytesseract 库调用
    - 提供基于 Tesseract OCR 引擎的识别能力
    - 异常转换为 ProviderError

设计原则:
    - 懒加载 (首次调用时检查 Tesseract 安装)
    - 无 pytesseract / tesseract 可执行文件时 is_available=False
"""
from __future__ import annotations

import logging
from typing import Any, List, Optional

from backend.vision.perception.interface import PerceptionOptions
from backend.vision.perception.providers.base import OCRProvider, ProviderError
from backend.vision.perception.schema import BoundingBox, DetectedText

logger = logging.getLogger(__name__)


class TesseractProvider(OCRProvider):
    """Tesseract OCR Provider

    用法:
        provider = TesseractProvider(lang="chi_sim+eng")
        if provider.is_available():
            texts = provider.recognize_text(image)

    特性:
        - 依赖 pytesseract + tesseract 可执行文件
        - 支持中英文 (lang=chi_sim+eng)
        - 返回 image_to_data 结果 (含位置与置信度)
    """

    name: str = "tesseract"

    def __init__(
        self,
        lang: str = "chi_sim+eng",
        config: str = "--psm 6",
    ):
        self._lang = lang
        self._config = config
        self._available_checked = False
        self._available = False

    def is_available(self) -> bool:
        """检测 Tesseract + pytesseract 是否可用"""
        if self._available_checked:
            return self._available
        try:
            import pytesseract  # noqa: F401
            # 触发一次调用验证 tesseract 可执行文件存在
            pytesseract.get_tesseract_version()
            self._available = True
        except ImportError:
            logger.warning("pytesseract 未安装, TesseractProvider 不可用")
            self._available = False
        except Exception as e:
            logger.warning(f"Tesseract 可执行文件未找到: {e}")
            self._available = False
        self._available_checked = True
        return self._available

    def recognize_text(
        self,
        image: Any,
        options: Optional[PerceptionOptions] = None,
    ) -> List[DetectedText]:
        """执行 OCR 识别

        Raises:
            ProviderError: 库未安装 / 识别异常
        """
        if image is None:
            raise ProviderError("输入图像为空")

        if not self.is_available():
            raise ProviderError("Tesseract 不可用 (pytesseract 未安装或可执行文件缺失)")

        try:
            import pytesseract
            from PIL import Image
            import numpy as np

            # numpy ndarray → PIL Image
            if isinstance(image, np.ndarray):
                # BGR → RGB
                if image.ndim == 3 and image.shape[2] == 3:
                    image_rgb = image[:, :, ::-1].copy()
                else:
                    image_rgb = image
                pil_img = Image.fromarray(image_rgb)
            else:
                pil_img = image  # 假设已是 PIL Image

            # 使用 image_to_data 获取带位置与置信度的结果
            data = pytesseract.image_to_data(
                pil_img,
                lang=self._lang,
                config=self._config,
                output_type=pytesseract.Output.DICT,
            )
            return self._parse_data(data)

        except ImportError as e:
            raise ProviderError(f"pytesseract 未安装: {e}") from e
        except Exception as e:
            raise ProviderError(f"Tesseract 识别失败: {type(e).__name__}: {e}") from e

    def _parse_data(self, data: Any) -> List[DetectedText]:
        """解析 image_to_data 字典结果"""
        texts: List[DetectedText] = []
        if not isinstance(data, dict):
            return texts

        n = len(data.get("text", []))
        for i in range(n):
            text = (data["text"][i] or "").strip()
            if not text:
                continue
            try:
                conf = float(data["conf"][i]) / 100.0  # tesseract conf 是 0-100
            except (KeyError, ValueError, TypeError):
                conf = 0.0
            if conf < 0:
                conf = 0.0
            x = int(data.get("left", [0] * n)[i])
            y = int(data.get("top", [0] * n)[i])
            w = int(data.get("width", [0] * n)[i])
            h = int(data.get("height", [0] * n)[i])
            texts.append(DetectedText(
                content=text,
                language=self._lang,
                confidence=conf,
                position=BoundingBox(x=x, y=y, w=w, h=h),
            ))
        return texts

    def get_info(self) -> dict:
        info = super().get_info()
        info["lang"] = self._lang
        info["config"] = self._config
        return info


__all__ = ["TesseractProvider"]
