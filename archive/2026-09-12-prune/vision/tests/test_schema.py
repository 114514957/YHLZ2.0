"""
单元测试: schema.py - 视觉数据结构
覆盖: VisionFrame / VisionPermission / VisionCaptureRequest / VisionCaptureResult
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from backend.vision.schema import (
    VisionCaptureRequest,
    VisionCaptureResult,
    VisionFrame,
    VisionPermission,
    VisionSource,
    VisionStatus,
)


class TestVisionSource(unittest.TestCase):
    def test_enum_values(self):
        self.assertEqual(VisionSource.SCREEN.value, "screen")
        self.assertEqual(VisionSource.CAMERA.value, "camera")
        self.assertEqual(VisionSource.MOCK.value, "mock")
        self.assertEqual(VisionSource.FILE.value, "file")


class TestVisionStatus(unittest.TestCase):
    def test_enum_values(self):
        self.assertEqual(VisionStatus.OK.value, "ok")
        self.assertEqual(VisionStatus.ERROR.value, "error")
        self.assertEqual(VisionStatus.PERMISSION_DENIED.value, "denied")
        self.assertEqual(VisionStatus.NO_DEVICE.value, "no_device")
        self.assertEqual(VisionStatus.TIMEOUT.value, "timeout")
        self.assertEqual(VisionStatus.DISCONNECTED.value, "disconnected")


class TestVisionPermission(unittest.TestCase):
    def test_default_all_disabled(self):
        """默认权限: 全部关闭"""
        p = VisionPermission()
        self.assertFalse(p.screen_enabled)
        self.assertFalse(p.camera_enabled)
        self.assertEqual(p.save_policy, "memory")
        self.assertTrue(p.allow_region_capture)

    def test_to_dict(self):
        p = VisionPermission(screen_enabled=True)
        d = p.to_dict()
        self.assertTrue(d["screen_enabled"])
        self.assertFalse(d["camera_enabled"])
        self.assertIn("capture_interval", d)

    def test_from_dict(self):
        d = {"screen_enabled": True, "camera_enabled": True, "capture_interval": 0.5}
        p = VisionPermission.from_dict(d)
        self.assertTrue(p.screen_enabled)
        self.assertTrue(p.camera_enabled)
        self.assertEqual(p.capture_interval, 0.5)

    def test_from_dict_partial(self):
        """部分字段缺失时使用默认值"""
        p = VisionPermission.from_dict({})
        self.assertFalse(p.screen_enabled)
        self.assertEqual(p.capture_interval, 1.0)


class TestVisionFrame(unittest.TestCase):
    def test_default_values(self):
        f = VisionFrame()
        self.assertIsNotNone(f.id)
        self.assertEqual(f.source, "unknown")
        self.assertEqual(f.status, VisionStatus.OK.value)
        self.assertIsNone(f.image)
        self.assertIsNone(f.error)

    def test_is_ok_with_image(self):
        img = np.zeros((100, 100, 3), dtype=np.uint8)
        f = VisionFrame.create_ok(source="mock", image=img)
        self.assertTrue(f.is_ok)
        self.assertFalse(f.is_error)
        self.assertEqual(f.width, 100)
        self.assertEqual(f.height, 100)
        self.assertEqual(f.channels, 3)

    def test_is_error_without_image(self):
        f = VisionFrame.create_error(
            source="screen",
            status=VisionStatus.NO_DEVICE.value,
            error="无设备",
        )
        self.assertFalse(f.is_ok)
        self.assertTrue(f.is_error)
        self.assertIsNone(f.image)
        self.assertEqual(f.error, "无设备")

    def test_is_error_with_status_error(self):
        """status=ok 但 image=None 应为 error"""
        f = VisionFrame(status=VisionStatus.OK.value, image=None)
        self.assertFalse(f.is_ok)

    def test_to_dict_no_image(self):
        f = VisionFrame(source="mock", status=VisionStatus.OK.value, width=640, height=480)
        d = f.to_dict()
        self.assertNotIn("image_b64", d)
        self.assertEqual(d["source"], "mock")
        self.assertEqual(d["width"], 640)

    def test_to_dict_with_image(self):
        img = np.zeros((10, 10, 3), dtype=np.uint8)
        f = VisionFrame.create_ok(source="mock", image=img)
        d = f.to_dict(include_image=True)
        self.assertIn("image_b64", d)
        self.assertIsNotNone(d["image_b64"])

    def test_from_dict_roundtrip(self):
        img = np.zeros((10, 10, 3), dtype=np.uint8)
        f1 = VisionFrame.create_ok(source="mock", image=img, metadata={"test": True})
        d = f1.to_dict()
        f2 = VisionFrame.from_dict(d)
        self.assertEqual(f1.id, f2.id)
        self.assertEqual(f1.source, f2.source)
        self.assertEqual(f1.metadata, f2.metadata)

    def test_create_ok_grayscale(self):
        """灰度图 (2D) 的 channels 应为 1"""
        img = np.zeros((100, 100), dtype=np.uint8)
        f = VisionFrame.create_ok(source="mock", image=img)
        self.assertEqual(f.channels, 1)
        self.assertEqual(f.width, 100)

    def test_unique_ids(self):
        """每帧 ID 应唯一"""
        ids = {VisionFrame().id for _ in range(100)}
        self.assertEqual(len(ids), 100)


class TestVisionCaptureRequest(unittest.TestCase):
    def test_default(self):
        r = VisionCaptureRequest()
        self.assertEqual(r.source, "screen")
        self.assertIsNone(r.region)
        self.assertEqual(r.device_index, 0)

    def test_with_region(self):
        r = VisionCaptureRequest(source="screen", region={"x": 0, "y": 0, "w": 100, "h": 100})
        self.assertEqual(r.region["w"], 100)

    def test_to_dict(self):
        r = VisionCaptureRequest(source="camera", device_index=1)
        d = r.to_dict()
        self.assertEqual(d["source"], "camera")
        self.assertEqual(d["device_index"], 1)


class TestVisionCaptureResult(unittest.TestCase):
    def test_ok_result(self):
        img = np.zeros((100, 100, 3), dtype=np.uint8)
        frame = VisionFrame.create_ok(source="mock", image=img)
        r = VisionCaptureResult(frame=frame, latency_ms=15.5, adapter="MockAdapter")
        self.assertTrue(r.is_ok)
        self.assertEqual(r.adapter, "MockAdapter")

    def test_error_result(self):
        frame = VisionFrame.create_error("camera", VisionStatus.NO_DEVICE.value, "无设备")
        r = VisionCaptureResult(frame=frame, latency_ms=0.5, adapter="CameraAdapter")
        self.assertFalse(r.is_ok)

    def test_to_dict(self):
        img = np.zeros((10, 10, 3), dtype=np.uint8)
        frame = VisionFrame.create_ok(source="mock", image=img)
        r = VisionCaptureResult(frame=frame, latency_ms=10.0, adapter="Mock")
        d = r.to_dict()
        self.assertIn("frame", d)
        self.assertEqual(d["adapter"], "Mock")


if __name__ == "__main__":
    unittest.main(verbosity=2)
