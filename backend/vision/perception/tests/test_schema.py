"""
单元测试: schema.py - 感知数据结构
覆盖: BoundingBox / DetectedObject / DetectedText / OCRResult / DetectionResult / PerceptionResult / PerceptionRequest
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from backend.vision.perception.schema import (
    BoundingBox,
    DetectedObject,
    DetectedText,
    DetectionResult,
    OCRResult,
    PerceptionRequest,
    PerceptionResult,
    PerceptionSource,
    PerceptionStatus,
)


class TestBoundingBox(unittest.TestCase):

    def test_default_values(self):
        box = BoundingBox()
        self.assertEqual(box.x, 0)
        self.assertEqual(box.y, 0)
        self.assertEqual(box.w, 0)
        self.assertEqual(box.h, 0)
        self.assertEqual(box.area, 0)

    def test_to_dict(self):
        box = BoundingBox(x=10, y=20, w=100, h=50)
        d = box.to_dict()
        self.assertEqual(d, {"x": 10, "y": 20, "w": 100, "h": 50})

    def test_from_dict(self):
        box = BoundingBox.from_dict({"x": 5, "y": 10, "w": 80, "h": 60})
        self.assertEqual(box.x, 5)
        self.assertEqual(box.w, 80)

    def test_area(self):
        box = BoundingBox(x=0, y=0, w=100, h=50)
        self.assertEqual(box.area, 5000)

    def test_from_dict_with_missing_keys(self):
        box = BoundingBox.from_dict({})
        self.assertEqual(box.x, 0)
        self.assertEqual(box.w, 0)

    def test_roundtrip(self):
        box1 = BoundingBox(x=1, y=2, w=3, h=4)
        d = box1.to_dict()
        box2 = BoundingBox.from_dict(d)
        self.assertEqual(box1, box2)


class TestDetectedObject(unittest.TestCase):

    def test_default_values(self):
        obj = DetectedObject()
        self.assertEqual(obj.name, "")
        self.assertEqual(obj.category, "")
        self.assertEqual(obj.confidence, 0.0)
        self.assertIsInstance(obj.position, BoundingBox)

    def test_to_dict(self):
        obj = DetectedObject(
            name="person",
            category="human",
            position=BoundingBox(x=10, y=20, w=100, h=200),
            confidence=0.95,
        )
        d = obj.to_dict()
        self.assertEqual(d["name"], "person")
        self.assertEqual(d["category"], "human")
        self.assertEqual(d["confidence"], 0.95)
        self.assertEqual(d["position"]["w"], 100)

    def test_from_dict(self):
        obj = DetectedObject.from_dict({
            "name": "car",
            "category": "vehicle",
            "position": {"x": 1, "y": 2, "w": 3, "h": 4},
            "confidence": 0.8,
        })
        self.assertEqual(obj.name, "car")
        self.assertEqual(obj.position.x, 1)
        self.assertEqual(obj.confidence, 0.8)

    def test_confidence_rounded(self):
        obj = DetectedObject(name="x", confidence=0.123456)
        d = obj.to_dict()
        self.assertEqual(d["confidence"], 0.1235)


class TestDetectedText(unittest.TestCase):

    def test_default_values(self):
        t = DetectedText()
        self.assertEqual(t.content, "")
        self.assertEqual(t.language, "unknown")
        self.assertEqual(t.confidence, 0.0)
        self.assertIsNone(t.position)

    def test_to_dict_with_position(self):
        t = DetectedText(
            content="你好",
            language="zh",
            confidence=0.9,
            position=BoundingBox(x=0, y=0, w=50, h=20),
        )
        d = t.to_dict()
        self.assertEqual(d["content"], "你好")
        self.assertEqual(d["language"], "zh")
        self.assertEqual(d["position"]["w"], 50)

    def test_to_dict_without_position(self):
        t = DetectedText(content="hello", language="en")
        d = t.to_dict()
        self.assertIsNone(d["position"])

    def test_from_dict(self):
        t = DetectedText.from_dict({
            "content": "test",
            "language": "en",
            "confidence": 0.5,
            "position": {"x": 1, "y": 2, "w": 3, "h": 4},
        })
        self.assertEqual(t.content, "test")
        self.assertEqual(t.position.x, 1)


class TestOCRResult(unittest.TestCase):

    def test_default_values(self):
        r = OCRResult()
        self.assertFalse(r.success)
        self.assertEqual(r.texts, [])
        self.assertEqual(r.processing_time_ms, 0.0)
        self.assertIsNone(r.error)
        self.assertEqual(r.provider, "unknown")

    def test_is_ok(self):
        self.assertFalse(OCRResult().is_ok)
        self.assertTrue(OCRResult(success=True).is_ok)

    def test_to_dict(self):
        r = OCRResult(
            success=True,
            texts=[DetectedText(content="hi", confidence=0.9)],
            processing_time_ms=12.3,
            provider="mock",
        )
        d = r.to_dict()
        self.assertTrue(d["success"])
        self.assertEqual(d["text_count"], 1)
        self.assertEqual(d["texts"][0]["content"], "hi")
        self.assertEqual(d["processing_time_ms"], 12.3)
        self.assertEqual(d["provider"], "mock")


class TestDetectionResult(unittest.TestCase):

    def test_default_values(self):
        r = DetectionResult()
        self.assertFalse(r.success)
        self.assertEqual(r.objects, [])

    def test_to_dict(self):
        r = DetectionResult(
            success=True,
            objects=[DetectedObject(name="person", confidence=0.9)],
            processing_time_ms=5.5,
            provider="yolo",
        )
        d = r.to_dict()
        self.assertEqual(d["object_count"], 1)
        self.assertEqual(d["objects"][0]["name"], "person")
        self.assertEqual(d["provider"], "yolo")


class TestPerceptionResult(unittest.TestCase):

    def test_default_values(self):
        r = PerceptionResult()
        self.assertFalse(r.success)
        self.assertEqual(r.status, PerceptionStatus.OK.value)
        self.assertEqual(r.source, "unknown")
        self.assertEqual(r.objects, [])
        self.assertEqual(r.text, [])

    def test_create_ok(self):
        r = PerceptionResult.create_ok(
            source="ocr",
            text=[DetectedText(content="hi", confidence=0.9)],
            processing_time=0.05,
        )
        self.assertTrue(r.is_ok)
        self.assertEqual(r.confidence, 0.9)
        self.assertEqual(r.text_content, "hi")

    def test_create_ok_with_objects_and_text(self):
        r = PerceptionResult.create_ok(
            source="combined",
            objects=[DetectedObject(name="x", confidence=0.8)],
            text=[DetectedText(content="y", confidence=0.6)],
        )
        # 平均置信度 = (0.8 + 0.6) / 2
        self.assertAlmostEqual(r.confidence, 0.7)
        self.assertEqual(len(r.objects), 1)
        self.assertEqual(len(r.text), 1)

    def test_create_error(self):
        r = PerceptionResult.create_error(
            source="ocr",
            status=PerceptionStatus.PERMISSION_DENIED.value,
            error="权限不足",
        )
        self.assertFalse(r.is_ok)
        self.assertTrue(r.is_error)
        self.assertEqual(r.status, PerceptionStatus.PERMISSION_DENIED.value)
        self.assertEqual(r.error, "权限不足")

    def test_from_ocr_success(self):
        ocr = OCRResult(
            success=True,
            texts=[DetectedText(content="hello", confidence=0.95)],
            processing_time_ms=12.0,
            provider="mock",
        )
        r = PerceptionResult.from_ocr(ocr)
        self.assertTrue(r.is_ok)
        self.assertEqual(r.source, PerceptionSource.OCR.value)
        self.assertEqual(r.text[0].content, "hello")
        self.assertEqual(r.processing_time, 0.012)
        self.assertEqual(r.metadata["provider"], "mock")

    def test_from_ocr_failure(self):
        ocr = OCRResult(success=False, error="OCR 失败")
        r = PerceptionResult.from_ocr(ocr)
        self.assertFalse(r.is_ok)
        self.assertEqual(r.status, PerceptionStatus.ERROR.value)
        self.assertEqual(r.error, "OCR 失败")

    def test_from_detection_success(self):
        det = DetectionResult(
            success=True,
            objects=[DetectedObject(name="car", confidence=0.88)],
            processing_time_ms=20.0,
            provider="yolo",
        )
        r = PerceptionResult.from_detection(det)
        self.assertTrue(r.is_ok)
        self.assertEqual(r.source, PerceptionSource.DETECTION.value)
        self.assertEqual(r.objects[0].name, "car")
        self.assertEqual(r.object_names, ["car"])

    def test_text_content_property(self):
        r = PerceptionResult.create_ok(
            source="ocr",
            text=[
                DetectedText(content="line1"),
                DetectedText(content="line2"),
                DetectedText(content=""),  # 空, 应被过滤
            ],
        )
        self.assertEqual(r.text_content, "line1\nline2")

    def test_to_dict(self):
        r = PerceptionResult.create_ok(
            source="ocr",
            text=[DetectedText(content="hi", confidence=0.9)],
            processing_time=0.05,
        )
        d = r.to_dict()
        self.assertEqual(d["source"], "ocr")
        self.assertEqual(d["text_count"], 1)
        self.assertEqual(d["text_content"], "hi")
        self.assertIn("object_count", d)
        self.assertIn("confidence", d)

    def test_from_dict_roundtrip(self):
        r1 = PerceptionResult.create_ok(
            source="combined",
            objects=[DetectedObject(name="x", confidence=0.8)],
            text=[DetectedText(content="hi", confidence=0.9)],
            processing_time=0.05,
        )
        d = r1.to_dict()
        r2 = PerceptionResult.from_dict(d)
        self.assertEqual(r2.source, "combined")
        self.assertEqual(len(r2.objects), 1)
        self.assertEqual(len(r2.text), 1)
        self.assertEqual(r2.objects[0].name, "x")
        self.assertEqual(r2.text[0].content, "hi")


class TestPerceptionRequest(unittest.TestCase):

    def test_default_values(self):
        req = PerceptionRequest()
        self.assertEqual(req.source, PerceptionSource.OCR.value)
        self.assertIsNone(req.image)
        self.assertEqual(req.language, "zh")
        self.assertEqual(req.min_confidence, 0.0)
        self.assertIsNone(req.max_objects)
        self.assertIsNone(req.region)

    def test_to_dict(self):
        req = PerceptionRequest(
            source="detection",
            language="en",
            min_confidence=0.5,
            max_objects=10,
            region={"x": 0, "y": 0, "w": 100, "h": 100},
        )
        d = req.to_dict()
        self.assertEqual(d["source"], "detection")
        self.assertEqual(d["language"], "en")
        self.assertEqual(d["min_confidence"], 0.5)
        self.assertEqual(d["max_objects"], 10)
        self.assertFalse(d["has_image"])


class TestEnums(unittest.TestCase):

    def test_perception_source_values(self):
        self.assertEqual(PerceptionSource.OCR.value, "ocr")
        self.assertEqual(PerceptionSource.DETECTION.value, "detection")
        self.assertEqual(PerceptionSource.MOCK.value, "mock")
        self.assertEqual(PerceptionSource.COMBINED.value, "combined")

    def test_perception_status_values(self):
        self.assertEqual(PerceptionStatus.OK.value, "ok")
        self.assertEqual(PerceptionStatus.ERROR.value, "error")
        self.assertEqual(PerceptionStatus.PERMISSION_DENIED.value, "denied")
        self.assertEqual(PerceptionStatus.NO_PROVIDER.value, "no_provider")
        self.assertEqual(PerceptionStatus.TIMEOUT.value, "timeout")
        self.assertEqual(PerceptionStatus.EMPTY_INPUT.value, "empty_input")


if __name__ == "__main__":
    unittest.main()
