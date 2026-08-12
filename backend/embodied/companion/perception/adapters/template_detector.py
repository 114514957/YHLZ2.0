"""
YHLZ Embodied AI V6.3 - 模板匹配检测器 (Template Detector Adapter)

职责:
    - 轻量视觉识别: 模板匹配 (OpenCV matchTemplate)
    - 禁止大模型视觉依赖
    - 无 OpenCV → is_available=False (测试 skipIf)

输出 (DetectionResult 扩展):
    {objects: [{label, bbox, confidence}], confidence, source: "template"}
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from backend.embodied.companion.perception.interface import (
    PerceptionAdapter,
)
from backend.embodied.companion.perception.schema import (
    DetectionResult,
    OCRResult,
)

logger = logging.getLogger(__name__)


class TemplateDetectorAdapter(PerceptionAdapter):
    """模板匹配检测适配器 (OpenCV)

    用法:
        detector = TemplateDetectorAdapter(templates={
            "book": <numpy 数组模板>,
        })
        result = detector.detect(scene_image)
    """

    name = "template_detector"
    source = "template"

    def __init__(
        self,
        templates: Optional[Dict[str, Any]] = None,
        match_threshold: float = 0.7,
        nms_enabled: bool = True,
        nms_iou_threshold: float = 0.5,
    ):
        self._templates: Dict[str, Any] = dict(templates or {})
        self._threshold = float(match_threshold)
        self._nms_enabled = bool(nms_enabled)
        self._nms_iou = float(nms_iou_threshold)
        self._cv2 = None
        self._np = None
        self._try_load()

    def _try_load(self) -> None:
        """尝试加载 OpenCV + numpy"""
        try:
            import cv2  # type: ignore
            import numpy as np  # type: ignore
            self._cv2 = cv2
            self._np = np
        except ImportError:
            logger.info("[Perception] OpenCV 不可用, "
                        "模板检测适配器不可用")

    def is_available(self) -> bool:
        """无 OpenCV / 无模板 → False"""
        return self._cv2 is not None and bool(self._templates)

    def add_template(self, label: str, template: Any) -> None:
        """注册模板"""
        self._templates[label] = template

    def remove_template(self, label: str) -> bool:
        """移除模板"""
        return self._templates.pop(label, None) is not None

    def detect(self, image: Any = None,
               metadata: Optional[Dict[str, Any]] = None
               ) -> DetectionResult:
        """模板匹配检测 (matchTemplate)

        Args:
            image: 场景图像 (numpy 数组/BGR 或灰度)

        Returns:
            DetectionResult: 匹配目标列表
        """
        if not self.is_available():
            raise RuntimeError("模板检测不可用 (无 OpenCV 或无模板)")
        if image is None:
            raise ValueError("模板检测需要图像输入")
        cv2 = self._cv2
        np = self._np
        scene = image
        if scene.ndim == 3:
            scene = cv2.cvtColor(scene, cv2.COLOR_BGR2GRAY)
        objects: List[Dict[str, Any]] = []
        max_conf = 0.0
        for label, template in self._templates.items():
            tpl = template
            if tpl.ndim == 3:
                tpl = cv2.cvtColor(tpl, cv2.COLOR_BGR2GRAY)
            if scene.shape[0] < tpl.shape[0] or \
                    scene.shape[1] < tpl.shape[1]:
                continue
            # TM_SQDIFF_NORMED: 值越小越匹配 (对噪声更鲁棒)
            result = cv2.matchTemplate(scene, tpl,
                                       cv2.TM_SQDIFF_NORMED)
            if self._nms_enabled:
                matches = self._multi_match(
                    result, tpl.shape[:2],
                )
            else:
                min_val, max_val, min_loc, max_loc = \
                    cv2.minMaxLoc(result)
                matches = [(
                    min_loc, 1.0 - float(min_val),
                )] if 1.0 - float(min_val) >= self._threshold \
                    else []
            for loc, confidence in matches:
                h, w = tpl.shape[:2]
                objects.append({
                    "label": label,
                    "bbox": [loc[0], loc[1], w, h],
                    "confidence": round(confidence, 4),
                })
                max_conf = max(max_conf, confidence)
        return DetectionResult(objects=objects,
                               confidence=round(max_conf, 4))

    def _multi_match(self, result: Any,
                     tpl_shape: tuple) -> List[tuple]:
        """多目标匹配: 阈值过滤 + 局部最大值 + NMS 规则

        Args:
            result: matchTemplate 结果矩阵
            tpl_shape: (h, w)

        Returns:
            [(loc, confidence), ...]
        """
        np = self._np
        h, w = tpl_shape
        conf = 1.0 - result
        # 1. 阈值过滤
        mask = conf >= self._threshold
        if not mask.any():
            return []
        # 2. 局部最大值 (非极大值抑制的简化: 逐点邻域)
        ys, xs = np.where(mask)
        candidates: List[tuple] = []
        for y, x in zip(ys, xs):
            candidates.append(((int(x), int(y)),
                               float(conf[y, x])))
        # 3. 按置信度降序, IoU 去重 (NMS 规则)
        candidates.sort(key=lambda c: c[1], reverse=True)
        kept: List[tuple] = []
        for loc, c in candidates:
            overlap = False
            for k_loc, _ in kept:
                if self._iou(loc, k_loc, w, h) > self._nms_iou:
                    overlap = True
                    break
            if not overlap:
                kept.append((loc, c))
        return kept

    @staticmethod
    def _iou(a: tuple, b: tuple, w: int, h: int) -> float:
        """IoU 计算 (规则版)"""
        ax, ay = a
        bx, by = b
        ix = max(0, min(ax + w, bx + w) - max(ax, bx))
        iy = max(0, min(ay + h, by + h) - max(ay, by))
        inter = ix * iy
        union = w * h * 2 - inter
        return inter / union if union > 0 else 0.0

    def ocr(self, image: Any = None,
            metadata: Optional[Dict[str, Any]] = None) -> OCRResult:
        """模板检测不做 OCR (返回空)"""
        return OCRResult(text="")

    def get_info(self) -> Dict[str, Any]:
        info = super().get_info()
        info["source"] = "template"
        info["templates"] = list(self._templates.keys())
        info["match_threshold"] = self._threshold
        info["nms_enabled"] = self._nms_enabled
        info["nms_iou_threshold"] = self._nms_iou
        return info


__all__ = ["TemplateDetectorAdapter"]
