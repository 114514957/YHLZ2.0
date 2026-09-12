"""
单元测试: permission.py - 权限控制
覆盖: 默认拒绝 / 启用开关 / 区域权限 / resize 校验 / 来源校验 / 动态更新
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from backend.vision.permission import PermissionChecker, PermissionError
from backend.vision.schema import (
    VisionCaptureRequest,
    VisionPermission,
    VisionSource,
    VisionStatus,
)


class TestPermissionDefault(unittest.TestCase):
    """默认权限: 全部拒绝"""

    def setUp(self):
        self.checker = PermissionChecker()

    def test_default_screen_denied(self):
        r = VisionCaptureRequest(source="screen")
        ok, _ = self.checker.check(r)
        self.assertFalse(ok)

    def test_default_camera_denied(self):
        r = VisionCaptureRequest(source="camera")
        ok, _ = self.checker.check(r)
        self.assertFalse(ok)

    def test_mock_always_allowed(self):
        r = VisionCaptureRequest(source="mock")
        ok, _ = self.checker.check(r)
        self.assertTrue(ok)


class TestPermissionEnabled(unittest.TestCase):
    """启用后允许"""

    def setUp(self):
        self.checker = PermissionChecker()
        self.checker.update(screen_enabled=True, camera_enabled=True)

    def test_screen_enabled(self):
        r = VisionCaptureRequest(source="screen")
        ok, _ = self.checker.check(r)
        self.assertTrue(ok)

    def test_camera_enabled(self):
        r = VisionCaptureRequest(source="camera")
        ok, _ = self.checker.check(r)
        self.assertTrue(ok)

    def test_unknown_source_denied(self):
        r = VisionCaptureRequest(source="unknown_source")
        ok, _ = self.checker.check(r)
        self.assertFalse(ok)


class TestPermissionRegion(unittest.TestCase):
    """区域截图权限"""

    def setUp(self):
        self.checker = PermissionChecker()
        self.checker.update(screen_enabled=True)

    def test_region_allowed_when_enabled(self):
        r = VisionCaptureRequest(
            source="screen",
            region={"x": 0, "y": 0, "w": 100, "h": 100},
        )
        ok, _ = self.checker.check(r)
        self.assertTrue(ok)

    def test_region_denied_when_disabled(self):
        self.checker.update(allow_region_capture=False)
        r = VisionCaptureRequest(
            source="screen",
            region={"x": 0, "y": 0, "w": 100, "h": 100},
        )
        ok, reason = self.checker.check(r)
        self.assertFalse(ok)
        self.assertIn("区域截图", reason)

    def test_region_invalid_size(self):
        r = VisionCaptureRequest(
            source="screen",
            region={"x": 0, "y": 0, "w": 0, "h": 100},
        )
        ok, reason = self.checker.check(r)
        self.assertFalse(ok)
        self.assertIn("尺寸非法", reason)

    def test_region_missing_field(self):
        r = VisionCaptureRequest(
            source="screen",
            region={"x": 0, "y": 0, "w": 100},  # 缺 h
        )
        ok, reason = self.checker.check(r)
        self.assertFalse(ok)
        self.assertIn("不完整", reason)

    def test_region_exceeds_max(self):
        self.checker.update(max_frame_width=500, max_frame_height=500)
        r = VisionCaptureRequest(
            source="screen",
            region={"x": 0, "y": 0, "w": 1000, "h": 100},
        )
        ok, reason = self.checker.check(r)
        self.assertFalse(ok)
        self.assertIn("超出限制", reason)


class TestPermissionResize(unittest.TestCase):
    """resize 校验"""

    def setUp(self):
        self.checker = PermissionChecker()
        self.checker.update(screen_enabled=True)

    def test_resize_valid(self):
        r = VisionCaptureRequest(
            source="screen",
            resize={"width": 640, "height": 480},
        )
        ok, _ = self.checker.check(r)
        self.assertTrue(ok)

    def test_resize_missing_field(self):
        r = VisionCaptureRequest(
            source="screen",
            resize={"width": 640},  # 缺 height
        )
        ok, reason = self.checker.check(r)
        self.assertFalse(ok)
        self.assertIn("不完整", reason)

    def test_resize_exceeds_max(self):
        self.checker.update(max_frame_width=500)
        r = VisionCaptureRequest(
            source="screen",
            resize={"width": 1000, "height": 480},
        )
        ok, _ = self.checker.check(r)
        self.assertFalse(ok)


class TestPermissionManagement(unittest.TestCase):
    """权限管理 (load / update / reset)"""

    def test_load_from_dict(self):
        c = PermissionChecker()
        c.load_from_dict({"screen_enabled": True, "camera_enabled": True})
        self.assertTrue(c.permission.screen_enabled)
        self.assertTrue(c.permission.camera_enabled)

    def test_load_from_permission(self):
        c = PermissionChecker()
        p = VisionPermission(screen_enabled=True)
        c.load_from_permission(p)
        self.assertTrue(c.permission.screen_enabled)

    def test_update_returns_new_permission(self):
        c = PermissionChecker()
        result = c.update(screen_enabled=True)
        self.assertTrue(result.screen_enabled)

    def test_reset(self):
        c = PermissionChecker()
        c.update(screen_enabled=True)
        c.reset()
        self.assertFalse(c.permission.screen_enabled)
        self.assertFalse(c.permission.camera_enabled)

    def test_to_dict(self):
        c = PermissionChecker()
        c.update(screen_enabled=True)
        d = c.to_dict()
        self.assertTrue(d["screen_enabled"])

    def test_check_source(self):
        c = PermissionChecker()
        c.update(camera_enabled=True)
        ok, _ = c.check_source("camera")
        self.assertTrue(ok)
        ok, _ = c.check_source("screen")
        self.assertFalse(ok)
        ok, _ = c.check_source("mock")
        self.assertTrue(ok)


if __name__ == "__main__":
    unittest.main(verbosity=2)
