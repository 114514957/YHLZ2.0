"""
单元测试: providers/mock_provider.py - Mock OCR / Detection Provider
覆盖: 正常识别 / 空结果 / 异常模式 / 可用性切换 / max_objects / min_confidence 过滤
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from backend.vision.perception.interface import PerceptionOptions
from backend.vision.perception.providers.base import ProviderError
from backend.vision.perception.providers.mock_provider import (
    MockDetectionProvider,
    MockOCRProvider,
)


class TestMockOCRProvider(unittest.TestCase):

    def setUp(self):
        self.provider = MockOCRProvider()
        self.image = np.zeros((100, 200, 3), dtype=np.uint8)

    def test_is_available(self):
        self.assertTrue(self.provider.is_available())

    def test_recognize_default(self):
        texts = self.provider.recognize_text(self.image)
        self.assertEqual(len(texts), 3)  # 默认 3 条文本
        self.assertGreater(texts[0].confidence, 0)
        self.assertIn("language", texts[0].__dict__)

    def test_recognize_with_options(self):
        opts = PerceptionOptions(language="en")
        texts = self.provider.recognize_text(self.image, opts)
        for t in texts:
            self.assertEqual(t.language, "en")

    def test_recognize_with_custom_texts(self):
        provider = MockOCRProvider(texts=["你好", "world"])
        texts = provider.recognize_text(self.image)
        self.assertEqual(len(texts), 2)
        self.assertEqual(texts[0].content, "你好")
        self.assertEqual(texts[1].content, "world")

    def test_recognize_empty_mode(self):
        provider = MockOCRProvider(mode="empty")
        texts = provider.recognize_text(self.image)
        self.assertEqual(texts, [])

    def test_recognize_exception_mode(self):
        provider = MockOCRProvider(mode="exception")
        with self.assertRaises(ProviderError):
            provider.recognize_text(self.image)

    def test_unavailable(self):
        provider = MockOCRProvider(available=False)
        self.assertFalse(provider.is_available())
        with self.assertRaises(ProviderError):
            provider.recognize_text(self.image)

    def test_position_based_on_image(self):
        texts = self.provider.recognize_text(self.image)
        # 第一条文本应有位置 (image 有效)
        self.assertIsNotNone(texts[0].position)
        self.assertEqual(texts[0].position.x, 10)

    def test_call_count(self):
        self.provider.recognize_text(self.image)
        self.provider.recognize_text(self.image)
        self.assertEqual(self.provider.call_count, 2)

    def test_set_mode(self):
        self.provider.set_mode("empty")
        texts = self.provider.recognize_text(self.image)
        self.assertEqual(texts, [])

    def test_set_available(self):
        self.provider.set_available(False)
        self.assertFalse(self.provider.is_available())

    def test_reset(self):
        self.provider.recognize_text(self.image)
        self.provider.reset()
        self.assertEqual(self.provider.call_count, 0)
        self.assertTrue(self.provider.is_available())

    def test_get_info(self):
        info = self.provider.get_info()
        self.assertEqual(info["name"], "mock")
        self.assertEqual(info["type"], "ocr")
        self.assertTrue(info["available"])
        self.assertEqual(info["mode"], "ok")
        self.assertIn("call_count", info)


class TestMockDetectionProvider(unittest.TestCase):

    def setUp(self):
        self.provider = MockDetectionProvider()
        self.image = np.zeros((480, 640, 3), dtype=np.uint8)

    def test_is_available(self):
        self.assertTrue(self.provider.is_available())

    def test_detect_default(self):
        objects = self.provider.detect_objects(self.image)
        self.assertEqual(len(objects), 3)  # 默认 3 个对象
        self.assertEqual(objects[0].name, "person")

    def test_detect_with_max_objects(self):
        opts = PerceptionOptions(max_objects=2)
        objects = self.provider.detect_objects(self.image, opts)
        self.assertEqual(len(objects), 2)

    def test_detect_with_min_confidence(self):
        opts = PerceptionOptions(min_confidence=0.85)
        objects = self.provider.detect_objects(self.image, opts)
        # 默认对象置信度: 0.92, 0.88, 0.75
        # >= 0.85 的: 0.92, 0.88 → 2 个
        self.assertEqual(len(objects), 2)

    def test_detect_empty_mode(self):
        provider = MockDetectionProvider(mode="empty")
        self.assertEqual(provider.detect_objects(self.image), [])

    def test_detect_exception_mode(self):
        provider = MockDetectionProvider(mode="exception")
        with self.assertRaises(ProviderError):
            provider.detect_objects(self.image)

    def test_unavailable(self):
        provider = MockDetectionProvider(available=False)
        with self.assertRaises(ProviderError):
            provider.detect_objects(self.image)

    def test_custom_objects(self):
        from backend.vision.perception.schema import BoundingBox, DetectedObject
        custom = [DetectedObject(name="cat", category="animal",
                                 position=BoundingBox(0, 0, 50, 50), confidence=0.99)]
        provider = MockDetectionProvider(objects=custom)
        objects = provider.detect_objects(self.image)
        self.assertEqual(len(objects), 1)
        self.assertEqual(objects[0].name, "cat")

    def test_call_count(self):
        self.provider.detect_objects(self.image)
        self.assertEqual(self.provider.call_count, 1)

    def test_reset(self):
        self.provider.detect_objects(self.image)
        self.provider.reset()
        self.assertEqual(self.provider.call_count, 0)

    def test_get_info(self):
        info = self.provider.get_info()
        self.assertEqual(info["name"], "mock")
        self.assertEqual(info["type"], "detection")
        self.assertIn("mode", info)


if __name__ == "__main__":
    unittest.main()
