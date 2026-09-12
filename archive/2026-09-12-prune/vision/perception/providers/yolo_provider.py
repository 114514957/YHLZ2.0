"""
YHLZ Vision Perception V1.0 - YOLO Detection Provider (占位实现)

职责:
    - 封装 ultralytics YOLO 模型调用
    - 提供目标检测能力
    - 异常转换为 ProviderError

设计原则:
    - 懒加载 (首次调用时加载模型)
    - 无 ultralytics / 模型文件时 is_available=False (不抛)
    - 真实模型测试用 @unittest.skipIf 标记

本版本范围:
    - 仅建立接口, 占位实现
    - 真实 YOLO 模型加载在 V1.1 / V2.0 完善
"""
from __future__ import annotations

import logging
from typing import Any, List, Optional

from backend.vision.perception.interface import PerceptionOptions
from backend.vision.perception.providers.base import DetectionProvider, ProviderError
from backend.vision.perception.schema import BoundingBox, DetectedObject

logger = logging.getLogger(__name__)


class YOLOProvider(DetectionProvider):
    """YOLO Detection Provider

    用法:
        provider = YOLOProvider(model_path="yolov8n.pt")
        if provider.is_available():
            objects = provider.detect_objects(image)

    特性:
        - 懒加载 (首次 detect_objects 时加载模型)
        - 默认使用 yolov8n (轻量级, 适配 CPU 推理)
        - 返回带位置和置信度的对象列表
        - 本版本为占位实现, is_available() 检测 ultralytics 安装情况
    """

    name: str = "yolo"

    # COCO 数据集类别 (80 类) - 与 yolov8n 默认模型一致
    COCO_NAMES = [
        "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train",
        "truck", "boat", "traffic light", "fire hydrant", "stop sign",
        "parking meter", "bench", "bird", "cat", "dog", "horse", "sheep",
        "cow", "elephant", "bear", "zebra", "giraffe", "backpack", "umbrella",
        "handbag", "tie", "suitcase", "frisbee", "skis", "snowboard",
        "sports ball", "kite", "baseball bat", "baseball glove", "skateboard",
        "surfboard", "tennis racket", "bottle", "wine glass", "cup", "fork",
        "knife", "spoon", "bowl", "banana", "apple", "sandwich", "orange",
        "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair",
        "couch", "potted plant", "bed", "dining table", "toilet", "tv",
        "laptop", "mouse", "remote", "keyboard", "cell phone", "microwave",
        "oven", "toaster", "sink", "refrigerator", "book", "clock", "vase",
        "scissors", "teddy bear", "hair drier", "toothbrush",
    ]

    def __init__(
        self,
        model_path: str = "yolov8n.pt",
        device: str = "cpu",                # cpu / cuda
        conf_threshold: float = 0.25,
        iou_threshold: float = 0.45,
        auto_load: bool = False,
    ):
        self._model_path = model_path
        self._device = device
        self._conf_threshold = conf_threshold
        self._iou_threshold = iou_threshold
        self._model = None
        self._loaded = False
        self._load_error: Optional[str] = None
        if auto_load:
            self._ensure_loaded()

    def is_available(self) -> bool:
        """检测 ultralytics 是否可用"""
        try:
            import ultralytics  # noqa: F401
            return True
        except ImportError:
            return False
        except Exception as e:
            logger.warning(f"ultralytics 可用性检查异常: {e}")
            return False

    def _ensure_loaded(self) -> None:
        """懒加载 YOLO 模型"""
        if self._loaded:
            return
        try:
            from ultralytics import YOLO
            self._model = YOLO(self._model_path)
            self._loaded = True
            logger.info(f"YOLO 已加载 (model={self._model_path}, device={self._device})")
        except ImportError as e:
            self._load_error = f"ultralytics 未安装: {e}"
            logger.warning(self._load_error)
        except Exception as e:
            self._load_error = f"YOLO 加载失败: {type(e).__name__}: {e}"
            logger.error(self._load_error, exc_info=True)

    def detect_objects(
        self,
        image: Any,
        options: Optional[PerceptionOptions] = None,
    ) -> List[DetectedObject]:
        """执行目标检测

        Raises:
            ProviderError: 库未安装 / 加载失败 / 检测异常
        """
        if image is None:
            raise ProviderError("输入图像为空")

        self._ensure_loaded()
        if self._model is None:
            raise ProviderError(
                f"YOLO 不可用: {self._load_error or '未知原因'}"
            )

        try:
            results = self._model(
                image,
                conf=self._conf_threshold,
                iou=self._iou_threshold,
                device=self._device,
                verbose=False,
            )
            return self._parse_results(results, options)
        except Exception as e:
            raise ProviderError(f"YOLO 检测失败: {type(e).__name__}: {e}") from e

    def _parse_results(
        self,
        results: Any,
        options: Optional[PerceptionOptions] = None,
    ) -> List[DetectedObject]:
        """解析 YOLO 原始结果"""
        objects: List[DetectedObject] = []
        if not results:
            return objects

        try:
            # ultralytics 结果是 list, 取第一个 (单图)
            r = results[0] if isinstance(results, list) else results
            boxes = r.boxes
            if boxes is None:
                return objects

            for box in boxes:
                # box.xyxy: tensor [x1, y1, x2, y2]
                xyxy = box.xyxy[0].cpu().numpy() if hasattr(box.xyxy, "__getitem__") else box.xyxy
                x1, y1, x2, y2 = xyxy
                cls_id = int(box.cls[0])
                conf = float(box.conf[0])
                name = self.COCO_NAMES[cls_id] if 0 <= cls_id < len(self.COCO_NAMES) else f"class_{cls_id}"
                category = self._get_category(name)
                objects.append(DetectedObject(
                    name=name,
                    category=category,
                    position=BoundingBox(
                        x=int(x1), y=int(y1),
                        w=int(x2 - x1), h=int(y2 - y1),
                    ),
                    confidence=conf,
                ))

            # 应用 min_confidence
            if options and options.min_confidence > 0:
                objects = [o for o in objects if o.confidence >= options.min_confidence]
            # 应用 max_objects
            if options and options.max_objects is not None:
                objects = objects[:options.max_objects]
        except Exception as e:
            logger.warning(f"YOLO 结果解析异常: {e}")
        return objects

    @staticmethod
    def _get_category(name: str) -> str:
        """根据 COCO 名称推断类别 (粗粒度分组)"""
        category_map = {
            "human": {"person"},
            "vehicle": {"bicycle", "car", "motorcycle", "airplane", "bus",
                       "train", "truck", "boat"},
            "animal": {"bird", "cat", "dog", "horse", "sheep", "cow",
                       "elephant", "bear", "zebra", "giraffe"},
            "electronics": {"tv", "laptop", "mouse", "remote", "keyboard",
                            "cell phone", "microwave", "oven", "toaster",
                            "refrigerator"},
            "furniture": {"chair", "couch", "bed", "dining table", "toilet"},
            "kitchen": {"bottle", "wine glass", "cup", "fork", "knife", "spoon",
                       "bowl", "sink"},
            "food": {"banana", "apple", "sandwich", "orange", "broccoli",
                    "carrot", "hot dog", "pizza", "donut", "cake"},
            "accessory": {"backpack", "umbrella", "handbag", "tie", "suitcase"},
            "sports": {"frisbee", "skis", "snowboard", "sports ball", "kite",
                      "baseball bat", "baseball glove", "skateboard",
                      "surfboard", "tennis racket"},
            "indoor": {"clock", "vase", "scissors", "teddy bear",
                      "hair drier", "toothbrush", "book"},
            "outdoor": {"traffic light", "fire hydrant", "stop sign",
                       "parking meter", "bench"},
        }
        for cat, names in category_map.items():
            if name in names:
                return cat
        return "other"

    def get_info(self) -> dict:
        info = super().get_info()
        info["model"] = self._model_path
        info["device"] = self._device
        info["loaded"] = self._loaded
        info["load_error"] = self._load_error
        return info


__all__ = ["YOLOProvider"]
