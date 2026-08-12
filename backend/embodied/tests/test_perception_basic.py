"""
YHLZ Embodied AI V6.2 - 感知基础单元测试 (Perception Schema/Permission/Manager)

覆盖 (perception/schema.py, permission.py, manager.py, adapters):
    - 数据模型: PerceptionEvent/OCRResult/DetectionResult 校验
    - 权限: 默认拒绝 / 显式授权
    - 管理器: 注册/路由/异常隔离
    - 适配器: Mock 行为一致 / 摄像头 skipIf
"""
import unittest

from backend.embodied.companion.perception import (
    CameraAdapter,
    DetectionMockAdapter,
    DetectionResult,
    ManagerError,
    OCRMockAdapter,
    OCRResult,
    PERCEPTION_KINDS,
    PERCEPTION_SOURCES,
    PERCEPTION_TYPES,
    PerceptionEvent,
    PerceptionManager,
    PerceptionPermission,
    SchemaError,
    VisionMockAdapter,
)


class TestSchema(unittest.TestCase):
    """感知数据模型"""

    def test_perception_event_structure(self):
        ev = PerceptionEvent.create(
            source="camera", content={"kind": "ocr", "text": "hi"},
            confidence=0.9,
        )
        d = ev.to_dict()
        for key in ("type", "source", "content", "confidence",
                    "timestamp"):
            self.assertIn(key, d)
        self.assertEqual(d["type"], "vision")
        self.assertEqual(d["source"], "camera")

    def test_event_id_prefix(self):
        ev = PerceptionEvent.create(source="mock", content={},
                                    confidence=0.5)
        self.assertTrue(ev.event_id.startswith("pe_"))

    def test_validate_ok(self):
        ev = PerceptionEvent.create(source="mock", content={},
                                    confidence=0.5)
        ok, reason = ev.validate()
        self.assertTrue(ok)

    def test_validate_bad_type(self):
        ev = PerceptionEvent(ptype="bogus", source="mock",
                             content={}, confidence=0.5)
        ok, reason = ev.validate()
        self.assertFalse(ok)
        self.assertIn("类型", reason)

    def test_validate_bad_source(self):
        ev = PerceptionEvent(source="hacker", content={},
                             confidence=0.5)
        ok, reason = ev.validate()
        self.assertFalse(ok)
        self.assertIn("来源", reason)

    def test_validate_bad_confidence(self):
        ev = PerceptionEvent(source="mock", content={},
                             confidence=1.5)
        ok, reason = ev.validate()
        self.assertFalse(ok)

    def test_create_invalid_raises(self):
        with self.assertRaises(SchemaError):
            PerceptionEvent.create(source="hacker", content={},
                                   confidence=0.5)

    def test_types_whitelist(self):
        self.assertIn("vision", PERCEPTION_TYPES)
        self.assertIn("audio", PERCEPTION_TYPES)
        self.assertIn("text", PERCEPTION_TYPES)

    def test_sources_whitelist(self):
        for s in ("camera", "screen", "mic", "user_input", "mock"):
            self.assertIn(s, PERCEPTION_SOURCES)

    def test_kinds_whitelist(self):
        self.assertEqual(set(PERCEPTION_KINDS), {"ocr", "object"})

    def test_ocr_result(self):
        r = OCRResult(text="你好", confidence=0.9)
        d = r.to_dict()
        self.assertEqual(d["type"], "ocr")
        self.assertEqual(d["text"], "你好")
        self.assertEqual(d["confidence"], 0.9)

    def test_ocr_result_validation(self):
        with self.assertRaises(SchemaError):
            OCRResult(text="x", confidence=1.5)

    def test_ocr_from_dict(self):
        r = OCRResult.from_dict({"text": "abc", "confidence": 0.8})
        self.assertEqual(r.text, "abc")

    def test_detection_result(self):
        r = DetectionResult(objects=[{"label": "cup"}],
                            confidence=0.8)
        d = r.to_dict()
        self.assertEqual(d["type"], "object")
        self.assertEqual(len(d["objects"]), 1)

    def test_detection_result_validation(self):
        with self.assertRaises(SchemaError):
            DetectionResult(confidence=2.0)

    def test_detection_from_dict(self):
        r = DetectionResult.from_dict({
            "objects": [{"label": "cup"}], "confidence": 0.7,
        })
        self.assertEqual(r.objects[0]["label"], "cup")


