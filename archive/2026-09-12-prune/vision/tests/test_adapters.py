"""
单元测试: adapters - Screen / Camera / Mock
覆盖: 可用性 / 采集 / 区域 / resize / 异常处理 / Mock 失败模式
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from backend.vision.adapters.mock_adapter import MockVisionAdapter
from backend.vision.adapters.screen_adapter import ScreenAdapter
from backend.vision.adapters.camera_adapter import CameraAdapter
from backend.vision.schema import (
    VisionCaptureRequest,
    VisionSource,
    VisionStatus,
)


class TestMockAdapter(unittest.TestCase):
    """MockVisionAdapter (无外部依赖, 主测试对象)"""

    def test_default_available(self):
        a = MockVisionAdapter()
        self.assertTrue(a.is_available())

    def test_capture_ok(self):
        a = MockVisionAdapter(width=640, height=480)
        req = VisionCaptureRequest(source="mock")
        frame = a.capture(req)
        self.assertTrue(frame.is_ok)
        self.assertEqual(frame.source, "mock")
        self.assertEqual(frame.width, 640)
        self.assertEqual(frame.height, 480)
        self.assertEqual(frame.channels, 3)
        self.assertIsInstance(frame.image, np.ndarray)

    def test_capture_returns_bgr(self):
        a = MockVisionAdapter(width=10, height=10)
        req = VisionCaptureRequest(source="mock")
        frame = a.capture(req)
        self.assertEqual(frame.image.shape, (10, 10, 3))

    def test_capture_with_resize(self):
        a = MockVisionAdapter(width=640, height=480)
        req = VisionCaptureRequest(
            source="mock",
            resize={"width": 100, "height": 100},
        )
        frame = a.capture(req)
        self.assertTrue(frame.is_ok)
        self.assertEqual(frame.width, 100)
        self.assertEqual(frame.height, 100)

    def test_capture_with_region(self):
        a = MockVisionAdapter(width=640, height=480)
        req = VisionCaptureRequest(
            source="mock",
            region={"x": 0, "y": 0, "w": 100, "h": 100},
        )
        frame = a.capture(req)
        self.assertTrue(frame.is_ok)
        self.assertEqual(frame.width, 100)
        self.assertEqual(frame.height, 100)

    def test_capture_exception_mode(self):
        """exception 模式: 抛异常 → 转错误帧"""
        a = MockVisionAdapter(mode="exception", error_msg="模拟异常")
        req = VisionCaptureRequest(source="mock")
        frame = a.capture(req)
        self.assertFalse(frame.is_ok)
        self.assertEqual(frame.status, VisionStatus.ERROR.value)
        self.assertIn("模拟异常", frame.error)

    def test_capture_error_mode(self):
        """error 模式: 返回错误帧"""
        a = MockVisionAdapter(mode="error", error_msg="模拟错误")
        req = VisionCaptureRequest(source="mock")
        frame = a.capture(req)
        self.assertFalse(frame.is_ok)

    def test_unavailable_adapter(self):
        """available=False → NO_DEVICE 错误帧"""
        a = MockVisionAdapter(available=False)
        req = VisionCaptureRequest(source="mock")
        frame = a.capture(req)
        self.assertFalse(frame.is_ok)
        self.assertEqual(frame.status, VisionStatus.NO_DEVICE.value)

    def test_capture_count_limit(self):
        """达到采集上限后转不可用"""
        a = MockVisionAdapter(capture_count_limit=2)
        req = VisionCaptureRequest(source="mock")
        # 前两次成功
        f1 = a.capture(req)
        f2 = a.capture(req)
        self.assertTrue(f1.is_ok)
        self.assertTrue(f2.is_ok)
        # 第三次失败
        f3 = a.capture(req)
        self.assertFalse(f3.is_ok)

    def test_list_devices(self):
        a = MockVisionAdapter(width=640, height=480)
        devices = a.list_devices()
        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0]["type"], "mock")

    def test_list_devices_unavailable(self):
        a = MockVisionAdapter(available=False)
        self.assertEqual(len(a.list_devices()), 0)

    def test_set_mode_runtime(self):
        a = MockVisionAdapter()
        self.assertTrue(a.capture(VisionCaptureRequest(source="mock")).is_ok)
        a.set_mode("exception", error_msg="切换后异常")
        f = a.capture(VisionCaptureRequest(source="mock"))
        self.assertFalse(f.is_ok)

    def test_reset(self):
        a = MockVisionAdapter(capture_count_limit=1)
        a.capture(VisionCaptureRequest(source="mock"))
        a.capture(VisionCaptureRequest(source="mock"))  # 触发上限
        a.reset()
        f = a.capture(VisionCaptureRequest(source="mock"))
        self.assertTrue(f.is_ok)

    def test_get_info(self):
        a = MockVisionAdapter(width=320, height=240)
        info = a.get_info()
        self.assertEqual(info["name"], "MockVisionAdapter")
        self.assertEqual(info["source"], "mock")
        self.assertTrue(info["available"])
        self.assertEqual(info["library"], "mock")

    def test_unique_frame_ids(self):
        a = MockVisionAdapter()
        ids = set()
        for _ in range(5):
            f = a.capture(VisionCaptureRequest(source="mock"))
            ids.add(f.id)
        self.assertEqual(len(ids), 5)

    def test_metadata_includes_latency(self):
        a = MockVisionAdapter()
        f = a.capture(VisionCaptureRequest(source="mock"))
        self.assertIn("latency_ms", f.metadata)
        self.assertGreaterEqual(f.metadata["latency_ms"], 0)


class TestScreenAdapter(unittest.TestCase):
    """ScreenAdapter (依赖 mss, 无屏幕环境可能不可用)"""

    def setUp(self):
        self.adapter = ScreenAdapter()

    def test_is_available_returns_bool(self):
        """可用性检查应返回 bool, 不抛异常"""
        result = self.adapter.is_available()
        self.assertIsInstance(result, bool)

    def test_capture_returns_frame(self):
        """如可用, 采集应返回帧; 否则返回错误帧"""
        req = VisionCaptureRequest(source="screen")
        frame = self.adapter.capture(req)
        self.assertIsNotNone(frame)
        if self.adapter.is_available():
            self.assertTrue(frame.is_ok)
            self.assertEqual(frame.source, "screen")
            self.assertIsInstance(frame.image, np.ndarray)
        else:
            # 不可用时返回错误帧, 不崩溃
            self.assertFalse(frame.is_ok)

    def test_get_info(self):
        info = self.adapter.get_info()
        self.assertEqual(info["name"], "ScreenAdapter")
        self.assertEqual(info["source"], "screen")
        self.assertEqual(info["library"], "mss")


class TestCameraAdapter(unittest.TestCase):
    """CameraAdapter (依赖 cv2 + 摄像头, 无设备环境返回错误帧)"""

    def setUp(self):
        self.adapter = CameraAdapter(max_detect=2)

    def test_is_available_returns_bool(self):
        result = self.adapter.is_available()
        self.assertIsInstance(result, bool)

    def test_capture_no_device_returns_error(self):
        """无摄像头时返回 NO_DEVICE 错误帧"""
        if not self.adapter.is_available():
            req = VisionCaptureRequest(source="camera", device_index=0)
            frame = self.adapter.capture(req)
            self.assertFalse(frame.is_ok)
            # 应为 NO_DEVICE 或 ERROR
            self.assertIn(frame.status, [VisionStatus.NO_DEVICE.value, VisionStatus.ERROR.value])

    def test_get_info(self):
        info = self.adapter.get_info()
        self.assertEqual(info["name"], "CameraAdapter")
        self.assertEqual(info["source"], "camera")
        self.assertEqual(info["library"], "cv2")


if __name__ == "__main__":
    unittest.main(verbosity=2)
