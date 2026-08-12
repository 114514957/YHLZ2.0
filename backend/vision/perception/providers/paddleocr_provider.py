"""
YHLZ Vision Perception V1.0 - PaddleOCR Provider

职责:
    - 封装 PaddleOCR 库调用
    - 提供 OCR 识别能力
    - 异常转换为 ProviderError

设计原则:
    - 懒加载 (首次调用时加载模型, 不在 import 时加载)
    - 无 PaddleOCR 库时返回 is_available=False (不抛异常)
    - 真实模型测试用 @unittest.skipIf 标记
"""
from __future__ import annotations

import logging
from typing import Any, List, Optional

from backend.vision.perception.interface import PerceptionOptions
from backend.vision.perception.providers.base import OCRProvider, ProviderError
from backend.vision.perception.schema import BoundingBox, DetectedText

logger = logging.getLogger(__name__)


class PaddleOCRProvider(OCRProvider):
    """PaddleOCR Provider

    用法:
        provider = PaddleOCRProvider()
        if provider.is_available():
            texts = provider.recognize_text(image)

    特性:
        - 懒加载 (首次 recognize_text 时初始化 PaddleOCR 实例)
        - 支持中英文 (use_angle_cls=True)
        - 无 PaddleOCR 库时 is_available()=False
        - 测试环境用 YHLZ_PERCEPTION_TEST_MODE=true 跳过
    """

    name: str = "paddleocr"

    def __init__(
        self,
        lang: str = "ch",                  # PaddleOCR 语言模型 (ch / en / chinese_cht ...)
        use_angle_cls: bool = True,        # 是否使用角度分类
        use_gpu: bool = False,
        auto_load: bool = False,
    ):
        self._lang = lang
        self._use_angle_cls = use_angle_cls
        self._use_gpu = use_gpu
        self._ocr = None  # 懒加载
        self._loaded = False
        self._load_error: Optional[str] = None
        if auto_load:
            self._ensure_loaded()

    def is_available(self) -> bool:
        """检测 PaddleOCR 是否可用"""
        try:
            import paddleocr  # noqa: F401
            return True
        except ImportError:
            return False
        except Exception as e:
            logger.warning(f"PaddleOCR 可用性检查异常: {e}")
            return False

    def _ensure_loaded(self) -> None:
        """懒加载 PaddleOCR 实例"""
        if self._loaded:
            return
        try:
            from paddleocr import PaddleOCR
            self._ocr = PaddleOCR(
                use_angle_cls=self._use_angle_cls,
                lang=self._lang,
                use_gpu=self._use_gpu,
                show_log=False,
            )
            self._loaded = True
            logger.info(f"PaddleOCR 已加载 (lang={self._lang}, gpu={self._use_gpu})")
        except ImportError as e:
            self._load_error = f"PaddleOCR 未安装: {e}"
            logger.warning(self._load_error)
        except Exception as e:
            self._load_error = f"PaddleOCR 加载失败: {type(e).__name__}: {e}"
            logger.error(self._load_error, exc_info=True)

    def recognize_text(
        self,
        image: Any,
        options: Optional[PerceptionOptions] = None,
    ) -> List[DetectedText]:
        """执行 OCR 识别

        Raises:
            ProviderError: 库未安装 / 加载失败 / 识别异常
        """
        if image is None:
            raise ProviderError("输入图像为空")

        self._ensure_loaded()
        if self._ocr is None:
            raise ProviderError(
                f"PaddleOCR 不可用: {self._load_error or '未知原因'}"
            )

        try:
            # PaddleOCR.ocr 返回 [[bbox, (text, confidence)], ...]
            result = self._ocr.ocr(image, cls=self._use_angle_cls)
            return self._parse_result(result, options)
        except Exception as e:
            raise ProviderError(f"PaddleOCR 识别失败: {type(e).__name__}: {e}") from e

    def _parse_result(
        self,
        result: Any,
        options: Optional[PerceptionOptions] = None,
    ) -> List[DetectedText]:
        """解析 PaddleOCR 原始结果为 DetectedText 列表"""
        texts: List[DetectedText] = []
        if not result:
            return texts

        # PaddleOCR 2.x: result 是 list[list[box, (text, conf)]]
        # PaddleOCR 3.x 可能返回 dict 结构, 此处兼容处理
        items = []
        try:
            if isinstance(result, list):
                for page in result:
                    if page is None:
                        continue
                    if isinstance(page, list):
                        items.extend(page)
                    elif isinstance(page, dict) and "rec_texts" in page:
                        # PaddleOCR 3.x 结构: {rec_texts: [], rec_scores: [], dt_polys: []}
                        rec_texts = page.get("rec_texts", [])
                        rec_scores = page.get("rec_scores", [])
                        dt_polys = page.get("dt_polys", [])
                        for i, text in enumerate(rec_texts):
                            conf = float(rec_scores[i]) if i < len(rec_scores) else 0.5
                            pos = self._poly_to_bbox(dt_polys[i]) if i < len(dt_polys) else None
                            texts.append(DetectedText(
                                content=text,
                                language=self._lang,
                                confidence=conf,
                                position=pos,
                            ))
                        return texts
        except Exception as e:
            logger.warning(f"PaddleOCR 结果解析异常: {e}")

        # 2.x 结构: [[box, (text, conf)]]
        for item in items:
            try:
                box, text_info = item
                text, conf = text_info
                position = self._box_to_bbox(box)
                texts.append(DetectedText(
                    content=text,
                    language=self._lang,
                    confidence=float(conf),
                    position=position,
                ))
            except (ValueError, TypeError) as e:
                logger.warning(f"PaddleOCR 项解析失败: {e}, item={item}")
                continue

        # 应用置信度过滤
        if options and options.min_confidence > 0:
            texts = [t for t in texts if t.confidence >= options.min_confidence]

        return texts

    @staticmethod
    def _box_to_bbox(box: Any) -> BoundingBox:
        """PaddleOCR 4点框 → BoundingBox (左上 / 右下)"""
        try:
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            x = int(min(xs))
            y = int(min(ys))
            w = int(max(xs) - x)
            h = int(max(ys) - y)
            return BoundingBox(x=x, y=y, w=w, h=h)
        except Exception:
            return BoundingBox()

    @staticmethod
    def _poly_to_bbox(poly: Any) -> BoundingBox:
        """PaddleOCR 3.x 多边形 → BoundingBox"""
        try:
            import numpy as np
            arr = np.array(poly)
            xs = arr[:, 0]
            ys = arr[:, 1]
            x = int(xs.min())
            y = int(ys.min())
            w = int(xs.max() - x)
            h = int(ys.max() - y)
            return BoundingBox(x=x, y=y, w=w, h=h)
        except Exception:
            return BoundingBox()

    def get_info(self) -> dict:
        info = super().get_info()
        info["lang"] = self._lang
        info["loaded"] = self._loaded
        info["load_error"] = self._load_error
        return info


__all__ = ["PaddleOCRProvider"]