class TestPermission(unittest.TestCase):
    """权限"""

    def test_default_all_denied(self):
        p = PerceptionPermission()
        for t in ("vision", "ocr", "detection"):
            allowed, reason = p.check(t)
            self.assertFalse(allowed)

    def test_default_reason(self):
        p = PerceptionPermission()
        allowed, reason = p.check("vision")
        self.assertIn("默认拒绝", reason)

    def test_enable_all(self):
        p = PerceptionPermission(enabled=True, vision_enabled=True,
                                 ocr_enabled=True,
                                 detection_enabled=True)
        for t in ("vision", "ocr", "detection"):
            allowed, reason = p.check(t)
            self.assertTrue(allowed, t)

    def test_enabled_but_ocr_off(self):
        p = PerceptionPermission(enabled=True)
        allowed, reason = p.check("ocr")
        self.assertFalse(allowed)
        self.assertIn("未授权", reason)

    def test_invalid_type(self):
        p = PerceptionPermission()
        allowed, reason = p.check("bogus")
        self.assertFalse(allowed)

    def test_update(self):
        p = PerceptionPermission()
        p.update(enabled=True, ocr_enabled=True)
        allowed, _ = p.check("ocr")
        self.assertTrue(allowed)

    def test_to_dict(self):
        p = PerceptionPermission()
        d = p.to_dict()
        self.assertEqual(d["mode"], "rule_based")
        self.assertFalse(d["enabled"])
        self.assertTrue(d["permission_required"])


class TestManager(unittest.TestCase):
    """管理器"""

    def setUp(self):
        self.mgr = PerceptionManager(
            default_ocr="ocr_mock", default_detect="detection_mock",
        )
        self.mgr.register(OCRMockAdapter())
        self.mgr.register(DetectionMockAdapter())

    def test_register(self):
        self.assertIn("ocr_mock", self.mgr.names())
        self.assertIn("detection_mock", self.mgr.names())

    def test_register_invalid(self):
        with self.assertRaises(ManagerError):
            self.mgr.register(None)

    def test_get(self):
        a = self.mgr.get("ocr_mock")
        self.assertEqual(a.name, "ocr_mock")

    def test_get_missing(self):
        self.assertIsNone(self.mgr.get("nope"))

    def test_unregister(self):
        self.assertTrue(self.mgr.unregister("ocr_mock"))
        self.assertFalse(self.mgr.unregister("ocr_mock"))

    def test_ocr_success(self):
        frame = self.mgr.ocr()
        self.assertEqual(frame["status"], "success")
        self.assertEqual(frame["type"], "ocr")
        self.assertTrue(frame["text"])

    def test_ocr_by_name(self):
        frame = self.mgr.ocr(adapter_name="ocr_mock")
        self.assertEqual(frame["adapter"], "ocr_mock")

    def test_ocr_no_adapter(self):
        m = PerceptionManager()
        frame = m.ocr()
        self.assertEqual(frame["status"], "error")

    def test_ocr_error_frame(self):
        m = PerceptionManager()
        m.register(OCRMockAdapter(error_mode=True))
        frame = m.ocr()
        self.assertEqual(frame["status"], "error")
        self.assertIn("error", frame)

    def test_detect_success(self):
        frame = self.mgr.detect()
        self.assertEqual(frame["status"], "success")
        self.assertEqual(frame["type"], "object")
        self.assertGreaterEqual(len(frame["objects"]), 1)

    def test_detect_error_frame(self):
        m = PerceptionManager()
        m.register(DetectionMockAdapter(error_mode=True))
        frame = m.detect()
        self.assertEqual(frame["status"], "error")

    def test_frame_id_prefix(self):
        frame = self.mgr.ocr()
        self.assertTrue(frame["frame_id"].startswith("ocr_"))

    def test_snapshot(self):
        snap = self.mgr.snapshot()
        self.assertEqual(snap["mode"], "rule_based")
        self.assertEqual(len(snap["adapters"]), 2)

    def test_clear(self):
        self.mgr.clear()
        self.assertEqual(self.mgr.names(), [])


class TestAdapters(unittest.TestCase):
    """适配器"""

    def test_ocr_mock_available(self):
        a = OCRMockAdapter()
        self.assertTrue(a.is_available())

    def test_ocr_mock_text(self):
        a = OCRMockAdapter(text="测试文本")
        r = a.ocr()
        self.assertEqual(r.text, "测试文本")

    def test_ocr_mock_error(self):
        a = OCRMockAdapter(error_mode=True)
        with self.assertRaises(RuntimeError):
            a.ocr()

    def test_detection_mock_objects(self):
        a = DetectionMockAdapter()
        r = a.detect()
        self.assertEqual(r.objects[0]["label"], "chair")

    def test_detection_mock_error(self):
        a = DetectionMockAdapter(error_mode=True)
        with self.assertRaises(RuntimeError):
            a.detect()

    def test_vision_mock(self):
        a = VisionMockAdapter()
        self.assertTrue(a.is_available())
        ocr = a.ocr()
        self.assertTrue(ocr.text)
        det = a.detect()
        self.assertGreaterEqual(len(det.objects), 1)

    def test_camera_available_or_skip(self):
        a = CameraAdapter()
        # 无摄像头环境: is_available=False; 有摄像头: True
        self.assertIsInstance(a.is_available(), bool)

    def test_camera_info(self):
        a = CameraAdapter()
        info = a.get_info()
        self.assertEqual(info["name"], "camera")
        self.assertEqual(info["source"], "camera")


if __name__ == "__main__":
    unittest.main()
