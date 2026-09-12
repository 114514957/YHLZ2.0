"""
集成测试: service.py - VisionService 完整流程
覆盖: 权限校验 → 采集 → 日志记录 完整流程 / 配置加载 / 状态查询 / 单例
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from backend.vision.adapters.mock_adapter import MockVisionAdapter
from backend.vision.logger import VisionLogger
from backend.vision.manager import VisionManager
from backend.vision.permission import PermissionChecker
from backend.vision.schema import (
    VisionCaptureRequest,
    VisionPermission,
    VisionSource,
    VisionStatus,
)
from backend.vision.service import VisionService, get_service, reset_service


class TestVisionServiceBasic(unittest.TestCase):

    def setUp(self):
        reset_service()
        # 用 Mock Adapter 隔离真实设备
        self.mgr = VisionManager()
        self.mock = MockVisionAdapter(width=100, height=100)
        self.mgr.register_adapter("mock", self.mock)
        self.perm = PermissionChecker()  # 默认拒绝
        self.vlog = VisionLogger(max_entries=100, enable_logging=False)
        self.svc = VisionService(
            manager=self.mgr,
            permission=self.perm,
            vlog=self.vlog,
        )

    def tearDown(self):
        reset_service()

    def test_capture_permission_denied(self):
        """权限拒绝 → 返回 PERMISSION_DENIED 帧"""
        req = VisionCaptureRequest(source="screen")
        result = self.svc.capture(req)
        self.assertFalse(result.is_ok)
        self.assertEqual(result.frame.status, VisionStatus.PERMISSION_DENIED.value)

    def test_capture_mock_allowed(self):
        """Mock 始终允许"""
        req = VisionCaptureRequest(source="mock")
        result = self.svc.capture(req)
        self.assertTrue(result.is_ok)

    def test_capture_after_enable_screen(self):
        """启用 screen 权限后, screen mock 可采集 (需注册 mock 为 screen)"""
        self.mgr.register_adapter("screen", MockVisionAdapter(), override=True)
        self.svc.update_permission(screen_enabled=True)
        req = VisionCaptureRequest(source="screen")
        result = self.svc.capture(req)
        self.assertTrue(result.is_ok)

    def test_capture_logs_start_and_success(self):
        """成功采集应记录 start + success 日志"""
        req = VisionCaptureRequest(source="mock")
        self.svc.capture(req)
        logs = self.vlog.query(limit=10)
        events = [e.event for e in logs]
        self.assertIn("start", events)
        self.assertIn("success", events)

    def test_capture_logs_fail_on_permission_denied(self):
        """权限拒绝应记录 fail 日志"""
        req = VisionCaptureRequest(source="screen")
        self.svc.capture(req)
        fail_logs = self.vlog.query(event="fail", limit=10)
        self.assertGreater(len(fail_logs), 0)
        self.assertEqual(fail_logs[0].status, VisionStatus.PERMISSION_DENIED.value)

    def test_capture_logs_fail_on_adapter_error(self):
        """Adapter 失败应记录 fail 日志"""
        bad_mock = MockVisionAdapter(mode="exception", error_msg="service 测试")
        self.mgr.register_adapter("mock", bad_mock, override=True)
        req = VisionCaptureRequest(source="mock")
        self.svc.capture(req)
        fail_logs = self.vlog.query(event="fail", limit=10)
        self.assertGreater(len(fail_logs), 0)

    def test_capture_screen_shortcut(self):
        """capture_screen 快捷方法"""
        # 默认权限拒绝
        result = self.svc.capture_screen()
        self.assertFalse(result.is_ok)
        # 启用后 (用 mock 替代)
        self.mgr.register_adapter("screen", MockVisionAdapter(), override=True)
        self.svc.update_permission(screen_enabled=True)
        result = self.svc.capture_screen()
        self.assertTrue(result.is_ok)

    def test_capture_mock_shortcut(self):
        """capture_mock 快捷方法"""
        result = self.svc.capture_mock(width=50, height=50)
        self.assertTrue(result.is_ok)
        self.assertEqual(result.frame.width, 50)

    def test_capture_camera_shortcut(self):
        """capture_camera 快捷方法 (无设备 → 错误)"""
        # 摄像头权限默认拒绝
        result = self.svc.capture_camera()
        self.assertFalse(result.is_ok)
        self.assertEqual(result.frame.status, VisionStatus.PERMISSION_DENIED.value)


class TestVisionServiceConfig(unittest.TestCase):

    def setUp(self):
        reset_service()
        self.svc = VisionService()

    def tearDown(self):
        reset_service()

    def test_load_config(self):
        config = {
            "screen_enabled": True,
            "camera_enabled": False,
            "capture_interval": 0.5,
            "save_policy": "disk",
        }
        self.svc.load_config(config)
        perm = self.svc.get_permission()
        self.assertTrue(perm["screen_enabled"])
        self.assertFalse(perm["camera_enabled"])
        self.assertEqual(perm["capture_interval"], 0.5)

    def test_load_permission(self):
        perm = VisionPermission(screen_enabled=True, camera_enabled=True)
        self.svc.load_permission(perm)
        d = self.svc.get_permission()
        self.assertTrue(d["screen_enabled"])

    def test_update_permission(self):
        result = self.svc.update_permission(screen_enabled=True)
        self.assertTrue(result.screen_enabled)

    def test_reset_permission(self):
        self.svc.update_permission(screen_enabled=True, camera_enabled=True)
        self.svc.reset_permission()
        d = self.svc.get_permission()
        self.assertFalse(d["screen_enabled"])
        self.assertFalse(d["camera_enabled"])


class TestVisionServiceLogs(unittest.TestCase):

    def setUp(self):
        reset_service()
        self.mgr = VisionManager()
        self.mgr.register_adapter("mock", MockVisionAdapter())
        self.svc = VisionService(manager=self.mgr)
        # mock 始终允许, 采集几次产生日志
        for _ in range(3):
            self.svc.capture(VisionCaptureRequest(source="mock"))

    def tearDown(self):
        reset_service()

    def test_get_logs(self):
        logs = self.svc.get_logs(limit=10)
        self.assertGreater(len(logs), 0)
        self.assertIn("event", logs[0])

    def test_get_log_stats(self):
        stats = self.svc.get_log_stats()
        self.assertGreater(stats["total"], 0)
        self.assertGreater(stats["success"], 0)

    def test_clear_logs(self):
        n = self.svc.clear_logs()
        self.assertGreater(n, 0)
        self.assertEqual(self.svc.get_log_stats()["total"], 0)


class TestVisionServiceStatus(unittest.TestCase):

    def setUp(self):
        reset_service()

    def tearDown(self):
        reset_service()

    def test_status_returns_dict(self):
        svc = get_service()
        s = svc.status()
        self.assertEqual(s["version"], "1.0.0")
        self.assertIn("permission", s)
        self.assertIn("manager", s)
        self.assertIn("log_stats", s)

    def test_status_initialized_flag(self):
        svc = VisionService()
        self.assertFalse(svc.status()["initialized"])
        svc.load_config({"screen_enabled": True})
        self.assertTrue(svc.status()["initialized"])


class TestVisionServiceDevices(unittest.TestCase):

    def setUp(self):
        reset_service()
        self.mgr = VisionManager()
        self.mgr.register_adapter("mock", MockVisionAdapter())
        self.svc = VisionService(manager=self.mgr)

    def tearDown(self):
        reset_service()

    def test_list_adapters(self):
        adapters = self.svc.list_adapters()
        self.assertGreaterEqual(len(adapters), 1)

    def test_list_devices_all(self):
        devices = self.svc.list_devices()
        self.assertIsInstance(devices, dict)

    def test_list_devices_by_source(self):
        devices = self.svc.list_devices("mock")
        self.assertIn("mock", devices)


class TestVisionServiceSingleton(unittest.TestCase):

    def setUp(self):
        reset_service()

    def tearDown(self):
        reset_service()

    def test_get_service_singleton(self):
        s1 = get_service()
        s2 = get_service()
        self.assertIs(s1, s2)

    def test_reset_service(self):
        s1 = get_service()
        reset_service()
        s2 = get_service()
        self.assertIsNot(s1, s2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
