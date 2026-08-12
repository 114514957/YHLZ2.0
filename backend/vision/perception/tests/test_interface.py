"""
单元测试: interface.py - 抽象接口
覆盖: PerceptionOptions / 抽象基类不可实例化 / get_info 默认实现
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from backend.vision.perception.interface import (
    DetectionAdapter,
    OCRAdapter,
    PerceptionAdapter,
    PerceptionAdapterError,
    PerceptionOptions,
)


class TestPerceptionOptions(unittest.TestCase):

    def test_default_values(self):
        opts = PerceptionOptions()
        self.assertEqual(opts.language, "zh")
        self.assertEqual(opts.min_confidence, 0.0)
        self.assertIsNone(opts.max_objects)
        self.assertEqual(opts.timeout, 10.0)
        self.assertEqual(opts.extra, {})

    def test_custom_values(self):
        opts = PerceptionOptions(
            language="en",
            min_confidence=0.5,
            max_objects=10,
            timeout=5.0,
            extra={"model": "paddleocr"},
        )
        self.assertEqual(opts.language, "en")
        self.assertEqual(opts.max_objects, 10)
        self.assertEqual(opts.extra["model"], "paddleocr")

    def test_to_dict(self):
        opts = PerceptionOptions(language="mixed", min_confidence=0.3, max_objects=5)
        d = opts.to_dict()
        self.assertEqual(d["language"], "mixed")
        self.assertEqual(d["min_confidence"], 0.3)
        self.assertEqual(d["max_objects"], 5)

    def test_from_dict(self):
        opts = PerceptionOptions.from_dict({
            "language": "en",
            "min_confidence": 0.7,
            "max_objects": 3,
        })
        self.assertEqual(opts.language, "en")
        self.assertEqual(opts.min_confidence, 0.7)
        self.assertEqual(opts.max_objects, 3)

    def test_roundtrip(self):
        opts1 = PerceptionOptions(language="zh", min_confidence=0.5, max_objects=10)
        d = opts1.to_dict()
        opts2 = PerceptionOptions.from_dict(d)
        self.assertEqual(opts1.language, opts2.language)
        self.assertEqual(opts1.min_confidence, opts2.min_confidence)
        self.assertEqual(opts1.max_objects, opts2.max_objects)


class TestAbstractClasses(unittest.TestCase):

    def test_ocr_adapter_cannot_instantiate(self):
        with self.assertRaises(TypeError):
            OCRAdapter()

    def test_detection_adapter_cannot_instantiate(self):
        with self.assertRaises(TypeError):
            DetectionAdapter()

    def test_perception_adapter_cannot_instantiate(self):
        with self.assertRaises(TypeError):
            PerceptionAdapter()

    def test_perception_adapter_error_is_exception(self):
        self.assertTrue(issubclass(PerceptionAdapterError, Exception))

    def test_subclass_must_implement_abstract(self):
        # 缺失 is_available / recognize 仍不可实例化
        class IncompleteAdapter(OCRAdapter):
            name = "incomplete"
        with self.assertRaises(TypeError):
            IncompleteAdapter()

    def test_complete_subclass_can_instantiate(self):
        class CompleteOCRAdapter(OCRAdapter):
            name = "complete"

            def is_available(self) -> bool:
                return True

            def recognize(self, image, options=None):
                from backend.vision.perception.schema import OCRResult
                return OCRResult(success=True)

        adapter = CompleteOCRAdapter()
        self.assertTrue(adapter.is_available())
        info = adapter.get_info()
        self.assertEqual(info["name"], "complete")
        self.assertEqual(info["type"], "ocr")
        self.assertTrue(info["available"])


if __name__ == "__main__":
    unittest.main()
