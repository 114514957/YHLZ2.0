"""
单元测试: adapters/ocr_adapter.py + adapters/detection_adapter.py
覆盖: 默认 Mock Provider / 切换 Provider / Provider 信息暴露
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
from backend.vision.perception.providers.mock_provider import (
    MockDetectionProvider,
    MockOCRProvider,
)


class TestOCRAdapter(unittest.TestCase):

    def setUp(self):
        self.image = np.zeros((100, 200, 3), dtype=np.uint8)

    def test_default_uses_mock(self):
        """未指定 Provider 时默认 Mock"""
        adapter = OCRAdapter()
        self.assertTrue(adapter.is_available())
        result = adapter.recognize(self.image)
        self.assertTrue(result.success)
        self.assertEqual(result.provider, "mock")

    def test_explicit_provider(self):
        adapter = OCRAdapter(provider=MockOCRProvider(texts=["hi"]))
        result = adapter.recognize(self.image)
        self.assertEqual(len(result.texts), 1)
        self.assertEqual(result.texts[0].content, "hi")

    def test_set_provider_runtime(self):
        adapter = OCRAdapter()
        adapter.set_provider(MockOCRProvider(texts=["new"]))
        result = adapter.recognize(self.image)
        self.assertEqual(result.texts[0].content, "new")

    def test_get_info(self):
        adapter = OCRAdapter()
        info = adapter.get_info()
        self.assertEqual(info["name"], "OCRAdapter")
        self.assertEqual(info["type"], "ocr")
        self.assertEqual(info["default_provider"], "mock")
        self.assertIn("provider", info)

    def test_recognize_with_options(self):
        adapter = OCRAdapter()
        opts = PerceptionOptions(language="en", min_confidence=0.0)
        result = adapter.recognize(self.image, opts)
        self.assertTrue(result.success)
        for t in result.texts:
            self.assertEqual(t.language, "en")


class TestDetectionAdapter(unittest.TestCase):

    def setUp(self):
        self.image = np.zeros((480, 640, 3), dtype=np.uint8)

    def test_default_uses_mock(self):
        adapter = DetectionAdapter()
        self.assertTrue(adapter.is_available())
        result = adapter.detect(self.image)
        self.assertTrue(result.success)
        self.assertEqual(result.provider, "mock")
        self.assertGreater(len(result.objects), 0)

    def test_explicit_provider(self):
        from backend.vision.perception.schema import BoundingBox, DetectedObject
        custom = [DetectedObject(name="cup", category="kitchen",
                                 position=BoundingBox(0, 0, 10, 10), confidence=0.9)]
        adapter = DetectionAdapter(provider=MockDetectionProvider(objects=custom))
        result = adapter.detect(self.image)
        self.assertEqual(len(result.objects), 1)
        self.assertEqual(result.objects[0].name, "cup")

    def test_get_info(self):
        adapter = DetectionAdapter()
        info = adapter.get_info()
        self.assertEqual(info["name"], "DetectionAdapter")
        self.assertEqual(info["type"], "detection")
        self.assertEqual(info["default_provider"], "mock")


if __name__ == "__main__":
    unittest.main()
