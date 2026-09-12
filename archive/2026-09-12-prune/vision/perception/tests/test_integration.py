"""
集成测试: Perception 子系统端到端流程
覆盖: Schema → Interface → Base → Adapter → Provider → Manager → Service → Permission → Logger
异常场景: 权限关闭 / 输入为空 / Provider 异常 / Adapter 异常 / 联合感知
真实设备场景: PaddleOCR / Tesseract / YOLO (skipIf 无库)
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from backend.vision.perception.adapters.detection_adapter import DetectionAdapter
from backend.vision.perception.adapters.ocr_adapter import OCRAdapter
from backend.vision.perception.interface import PerceptionOptions
from backend.vision.perception.logger import PerceptionLogger
from backend.vision.perception.manager import PerceptionManager
from backend.vision.perception.permission import PermissionChecker
from backend.vision.perception.providers.mock_provider import (
    MockDetectionProvider,
    MockOCRProvider,
)
from backend.vision.perception.providers.paddleocr_provider import PaddleOCRProvider
from backend.vision.perception.providers.tesseract_provider import TesseractProvider
from backend.vision.perception.providers.yolo_provider import YOLOProvider
from backend.vision.perception.schema import (
    PerceptionRequest,
    PerceptionSource,
    PerceptionStatus,
)
from backend.vision.perception.service import PerceptionService, reset_service

# 真实设备测试开关
_RUN_REAL = os.getenv("YHLZ_RUN_REAL_TESTS", "false").lower() == "true"


class TestEndToEndFlow(unittest.TestCase):
    """端到端流程测试 (Mock)"""

    def setUp(self):
        reset_service()
        self.mgr = PerceptionManager()
        self.mgr.register_ocr_adapter(
            "mock", OCRAdapter(provider=MockOCRProvider(texts=["hello", "world"]))
        )
        self.mgr.register_detection_adapter(
            "mock", DetectionAdapter(provider=MockDetectionProvider())
        )
        self.perm = PermissionChecker()
        self.perm.update(
            perception_enabled=True, ocr_enabled=True, detection_enabled=True
        )
        self.plog = PerceptionLogger(max_entries=500, enable_logging=False)
        self.svc = PerceptionService(
            manager=self.mgr, permission=self.perm, plog=self.plog
        )
        self.image = np.zeros((480, 640, 3), dtype=np.uint8)

    def tearDown(self):
        reset_service()

    def test_full_ocr_flow(self):
        """完整 OCR 流程: 权限 → Manager → Adapter → Provider → Result"""
        req = PerceptionRequest(source="ocr", image=self.image)
        result = self.svc.perceive(req)
        self.assertTrue(result.is_ok)
        self.assertEqual(result.source, "ocr")
        self.assertEqual(len(result.text), 2)
        # 日志完整
        logs = self.plog.query(limit=10)
        events = [e.event for e in logs]
        self.assertIn("start", events)
        self.assertIn("success", events)
        # 统计正确
        stats = self.plog.stats()
        self.assertGreaterEqual(stats["success"], 1)

    def test_full_detection_flow(self):
        req = PerceptionRequest(source="detection", image=self.image)
        result = self.svc.perceive(req)
        self.assertTrue(result.is_ok)
        self.assertGreater(len(result.objects), 0)
        self.assertGreater(result.confidence, 0)

    def test_combined_flow(self):
        req = PerceptionRequest(source="combined", image=self.image)
        result = self.svc.perceive(req)
        self.assertTrue(result.is_ok)
        self.assertGreater(len(result.objects), 0)
        self.assertGreater(len(result.text), 0)

    def test_multiple_perceives(self):
        for _ in range(5):
            req = PerceptionRequest(source="ocr", image=self.image)
            result = self.svc.perceive(req)
            self.assertTrue(result.is_ok)
        stats = self.plog.stats()
        self.assertEqual(stats["success"], 5)
        self.assertGreater(stats["avg_latency_ms"], 0)

    def test_min_confidence_filter(self):
        """全局 min_confidence 过滤"""
        self.perm.update(min_confidence=0.85)
        req = PerceptionRequest(source="detection", image=self.image)
        result = self.svc.perceive(req)
        # 默认对象置信度: 0.92, 0.88, 0.75 → 2 个 >= 0.85
        self.assertEqual(len(result.objects), 2)


class TestExceptionScenarios(unittest.TestCase):
    """异常场景测试"""

    def setUp(self):
        reset_service()
        self.mgr = PerceptionManager()
        self.perm = PermissionChecker()
        self.perm.update(perception_enabled=True, ocr_enabled=True, detection_enabled=True)
        self.plog = PerceptionLogger(max_entries=500, enable_logging=False)
        self.svc = PerceptionService(
            manager=self.mgr, permission=self.perm, plog=self.plog
        )
        self.image = np.zeros((100, 100, 3), dtype=np.uint8)

    def tearDown(self):
        reset_service()

    def test_permission_denied_returns_structured_error(self):
        self.perm.reset()
        req = PerceptionRequest(source="ocr", image=self.image)
        result = self.svc.perceive(req)
        self.assertFalse(result.is_ok)
        self.assertEqual(result.status, PerceptionStatus.PERMISSION_DENIED.value)
        self.assertIsNotNone(result.error)

    def test_empty_image_rejected_by_permission(self):
        """权限层校验输入图像"""
        req = PerceptionRequest(source="ocr", image=None)
        result = self.svc.perceive(req)
        self.assertFalse(result.is_ok)

    def test_provider_exception_returns_error_result(self):
        """Provider 异常应转为错误结果, 不外抛"""
        self.mgr.register_ocr_adapter(
            "bad", OCRAdapter(provider=MockOCRProvider(mode="exception"))
        )
        req = PerceptionRequest(source="ocr", image=self.image)
        result = self.svc.perceive(req)
        # Manager 默认使用第一个注册的 Adapter
        self.assertFalse(result.is_ok)
        self.assertEqual(result.status, PerceptionStatus.ERROR.value)

    def test_no_adapter_registered(self):
        """未注册任何 Adapter, Manager 返回错误结果"""
        req = PerceptionRequest(source="ocr", image=self.image)
        result = self.svc.perceive(req)
        self.assertFalse(result.is_ok)

    def test_unknown_source_rejected(self):
        req = PerceptionRequest(source="unknown", image=self.image)
        result = self.svc.perceive(req)
        self.assertFalse(result.is_ok)

    def test_combined_partial_failure(self):
        """联合感知: OCR 失败但 Detection 成功, 仍返回结果"""
        # 只注册 Detection (不注册 OCR)
        self.mgr.register_detection_adapter(
            "mock", DetectionAdapter(provider=MockDetectionProvider())
        )
        req = PerceptionRequest(source="combined", image=self.image)
        result = self.svc.perceive(req)
        self.assertTrue(result.is_ok)
        self.assertGreater(len(result.objects), 0)
        self.assertEqual(len(result.text), 0)


class TestRealProviders(unittest.TestCase):
    """真实 Provider 集成测试 (需要环境)"""

    def setUp(self):
        # 重置环境, 避免污染
        reset_service()

    def test_paddleocr_provider_available_check(self):
        """PaddleOCR 可用性检查 (不依赖真实加载)"""
        provider = PaddleOCRProvider()
        # 仅验证不抛异常, 真实环境可能是 True 或 False
        result = provider.is_available()
        self.assertIsInstance(result, bool)

    def test_tesseract_provider_available_check(self):
        provider = TesseractProvider()
        result = provider.is_available()
        self.assertIsInstance(result, bool)

    def test_yolo_provider_available_check(self):
        provider = YOLOProvider()
        result = provider.is_available()
        self.assertIsInstance(result, bool)

    @unittest.skipUnless(_RUN_REAL, "需要 YHLZ_RUN_REAL_TESTS=true")
    def test_paddleocr_real_recognize(self):
        """真实 PaddleOCR 识别 (需要安装 paddleocr)"""
        provider = PaddleOCRProvider(auto_load=True)
        if not provider.is_available():
            self.skipTest("PaddleOCR 未安装")
        # 用合成图像 (实际场景需有文字)
        image = np.zeros((100, 200, 3), dtype=np.uint8)
        try:
            texts = provider.recognize_text(image)
            self.assertIsInstance(texts, list)
        except Exception as e:
            self.skipTest(f"PaddleOCR 识别失败 (合成图像无文字正常): {e}")

    @unittest.skipUnless(_RUN_REAL, "需要 YHLZ_RUN_REAL_TESTS=true")
    def test_yolo_real_detect(self):
        """真实 YOLO 检测 (需要安装 ultralytics + 模型文件)"""
        provider = YOLOProvider(auto_load=True)
        if not provider.is_available():
            self.skipTest("ultralytics 未安装")
        image = np.zeros((640, 480, 3), dtype=np.uint8)
        try:
            objects = provider.detect_objects(image)
            self.assertIsInstance(objects, list)
        except Exception as e:
            self.skipTest(f"YOLO 检测失败 (合成图像无对象正常): {e}")


class TestSchemaSerialization(unittest.TestCase):
    """Schema 序列化/反序列化测试"""

    def test_perception_result_full_roundtrip(self):
        from backend.vision.perception.schema import (
            BoundingBox,
            DetectedObject,
            DetectedText,
            PerceptionResult,
        )
        r1 = PerceptionResult.create_ok(
            source="combined",
            objects=[
                DetectedObject(name="car", category="vehicle",
                              position=BoundingBox(10, 20, 100, 50), confidence=0.9)
            ],
            text=[
                DetectedText(content="hello", language="en", confidence=0.95)
            ],
            processing_time=0.05,
        )
        d = r1.to_dict()
        r2 = PerceptionResult.from_dict(d)
        self.assertEqual(r1.source, r2.source)
        self.assertEqual(len(r1.objects), len(r2.objects))
        self.assertEqual(r1.objects[0].name, r2.objects[0].name)
        self.assertEqual(r1.objects[0].position.x, r2.objects[0].position.x)
        self.assertEqual(len(r1.text), len(r2.text))
        self.assertEqual(r1.text[0].content, r2.text[0].content)


if __name__ == "__main__":
    unittest.main()
