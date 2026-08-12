"""
YHLZ Embodied AI V6.3 - 感知适配器包 (Perception Adapters)

Mock 优先: Mock 与真实实现同一接口, 行为一致
    - vision_mock:       Mock 视觉 (合成图像)
    - ocr_mock:          OCR Mock (合成文本)
    - detection_mock:    检测 Mock (合成目标)
    - camera_adapter:    摄像头 (OpenCV, 权限默认拒绝)
    - tesseract_ocr:     Tesseract OCR (真实, skipIf 无环境)
    - template_detector: 模板匹配检测 (真实, skipIf 无 OpenCV)
"""
from backend.embodied.companion.perception.adapters.camera_adapter import (
    CameraAdapter,
)
from backend.embodied.companion.perception.adapters.detection_mock import (
    DetectionMockAdapter,
)
from backend.embodied.companion.perception.adapters.ocr_mock import (
    OCRMockAdapter,
)
from backend.embodied.companion.perception.adapters.template_detector import (
    TemplateDetectorAdapter,
)
from backend.embodied.companion.perception.adapters.tesseract_ocr import (
    TesseractOCRAdapter,
)
from backend.embodied.companion.perception.adapters.vision_mock import (
    VisionMockAdapter,
)

__all__ = [
    "CameraAdapter",
    "DetectionMockAdapter",
    "OCRMockAdapter",
    "TemplateDetectorAdapter",
    "TesseractOCRAdapter",
    "VisionMockAdapter",
]
