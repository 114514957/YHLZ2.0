"""
单元测试: schema.py - Understanding 数据结构
覆盖: UnderstandingResult / UnderstandingSubject / SubjectPosition / 工厂方法 / 序列化
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from backend.vision.understanding.schema import (
    SceneType,
    SubjectPosition,
    UnderstandingRequest,
    UnderstandingResult,
    UnderstandingSource,
    UnderstandingStatus,
    UnderstandingSubject,
)


class TestSubjectPosition(unittest.TestCase):

    def test_defaults(self):
        pos = SubjectPosition()
        self.assertEqual(pos.x, 0)
        self.assertEqual(pos.y, 0)
        self.assertEqual(pos.w, 0)
        self.assertEqual(pos.h, 0)

    def test_to_dict_from_dict_roundtrip(self):
        pos = SubjectPosition(x=10, y=20, w=100, h=50)
        d = pos.to_dict()
        self.assertEqual(d, {"x": 10, "y": 20, "w": 100, "h": 50})
        pos2 = SubjectPosition.from_dict(d)
        self.assertEqual(pos2, pos)


class TestUnderstandingSubject(unittest.TestCase):

    def test_to_dict(self):
        s = UnderstandingSubject(
            name="window",
            category="ui",
            position=SubjectPosition(x=1, y=2, w=3, h=4),
            confidence=0.9,
        )
        d = s.to_dict()
        self.assertEqual(d["name"], "window")
        self.assertEqual(d["category"], "ui")
        self.assertEqual(d["position"], {"x": 1, "y": 2, "w": 3, "h": 4})
        self.assertEqual(d["confidence"], 0.9)

    def test_from_dict(self):
        d = {"name": "car", "category": "vehicle", "position": None, "confidence": 0.8}
        s = UnderstandingSubject.from_dict(d)
        self.assertEqual(s.name, "car")
        self.assertIsNone(s.position)

    def test_from_dict_with_position(self):
        d = {"name": "car", "category": "vehicle", "position": {"x": 1, "y": 2, "w": 3, "h": 4}, "confidence": 0.8}
        s = UnderstandingSubject.from_dict(d)
        self.assertIsNotNone(s.position)
        self.assertEqual(s.position.x, 1)


class TestUnderstandingResult(unittest.TestCase):

    def test_defaults(self):
        r = UnderstandingResult()
        self.assertFalse(r.success)
        self.assertEqual(r.status, UnderstandingStatus.OK.value)
        self.assertEqual(r.scene_type, SceneType.UNKNOWN.value)

    def test_is_ok(self):
        r = UnderstandingResult.create_ok(
            source="mock", scene_type="desktop", description="desc"
        )
        self.assertTrue(r.is_ok)
        self.assertFalse(r.is_error)

    def test_create_error(self):
        r = UnderstandingResult.create_error(
            source="vlm", status=UnderstandingStatus.ERROR.value, error="失败"
        )
        self.assertFalse(r.is_ok)
        self.assertTrue(r.is_error)
        self.assertEqual(r.status, UnderstandingStatus.ERROR.value)
        self.assertEqual(r.error, "失败")

    def test_to_dict_fields(self):
        r = UnderstandingResult.create_ok(
            source="describe",
            scene_type="desktop",
            description="桌面场景",
            subjects=[UnderstandingSubject(name="window", category="ui")],
            summary="桌面",
            confidence=0.9,
            processing_time=0.1,
        )
        d = r.to_dict()
        self.assertEqual(d["scene_type"], "desktop")
        self.assertEqual(d["description"], "桌面场景")
        self.assertEqual(d["summary"], "桌面")
        self.assertEqual(d["subject_count"], 1)
        self.assertEqual(d["subjects"][0]["name"], "window")
        self.assertEqual(d["processing_time"], 0.1)

    def test_from_dict_roundtrip(self):
        r = UnderstandingResult.create_ok(
            source="qa",
            scene_type="web",
            description="网页",
            subjects=[UnderstandingSubject(name="button", category="ui", confidence=0.7)],
            summary="网页内容",
            confidence=0.85,
            processing_time=0.2,
            metadata={"provider": "mock"},
        )
        d = r.to_dict()
        r2 = UnderstandingResult.from_dict(d)
        self.assertEqual(r2.scene_type, "web")
        self.assertEqual(r2.summary, "网页内容")
        self.assertEqual(len(r2.subjects), 1)
        self.assertEqual(r2.subjects[0].name, "button")
        self.assertEqual(r2.confidence, 0.85)
        self.assertEqual(r2.metadata["provider"], "mock")

    def test_subject_names(self):
        r = UnderstandingResult.create_ok(
            source="mock",
            scene_type="desktop",
            subjects=[
                UnderstandingSubject(name="a"),
                UnderstandingSubject(name="b"),
            ],
        )
        self.assertEqual(r.subject_names, ["a", "b"])

    def test_with_processing_time(self):
        r = UnderstandingResult.create_error(source="vlm", status="error", error="x")
        ret = r.with_processing_time(0.5)
        self.assertIs(ret, r)
        self.assertEqual(r.processing_time, 0.5)


class TestUnderstandingRequest(unittest.TestCase):

    def test_defaults(self):
        req = UnderstandingRequest()
        self.assertEqual(req.source, UnderstandingSource.VLM.value)
        self.assertEqual(req.language, "zh")
        self.assertEqual(req.max_tokens, 512)

    def test_to_dict(self):
        req = UnderstandingRequest(source="qa", image="img", question="有什么?", region={"x": 0, "y": 0, "w": 10, "h": 10})
        d = req.to_dict()
        self.assertEqual(d["source"], "qa")
        self.assertTrue(d["has_image"])
        self.assertTrue(d["has_question"])
        self.assertEqual(d["region"], {"x": 0, "y": 0, "w": 10, "h": 10})

    def test_to_dict_no_image(self):
        req = UnderstandingRequest()
        d = req.to_dict()
        self.assertFalse(d["has_image"])


class TestEnums(unittest.TestCase):

    def test_source_values(self):
        self.assertEqual(UnderstandingSource.VLM.value, "vlm")
        self.assertEqual(UnderstandingSource.MOCK.value, "mock")
        self.assertEqual(UnderstandingSource.DESCRIBE.value, "describe")
        self.assertEqual(UnderstandingSource.QA.value, "qa")

    def test_status_values(self):
        self.assertEqual(UnderstandingStatus.OK.value, "ok")
        self.assertEqual(UnderstandingStatus.PERMISSION_DENIED.value, "denied")
        self.assertEqual(UnderstandingStatus.NO_PROVIDER.value, "no_provider")
        self.assertEqual(UnderstandingStatus.TIMEOUT.value, "timeout")
        self.assertEqual(UnderstandingStatus.EMPTY_INPUT.value, "empty_input")

    def test_scene_types(self):
        for name in ["desktop", "document", "image", "web", "video", "game", "empty", "unknown"]:
            self.assertTrue(any(s.value == name for s in SceneType))


if __name__ == "__main__":
    unittest.main()
