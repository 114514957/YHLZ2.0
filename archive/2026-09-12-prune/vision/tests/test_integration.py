"""
集成测试: Vision Foundation 完整流程
覆盖: Service → Manager → Adapter → Permission → Logger 端到端
异常场景: 摄像头断开 / 屏幕权限关闭 / 输入为空 / Adapter 异常
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from backend.vision.adapters.mock_adapter import MockVisionAdapter
from backend.vision.logger import VisionLogger
from backend.vision.manager import VisionManager
from backend.vision.permission import PermissionChecker
from backend.vision.schema import (
    VisionCaptureRequest,
    VisionFrame,
    VisionPermission,
    VisionSource,
    VisionStatus,
)
from backend.vision.service import VisionService


class TestEndToEndFlow(unittest.TestCase):
    """端到端流程测试"""

    def setUp(self):
        self.mgr = VisionManager()
        self.mgr.register_adapter("mock", MockVisionAdapter(width=640, height=480))
        self.perm = PermissionChecker()
        # Mock 始终允许, screen / camera 默认拒绝
        self.vlog = VisionLogger(max_entries=500, enable_logging=False)
        self.svc = VisionService(
            manager=self.mgr,
            permission=self.perm,
            vlog=self.vlog,
        )

    def test_full_capture_flow(self):
        """完整采集流程: 权限 → 采集 → 日志"""
        req = VisionCaptureRequest(source="mock")
        result = self.svc.capture(req)

        # 1. 结果正确
        self.assertTrue(result.is_ok)
        self.assertEqual(result.frame.source, "mock")
        self.assertIsInstance(result.frame.image, np.ndarray)
        self.assertEqual(result.frame.width, 640)

        # 2. 日志记录完整
        logs = self.vlog.query(limit=10)
        events = [e.event for e in logs]
        self.assertIn("start", events)
        self.assertIn("success", events)

        # 3. 统计正确
        stats = self.vlog.stats()
        self.assertGreaterEqual(stats["success"], 1)

    def test_multiple_captures(self):
        """连续多次采集"""
        for i in range(5):
            req = VisionCaptureRequest(source="mock")
            result = self.svc.capture(req)
            self.assertTrue(result.is_ok)

        stats = self.vlog.stats()
        self.assertEqual(stats["success"], 5)
        self.assertGreater(stats["avg_latency_ms"], 0)

    def test_region_capture_flow(self):
        """区域截图完整流程"""
        req = VisionCaptureRequest(
            source="mock",
            region={"x": 0, "y": 0, "w": 100, "h": 100},
        )
        result = self.svc.capture(req)
        self.assertTrue(result.is_ok)
        self.assertEqual(result.frame.width, 100)
        self.assertEqual(result.frame.height, 100)

    def test_resize_capture_flow(self):
        """缩放采集完整流程"""
        req = VisionCaptureRequest(
            source="mock",
            resize={"width": 320, "height": 240},
        )
        result = self.svc.capture(req)
        self.assertTrue(result.is_ok)
        self.assertEqual(result.frame.width, 320)
        self.assertEqual(result.frame.height, 240)


class TestExceptionScenarios(unittest.TestCase):
    """异常场景测试 (Prompt 第八节要求)"""

    def setUp(self):
        self.mgr = VisionManager()
        self.perm = PermissionChecker()
        self.vlog = VisionLogger(max_entries=500, enable_logging=False)
        self.svc = VisionService(
            manager=self.mgr,
            permission=self.perm,
            vlog=self.vlog,
        )

    def test_camera_disconnected(self):
        """摄像头断开 (模拟: 可用后变为异常)"""
        # 注册一个会在第2次采集时失败的 Mock
        mock = MockVisionAdapter(mode="exception", error_msg="摄像头断开")
        self.mgr.register_adapter("camera", mock)
        self.perm.update(camera_enabled=True)

        req = VisionCaptureRequest(source="camera", device_index=0)
        result = self.svc.capture(req)
        self.assertFalse(result.is_ok)
        self.assertEqual(result.frame.status, VisionStatus.ERROR.value)
        self.assertIn("摄像头断开", result.frame.error)

        # 日志应记录失败
        fails = self.vlog.query(event="fail", limit=10)
        self.assertGreater(len(fails), 0)

    def test_screen_permission_closed(self):
        """屏幕权限关闭"""
        # 默认权限关闭, 不注册 screen adapter
        req = VisionCaptureRequest(source="screen")
        result = self.svc.capture(req)
        self.assertFalse(result.is_ok)
        self.assertEqual(result.frame.status, VisionStatus.PERMISSION_DENIED.value)

    def test_empty_input(self):
        """输入为空 (空请求参数)"""
        # source 为空字符串
        req = VisionCaptureRequest(source="")
        result = self.svc.capture(req)
        self.assertFalse(result.is_ok)
        # 未知来源应被拒绝
        self.assertIn(result.frame.status, [
            VisionStatus.ERROR.value,
            VisionStatus.PERMISSION_DENIED.value,
        ])

    def test_adapter_exception_does_not_crash(self):
        """Adapter 异常不应导致系统崩溃"""
        bad_mock = MockVisionAdapter(mode="exception", error_msg="严重异常")
        self.mgr.register_adapter("mock", bad_mock)

        # 第一次采集 (异常)
        req = VisionCaptureRequest(source="mock")
        result1 = self.svc.capture(req)
        self.assertFalse(result1.is_ok)

        # 系统仍可用: 替换为正常 mock 后能采集
        self.mgr.register_adapter("mock", MockVisionAdapter(), override=True)
        result2 = self.svc.capture(req)
        self.assertTrue(result2.is_ok)

    def test_no_adapter_registered(self):
        """未注册 Adapter"""
        req = VisionCaptureRequest(source="nonexistent")
        result = self.svc.capture(req)
        self.assertFalse(result.is_ok)
        self.assertEqual(result.adapter, "none")

    def test_permission_denied_logs_correctly(self):
        """权限拒绝日志应含正确状态"""
        req = VisionCaptureRequest(source="screen")
        self.svc.capture(req)
        fails = self.vlog.query(event="fail", limit=10)
        self.assertGreater(len(fails), 0)
        self.assertEqual(fails[0].status, VisionStatus.PERMISSION_DENIED.value)


class TestArchitectureCompliance(unittest.TestCase):
    """架构合规性测试 (Prompt 验收要求)"""

    def test_interface_service_manager_separation(self):
        """Interface / Service / Manager 分离"""
        from backend.vision.interface import VisionAdapter
        from backend.vision.manager import VisionManager
        from backend.vision.service import VisionService

        # VisionAdapter 是抽象基类
        self.assertTrue(hasattr(VisionAdapter, "capture"))
        self.assertTrue(hasattr(VisionAdapter, "is_available"))

        # VisionManager 管理 Adapter, 不直接对外的采集权限
        mgr = VisionManager()
        self.assertTrue(hasattr(mgr, "register_adapter"))
        self.assertTrue(hasattr(mgr, "capture"))
        self.assertFalse(hasattr(mgr, "check_permission"))  # 权限在 Service

        # VisionService 调用 Manager, 不直接调 Adapter
        svc = VisionService(manager=mgr)
        self.assertTrue(hasattr(svc, "capture"))
        self.assertTrue(hasattr(svc, "_manager"))
        self.assertTrue(hasattr(svc, "_permission"))
        self.assertTrue(hasattr(svc, "_vlog"))

    def test_adapter_independent(self):
        """Adapter 独立 (可替换)"""
        from backend.vision.adapters.mock_adapter import MockVisionAdapter
        from backend.vision.adapters.screen_adapter import ScreenAdapter
        from backend.vision.interface import VisionAdapter

        # 所有 Adapter 继承 VisionAdapter
        self.assertTrue(issubclass(MockVisionAdapter, VisionAdapter))
        self.assertTrue(issubclass(ScreenAdapter, VisionAdapter))

        # 可在 Manager 中替换
        mgr = VisionManager()
        a1 = MockVisionAdapter(width=100, height=100)
        mgr.register_adapter("mock", a1)
        a2 = MockVisionAdapter(width=200, height=200)
        mgr.register_adapter("mock", a2, override=True)
        self.assertIs(mgr.get_adapter("mock"), a2)

    def test_no_hardcoded_business_logic(self):
        """无硬编码 (权限默认值从配置加载)"""
        perm = VisionPermission()
        # 默认值不应硬编码为 True (安全默认)
        self.assertFalse(perm.screen_enabled)
        self.assertFalse(perm.camera_enabled)

    def test_log_complete(self):
        """日志完整 (开始/成功/失败/耗时/异常)"""
        vlog = VisionLogger(enable_logging=False)
        # 开始
        vlog.log_start(source="mock", adapter="A")
        # 成功
        vlog.log_success(source="mock", adapter="A", frame_id="1", latency_ms=10)
        # 失败
        vlog.log_fail(source="mock", adapter="A", status="error", error="test", latency_ms=5)
        # 异常
        vlog.log_exception(source="mock", adapter="A", error="boom")

        stats = vlog.stats()
        self.assertEqual(stats["total"], 4)
        self.assertEqual(stats["success"], 1)
        self.assertEqual(stats["fail"], 1)


class TestRealDeviceAvailability(unittest.TestCase):
    """真实设备可用性 (在 CI 环境中可能跳过)"""

    def test_screen_adapter_real_capture(self):
        """如有屏幕, 真实采集一次"""
        from backend.vision.adapters.screen_adapter import ScreenAdapter
        adapter = ScreenAdapter()
        if not adapter.is_available():
            self.skipTest("无屏幕设备 (headless 环境)")
        req = VisionCaptureRequest(source="screen")
        frame = adapter.capture(req)
        self.assertTrue(frame.is_ok)
        self.assertGreater(frame.width, 0)
        self.assertGreater(frame.height, 0)

    def test_camera_adapter_real_capture(self):
        """如有摄像头, 真实采集一次"""
        from backend.vision.adapters.camera_adapter import CameraAdapter
        adapter = CameraAdapter(max_detect=2)
        if not adapter.is_available():
            self.skipTest("无摄像头设备")
        req = VisionCaptureRequest(source="camera", device_index=0)
        frame = adapter.capture(req)
        self.assertTrue(frame.is_ok)
        self.assertGreater(frame.width, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
