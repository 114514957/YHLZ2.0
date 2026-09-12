"""
单元测试: manager.py - VisionManager
覆盖: 注册 / 注销 / 路由采集 / 设备查询 / 默认注册 / 单例
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from backend.vision.adapters.mock_adapter import MockVisionAdapter
from backend.vision.manager import VisionManager, VisionManagerError, get_manager, reset_manager
from backend.vision.schema import (
    VisionCaptureRequest,
    VisionSource,
    VisionStatus,
)


class TestVisionManager(unittest.TestCase):

    def setUp(self):
        reset_manager()
        self.mgr = VisionManager()
        self.mock = MockVisionAdapter(width=100, height=100)
        self.mgr.register_adapter("mock", self.mock)

    def tearDown(self):
        reset_manager()

    def test_register_adapter(self):
        self.assertTrue(self.mgr.has_adapter("mock"))
        self.assertIn("mock", self.mgr.list_sources())

    def test_register_duplicate_no_override(self):
        """重复注册 (override=False) 应抛异常"""
        with self.assertRaises(VisionManagerError):
            self.mgr.register_adapter("mock", MockVisionAdapter())

    def test_register_duplicate_with_override(self):
        """override=True 允许覆盖"""
        new_mock = MockVisionAdapter(width=200, height=200)
        self.mgr.register_adapter("mock", new_mock, override=True)
        adapter = self.mgr.get_adapter("mock")
        self.assertIs(adapter, new_mock)

    def test_unregister_adapter(self):
        ok = self.mgr.unregister_adapter("mock")
        self.assertTrue(ok)
        self.assertFalse(self.mgr.has_adapter("mock"))

    def test_unregister_nonexistent(self):
        ok = self.mgr.unregister_adapter("nonexistent")
        self.assertFalse(ok)

    def test_capture_routes_to_adapter(self):
        req = VisionCaptureRequest(source="mock")
        result = self.mgr.capture(req)
        self.assertTrue(result.is_ok)
        self.assertEqual(result.adapter, "MockVisionAdapter")

    def test_capture_unknown_source(self):
        req = VisionCaptureRequest(source="unknown")
        result = self.mgr.capture(req)
        self.assertFalse(result.is_ok)
        self.assertEqual(result.frame.status, VisionStatus.ERROR.value)
        self.assertEqual(result.adapter, "none")

    def test_capture_records_latency(self):
        req = VisionCaptureRequest(source="mock")
        result = self.mgr.capture(req)
        self.assertGreaterEqual(result.latency_ms, 0)

    def test_list_adapters(self):
        adapters = self.mgr.list_adapters()
        self.assertEqual(len(adapters), 1)
        self.assertEqual(adapters[0]["name"], "MockVisionAdapter")

    def test_list_devices(self):
        devices = self.mgr.list_devices("mock")
        self.assertIn("mock", devices)
        self.assertEqual(len(devices["mock"]), 1)

    def test_list_devices_all(self):
        devices = self.mgr.list_devices()
        self.assertIn("mock", devices)

    def test_list_devices_unknown_source(self):
        devices = self.mgr.list_devices("nonexistent")
        self.assertEqual(devices, {})

    def test_register_defaults(self):
        """注册默认 Adapter (mock + 尝试 screen + camera)"""
        mgr = VisionManager()
        mgr.register_defaults(include_mock=True)
        self.assertTrue(mgr.has_adapter("mock"))
        # screen / camera 视环境而定, 但至少 mock 必须有
        self.assertGreaterEqual(len(mgr.list_sources()), 1)

    def test_status(self):
        s = self.mgr.status()
        self.assertEqual(s["adapters_count"], 1)
        self.assertIn("mock", s["sources"])

    def test_get_adapter_returns_registered(self):
        adapter = self.mgr.get_adapter("mock")
        self.assertIs(adapter, self.mock)

    def test_get_adapter_nonexistent_returns_none(self):
        self.assertIsNone(self.mgr.get_adapter("nonexistent"))


class TestManagerSingleton(unittest.TestCase):

    def setUp(self):
        reset_manager()

    def tearDown(self):
        reset_manager()

    def test_get_manager_singleton(self):
        m1 = get_manager()
        m2 = get_manager()
        self.assertIs(m1, m2)

    def test_get_manager_has_defaults(self):
        mgr = get_manager()
        self.assertTrue(mgr.has_adapter("mock"))

    def test_reset_manager(self):
        m1 = get_manager()
        reset_manager()
        m2 = get_manager()
        self.assertIsNot(m1, m2)


class TestManagerExceptionIsolation(unittest.TestCase):
    """异常隔离: Adapter 抛异常时, Manager 不崩溃"""

    def setUp(self):
        reset_manager()
        self.mgr = VisionManager()
        # 注册 exception 模式的 Mock
        self.bad_mock = MockVisionAdapter(mode="exception", error_msg="Manager 测试异常")
        self.mgr.register_adapter("mock", self.bad_mock)

    def tearDown(self):
        reset_manager()

    def test_capture_does_not_raise(self):
        """Adapter 抛异常 → Manager 返回错误帧, 不抛"""
        req = VisionCaptureRequest(source="mock")
        result = self.mgr.capture(req)
        # BaseVisionAdapter 已捕获异常, 应为 ERROR 状态
        self.assertFalse(result.is_ok)


if __name__ == "__main__":
    unittest.main(verbosity=2)
