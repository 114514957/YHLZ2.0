"""
单元测试: manager.py - PerceptionManager
覆盖: 注册 / 注销 / 路由 / 默认注册 / 单例
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from backend.vision.perception.adapters.detection_adapter import DetectionAdapter
from backend.vision.perception.adapters.ocr_adapter import OCRAdapter
from backend.vision.perception.interface import PerceptionOptions
from backend.vision.perception.manager import (
    PerceptionManager,
    PerceptionManagerError,
    get_manager,
    reset_manager,
)
from backend.vision.perception.providers.mock_provider import (
    MockDetectionProvider,
    MockOCRProvider,
)


class TestPerceptionManager(unittest.TestCase):

    def setUp(self):
        reset_manager()
        self.mgr = PerceptionManager()
        self.image = np.zeros((100, 200, 3), dtype=np.uint8)

    def tearDown(self):
        reset_manager()

    def test_default_no_adapter(self):
        """未注册时无 Adapter"""
        self.assertEqual(len(self.mgr.list_ocr_adapters()), 0)
        self.assertEqual(len(self.mgr.list_detection_adapters()), 0)

    def test_register_ocr_adapter(self):
        adapter = OCRAdapter(provider=MockOCRProvider())
        self.mgr.register_ocr_adapter("mock", adapter)
        self.assertTrue(self.mgr.has_ocr_adapter("mock"))
        self.assertEqual(len(self.mgr.list_ocr_adapters()), 1)

    def test_register_ocr_duplicate_no_override(self):
        adapter1 = OCRAdapter(provider=MockOCRProvider())
        adapter2 = OCRAdapter(provider=MockOCRProvider())
        self.mgr.register_ocr_adapter("mock", adapter1)
        with self.assertRaises(PerceptionManagerError):
            self.mgr.register_ocr_adapter("mock", adapter2)

    def test_register_ocr_with_override(self):
        adapter1 = OCRAdapter(provider=MockOCRProvider(texts=["old"]))
        adapter2 = OCRAdapter(provider=MockOCRProvider(texts=["new"]))
        self.mgr.register_ocr_adapter("mock", adapter1)
        self.mgr.register_ocr_adapter("mock", adapter2, override=True)
        result = self.mgr.recognize_ocr(self.image)
        self.assertEqual(result.texts[0].content, "new")

    def test_unregister_ocr(self):
        adapter = OCRAdapter(provider=MockOCRProvider())
        self.mgr.register_ocr_adapter("mock", adapter)
        self.assertTrue(self.mgr.unregister_ocr_adapter("mock"))
        self.assertFalse(self.mgr.has_ocr_adapter("mock"))
        self.assertFalse(self.mgr.unregister_ocr_adapter("nonexistent"))

    def test_register_detection_adapter(self):
        adapter = DetectionAdapter(provider=MockDetectionProvider())
        self.mgr.register_detection_adapter("mock", adapter)
        self.assertTrue(self.mgr.has_detection_adapter("mock"))

    def test_recognize_ocr_routes_to_adapter(self):
        """Manager 路由 OCR 请求到 Adapter"""
        adapter = OCRAdapter(provider=MockOCRProvider(texts=["hello"]))
        self.mgr.register_ocr_adapter("default", adapter)
        result = self.mgr.recognize_ocr(self.image)
        self.assertTrue(result.success)
        self.assertEqual(result.texts[0].content, "hello")

    def test_recognize_ocr_with_explicit_name(self):
        adapter1 = OCRAdapter(provider=MockOCRProvider(texts=["a"]))
        adapter2 = OCRAdapter(provider=MockOCRProvider(texts=["b"]))
        self.mgr.register_ocr_adapter("first", adapter1)
        self.mgr.register_ocr_adapter("second", adapter2)
        result = self.mgr.recognize_ocr(self.image, adapter_name="second")
        self.assertEqual(result.texts[0].content, "b")

    def test_recognize_ocr_no_adapter(self):
        result = self.mgr.recognize_ocr(self.image)
        self.assertFalse(result.success)
        self.assertIn("无可用", result.error)

    def test_detect_routes_to_adapter(self):
        adapter = DetectionAdapter(provider=MockDetectionProvider())
        self.mgr.register_detection_adapter("default", adapter)
        result = self.mgr.detect(self.image)
        self.assertTrue(result.success)
        self.assertGreater(len(result.objects), 0)

    def test_detect_no_adapter(self):
        result = self.mgr.detect(self.image)
        self.assertFalse(result.success)
        self.assertIn("无可用", result.error)

    def test_recognize_ocr_exception_isolated(self):
        """Adapter 异常被 Manager 捕获"""
        from backend.vision.perception.adapters.ocr_adapter import OCRAdapter as Impl
        # 注册一个会抛异常的 Adapter (Mock, 直接调用 recognize 让它内部抛)
        # 这里测试 Manager 层的 try/except: 注入一个抛异常的 Mock
        class BadAdapter(Impl):
            def recognize(self, image, options=None):
                raise RuntimeError("boom")

        self.mgr.register_ocr_adapter("bad", BadAdapter())
        result = self.mgr.recognize_ocr(self.image)
        self.assertFalse(result.success)
        self.assertIn("Manager 捕获异常", result.error)

    def test_register_defaults_includes_mock(self):
        """默认注册应包含 Mock Adapter"""
        self.mgr.register_defaults(include_mock=True)
        # 默认环境无 PaddleOCR / YOLO, 应回退到 mock
        self.assertGreaterEqual(len(self.mgr.list_ocr_adapters()), 1)
        self.assertGreaterEqual(len(self.mgr.list_detection_adapters()), 1)

    def test_register_defaults_idempotent(self):
        """重复调用 register_defaults 不重复注册"""
        self.mgr.register_defaults()
        n1 = len(self.mgr.list_ocr_adapters())
        self.mgr.register_defaults()
        n2 = len(self.mgr.list_ocr_adapters())
        self.assertEqual(n1, n2)

    def test_get_default_ocr_adapter(self):
        adapter = OCRAdapter(provider=MockOCRProvider())
        self.mgr.register_ocr_adapter("default", adapter)
        default = self.mgr.get_default_ocr_adapter()
        self.assertIsNotNone(default)

    def test_get_default_ocr_adapter_none(self):
        self.assertIsNone(self.mgr.get_default_ocr_adapter())

    def test_list_names(self):
        self.mgr.register_ocr_adapter("a", OCRAdapter())
        self.mgr.register_ocr_adapter("b", OCRAdapter(), override=True)
        names = self.mgr.list_ocr_names()
        # 第二个会覆盖 (因 override=True 但 name 相同实例)
        # 实际上注册不同 name
        self.assertIn("a", names)
        self.assertIn("b", names)

    def test_status(self):
        self.mgr.register_defaults(include_mock=True)
        status = self.mgr.status()
        self.assertIn("ocr_adapters_count", status)
        self.assertIn("detection_adapters_count", status)
        self.assertTrue(status["default_registered"])

    def test_reset(self):
        self.mgr.register_defaults(include_mock=True)
        self.mgr.reset()
        self.assertEqual(len(self.mgr.list_ocr_adapters()), 0)
        self.assertFalse(self.mgr._default_registered)


class TestPerceptionManagerSingleton(unittest.TestCase):

    def setUp(self):
        reset_manager()

    def tearDown(self):
        reset_manager()

    def test_get_manager_singleton(self):
        mgr1 = get_manager()
        mgr2 = get_manager()
        self.assertIs(mgr1, mgr2)

    def test_get_manager_registers_defaults(self):
        mgr = get_manager()
        self.assertGreaterEqual(len(mgr.list_ocr_adapters()), 1)

    def test_reset_manager(self):
        mgr1 = get_manager()
        reset_manager()
        mgr2 = get_manager()
        self.assertIsNot(mgr1, mgr2)


if __name__ == "__main__":
    unittest.main()
