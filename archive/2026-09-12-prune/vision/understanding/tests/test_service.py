"""
集成测试: service.py - UnderstandingService 完整流程
覆盖: 权限校验 → 理解 → 日志 / 配置加载 / 状态 / 快捷方法 / 截屏理解 / 单例
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from backend.vision.understanding.adapters.vlm_adapter import VLMAdapter
from backend.vision.understanding.logger import UnderstandingLogger
from backend.vision.understanding.manager import UnderstandingManager
from backend.vision.understanding.permission import PermissionChecker
from backend.vision.understanding.providers.mock_provider import MockVLMProvider
from backend.vision.understanding.schema import (
    SceneType,
    UnderstandingRequest,
    UnderstandingSource,
    UnderstandingStatus,
)
from backend.vision.understanding.service import (
    UnderstandingService,
    get_service,
    reset_service,
)


class TestUnderstandingServiceBasic(unittest.TestCase):

    def setUp(self):
        reset_service()
        self.mgr = UnderstandingManager()
        self.mgr.register_adapter(
            "mock", VLMAdapter(provider=MockVLMProvider())
        )
        self.perm = PermissionChecker()
        self.ulog = UnderstandingLogger(max_entries=100, enable_logging=False)
        self.svc = UnderstandingService(
            manager=self.mgr,
            permission=self.perm,
            ulog=self.ulog,
        )
        self.svc.update_permission(understanding_enabled=True)
        self.svc._initialized = True
        self.image = np.zeros((100, 200, 3), dtype=np.uint8)

    def tearDown(self):
        reset_service()

    # ── 权限流程 ──────────────────────────────────────────────────
    def test_understand_permission_denied(self):
        """关闭权限 → 返回 PERMISSION_DENIED"""
        self.svc.reset_permission()
        req = UnderstandingRequest(image=self.image)
        result = self.svc.understand(req)
        self.assertFalse(result.is_ok)
        self.assertEqual(result.status, UnderstandingStatus.PERMISSION_DENIED.value)

    def test_understand_permission_allowed(self):
        """开启权限 → 正常执行"""
        req = UnderstandingRequest(image=self.image)
        result = self.svc.understand(req)
        self.assertTrue(result.is_ok)
        self.assertEqual(result.scene_type, SceneType.DESKTOP.value)

    def test_understand_logs_start_and_success(self):
        req = UnderstandingRequest(image=self.image)
        self.svc.understand(req)
        logs = self.ulog.query(limit=10)
        events = [e.event for e in logs]
        self.assertIn("start", events)
        self.assertIn("success", events)

    def test_understand_logs_fail_on_denied(self):
        self.svc.reset_permission()
        req = UnderstandingRequest(image=self.image)
        self.svc.understand(req)
        fail_logs = self.ulog.query(event="fail", limit=10)
        self.assertGreater(len(fail_logs), 0)

    # ── 来源路由 ──────────────────────────────────────────────────
    def test_understand_describe_source(self):
        req = UnderstandingRequest(source=UnderstandingSource.DESCRIBE.value, image=self.image)
        result = self.svc.understand(req)
        self.assertTrue(result.is_ok)
        self.assertGreater(len(result.description), 0)

    def test_understand_qa_source(self):
        req = UnderstandingRequest(
            source=UnderstandingSource.QA.value,
            image=self.image,
            question="屏幕上有几个窗口?",
        )
        result = self.svc.understand(req)
        self.assertTrue(result.is_ok)
        self.assertIn("回答", result.summary)

    # ── 快捷方法 ──────────────────────────────────────────────────
    def test_describe_scene_shortcut(self):
        result = self.svc.describe_scene(self.image)
        self.assertTrue(result.is_ok)
        self.assertEqual(result.scene_type, SceneType.DESKTOP.value)

    def test_answer_visual_shortcut(self):
        result = self.svc.answer_visual(self.image, "有什么内容?")
        self.assertTrue(result.is_ok)
        self.assertGreater(len(result.summary), 0)

    def test_understand_image_custom_prompt(self):
        result = self.svc.understand_image(self.image, prompt="自定义提示词")
        self.assertTrue(result.is_ok)

    # ── 配置 ──────────────────────────────────────────────────────
    def test_load_config_enables_permission(self):
        svc = UnderstandingService(manager=self.mgr, ulog=self.ulog)
        svc.load_config({"understanding_enabled": True})
        self.assertTrue(svc.get_permission()["understanding_enabled"])
        self.assertTrue(svc._initialized)

    def test_load_config_default_denied(self):
        svc = UnderstandingService(manager=self.mgr, ulog=self.ulog)
        svc.load_config({})
        self.assertFalse(svc.get_permission()["understanding_enabled"])

    def test_get_permission(self):
        perm = self.svc.get_permission()
        self.assertTrue(perm["understanding_enabled"])

    def test_reset_permission(self):
        self.svc.reset_permission()
        self.assertFalse(self.svc.get_permission()["understanding_enabled"])

    # ── 截屏理解 ──────────────────────────────────────────────────
    def test_capture_screen_without_vision_service(self):
        """未注入 VisionService → 结构化错误"""
        result = self.svc.capture_screen_and_understand(mode="describe")
        self.assertFalse(result.is_ok)
        self.assertIn("VisionService", result.error or "")

    def test_capture_screen_with_mock_vision(self):
        """注入 Mock VisionService → 截屏后理解"""
        svc = UnderstandingService(manager=self.mgr, ulog=self.ulog)
        svc.update_permission(understanding_enabled=True)

        mock_vision = MagicMock()
        frame = MagicMock()
        frame.image = self.image
        capture_result = MagicMock()
        capture_result.is_ok = True
        capture_result.frame = frame
        mock_vision.capture.return_value = capture_result
        # 通过 isinstance 检查绕过: 直接构造真实 VisionService 太复杂, 此处用 Mock 类
        from backend.vision.service import VisionService
        svc._vision_service = MagicMock(spec=VisionService)
        svc._vision_service.capture.return_value = capture_result

        result = svc.capture_screen_and_understand(mode="describe")
        self.assertTrue(result.is_ok)
        self.assertEqual(result.scene_type, SceneType.DESKTOP.value)

    # ── 状态与日志 ────────────────────────────────────────────────
    def test_status(self):
        status = self.svc.status()
        self.assertEqual(status["version"], "1.0.0")
        self.assertTrue(status["initialized"])
        self.assertIn("permission", status)
        self.assertIn("manager", status)
        self.assertIn("log_stats", status)

    def test_list_adapters(self):
        adapters = self.svc.list_adapters()
        self.assertGreaterEqual(len(adapters), 1)

    def test_get_logs(self):
        self.svc.describe_scene(self.image)
        logs = self.svc.get_logs(limit=10)
        self.assertGreater(len(logs), 0)

    def test_get_log_stats(self):
        self.svc.describe_scene(self.image)
        stats = self.svc.get_log_stats()
        self.assertGreater(stats["total"], 0)

    def test_clear_logs(self):
        self.svc.describe_scene(self.image)
        n = self.svc.clear_logs()
        self.assertGreater(n, 0)
        self.assertEqual(self.svc.get_log_stats()["total"], 0)

    # ── 异常与边界 ────────────────────────────────────────────────
    def test_understand_empty_image(self):
        req = UnderstandingRequest(image=None)
        result = self.svc.understand(req)
        self.assertFalse(result.is_ok)
        self.assertEqual(result.status, UnderstandingStatus.PERMISSION_DENIED.value)

    def test_understand_region_crop(self):
        req = UnderstandingRequest(image=self.image, region={"x": 0, "y": 0, "w": 50, "h": 50})
        result = self.svc.understand(req)
        self.assertTrue(result.is_ok)

    def test_understand_bad_region(self):
        req = UnderstandingRequest(image=self.image, region={"x": -10, "y": -10, "w": 9999, "h": 9999})
        result = self.svc.understand(req)
        self.assertTrue(result.is_ok)

    def test_understand_processing_time_recorded(self):
        req = UnderstandingRequest(image=self.image)
        result = self.svc.understand(req)
        self.assertGreater(result.processing_time, 0)

    def test_understand_with_perception_fallback(self):
        """未注入 PerceptionService → 退化为普通理解"""
        result = self.svc.understand_with_perception(self.image)
        self.assertTrue(result.is_ok)


class TestUnderstandingServiceSingleton(unittest.TestCase):

    def tearDown(self):
        reset_service()

    def test_get_service_singleton(self):
        s1 = get_service()
        s2 = get_service()
        self.assertIs(s1, s2)

    def test_get_service_registers_defaults(self):
        svc = get_service()
        self.assertGreaterEqual(len(svc.list_adapters()), 1)

    def test_reset_service(self):
        get_service()
        reset_service()
        self.assertIsNotNone(get_service())


if __name__ == "__main__":
    unittest.main()
