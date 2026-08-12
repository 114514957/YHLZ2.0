"""
集成测试: service.py - PerceptionService 完整流程
覆盖: 权限校验 → 感知 → 日志 / 配置加载 / 状态 / 快捷方法 / 截屏感知 / 单例
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from backend.vision.perception.adapters.detection_adapter import DetectionAdapter
from backend.vision.perception.adapters.ocr_adapter import OCRAdapter
from backend.vision.perception.logger import PerceptionLogger
from backend.vision.perception.manager import PerceptionManager
from backend.vision.perception.permission import PermissionChecker
from backend.vision.perception.providers.mock_provider import (
    MockDetectionProvider,
    MockOCRProvider,
)
from backend.vision.perception.schema import (
    PerceptionRequest,
    PerceptionSource,
    PerceptionStatus,
)
from backend.vision.perception.service import (
    PerceptionService,
    get_service,
    reset_service,
)


class TestPerceptionServiceBasic(unittest.TestCase):

    def setUp(self):
        reset_service()
        # 用 Mock Provider 隔离真实模型
        self.mgr = PerceptionManager()
        self.mgr.register_ocr_adapter(
            "mock", OCRAdapter(provider=MockOCRProvider(texts=["test1", "test2"]))
        )
        self.mgr.register_detection_adapter(
            "mock", DetectionAdapter(provider=MockDetectionProvider())
        )
        self.perm = PermissionChecker()
        self.plog = PerceptionLogger(max_entries=100, enable_logging=False)
        self.svc = PerceptionService(
            manager=self.mgr,
            permission=self.perm,
            plog=self.plog,
        )
        # 默认开启所有权限
        self.svc.update_permission(
            perception_enabled=True,
            ocr_enabled=True,
            detection_enabled=True,
        )
        # setUp 已完成依赖注入 + 权限配置 + Adapter 注册, 标记为已初始化
        # (load_config() 才会自动设置, 这里手动赋值以反映真实就绪状态)
        self.svc._initialized = True
        self.image = np.zeros((100, 200, 3), dtype=np.uint8)

    def tearDown(self):
        reset_service()

    # ── 权限流程 ──────────────────────────────────────────────────
    def test_perceive_permission_denied(self):
        """关闭权限 → 返回 PERMISSION_DENIED"""
        self.svc.reset_permission()  # 全部拒绝
        req = PerceptionRequest(source="ocr", image=self.image)
        result = self.svc.perceive(req)
        self.assertFalse(result.is_ok)
        self.assertEqual(result.status, PerceptionStatus.PERMISSION_DENIED.value)

    def test_perceive_permission_allowed(self):
        """开启权限 → 正常执行"""
        req = PerceptionRequest(source="ocr", image=self.image)
        result = self.svc.perceive(req)
        self.assertTrue(result.is_ok)
        self.assertEqual(len(result.text), 2)

    def test_perceive_logs_start_and_success(self):
        req = PerceptionRequest(source="ocr", image=self.image)
        self.svc.perceive(req)
        logs = self.plog.query(limit=10)
        events = [e.event for e in logs]
        self.assertIn("start", events)
        self.assertIn("success", events)

    def test_perceive_logs_fail_on_denied(self):
        self.svc.reset_permission()
        req = PerceptionRequest(source="ocr", image=self.image)
        self.svc.perceive(req)
        fail_logs = self.plog.query(event="fail", limit=10)
        self.assertGreater(len(fail_logs), 0)

    # ── 来源路由 ──────────────────────────────────────────────────
    def test_perceive_ocr(self):
        req = PerceptionRequest(source="ocr", image=self.image)
        result = self.svc.perceive(req)
        self.assertTrue(result.is_ok)
        self.assertEqual(result.source, "ocr")
        self.assertGreater(len(result.text), 0)
        self.assertEqual(len(result.objects), 0)

    def test_perceive_detection(self):
        req = PerceptionRequest(source="detection", image=self.image)
        result = self.svc.perceive(req)
        self.assertTrue(result.is_ok)
        self.assertEqual(result.source, "detection")
        self.assertGreater(len(result.objects), 0)

    def test_perceive_combined(self):
        req = PerceptionRequest(source="combined", image=self.image)
        result = self.svc.perceive(req)
        self.assertTrue(result.is_ok)
        self.assertEqual(result.source, "combined")
        self.assertGreater(len(result.objects), 0)
        self.assertGreater(len(result.text), 0)

    def test_perceive_mock_source(self):
        """mock 来源允许 (已开启 perception)"""
        req = PerceptionRequest(source="mock", image=self.image)
        result = self.svc.perceive(req)
        # mock 走 OCR 路径
        self.assertTrue(result.is_ok)
        self.assertEqual(result.source, "mock")

    def test_perceive_unknown_source(self):
        req = PerceptionRequest(source="unknown_xyz", image=self.image)
        # 权限层先拦截 (未知来源)
        result = self.svc.perceive(req)
        self.assertFalse(result.is_ok)

    # ── 快捷方法 ──────────────────────────────────────────────────
    def test_recognize_ocr_shortcut(self):
        result = self.svc.recognize_ocr(self.image, language="en")
        self.assertTrue(result.is_ok)
        self.assertEqual(len(result.text), 2)

    def test_detect_objects_shortcut(self):
        result = self.svc.detect_objects(self.image, min_confidence=0.5)
        self.assertTrue(result.is_ok)

    def test_perceive_combined_shortcut(self):
        result = self.svc.perceive_combined(self.image)
        self.assertTrue(result.is_ok)

    # ── region 裁剪 ──────────────────────────────────────────────
    def test_perceive_with_region(self):
        req = PerceptionRequest(
            source="ocr",
            image=self.image,
            region={"x": 0, "y": 0, "w": 50, "h": 50},
        )
        result = self.svc.perceive(req)
        self.assertTrue(result.is_ok)

    # ── 配置加载 ──────────────────────────────────────────────────
    def test_load_config(self):
        svc = PerceptionService()
        svc.load_config({
            "perception_enabled": True,
            "ocr_enabled": True,
            "detection_enabled": True,
        })
        perm = svc.permission.permission
        self.assertTrue(perm.perception_enabled)
        self.assertTrue(perm.ocr_enabled)
        self.assertTrue(svc._initialized)

    def test_load_config_registers_defaults(self):
        svc = PerceptionService()
        svc.load_config({"perception_enabled": True, "ocr_enabled": True})
        # 默认注册后应有 Adapter (mock 兜底)
        self.assertGreaterEqual(len(svc.list_ocr_adapters()), 1)

    def test_update_permission(self):
        self.svc.update_permission(ocr_enabled=False)
        perm = self.svc.permission.permission
        self.assertFalse(perm.ocr_enabled)

    def test_reset_permission(self):
        self.svc.reset_permission()
        perm = self.svc.permission.permission
        self.assertFalse(perm.perception_enabled)

    # ── Adapter 管理 ──────────────────────────────────────────────
    def test_list_adapters(self):
        ocr_list = self.svc.list_ocr_adapters()
        det_list = self.svc.list_detection_adapters()
        self.assertEqual(len(ocr_list), 1)
        self.assertEqual(len(det_list), 1)

    # ── 日志查询 ──────────────────────────────────────────────────
    def test_get_logs(self):
        req = PerceptionRequest(source="ocr", image=self.image)
        self.svc.perceive(req)
        logs = self.svc.get_logs(limit=10)
        self.assertGreaterEqual(len(logs), 2)  # start + success

    def test_get_log_stats(self):
        req = PerceptionRequest(source="ocr", image=self.image)
        self.svc.perceive(req)
        stats = self.svc.get_log_stats()
        self.assertGreaterEqual(stats["total"], 2)
        self.assertGreaterEqual(stats["success"], 1)

    def test_clear_logs(self):
        req = PerceptionRequest(source="ocr", image=self.image)
        self.svc.perceive(req)
        n = self.svc.clear_logs()
        self.assertGreater(n, 0)

    # ── 状态 ──────────────────────────────────────────────────────
    def test_status(self):
        status = self.svc.status()
        self.assertEqual(status["version"], "1.0.0")
        self.assertTrue(status["initialized"])
        self.assertIn("permission", status)
        self.assertIn("manager", status)
        self.assertIn("log_stats", status)
        self.assertFalse(status["has_vision_service"])

    # ── 截屏感知 (无 VisionService) ────────────────────────────────
    def test_capture_screen_without_vision_service(self):
        """未注入 VisionService 时返回错误"""
        result = self.svc.capture_screen_and_perceive(mode="ocr")
        self.assertFalse(result.is_ok)
        self.assertIn("VisionService", result.error)


class TestPerceptionServiceSingleton(unittest.TestCase):

    def setUp(self):
        reset_service()

    def tearDown(self):
        reset_service()

    def test_get_service_singleton(self):
        svc1 = get_service()
        svc2 = get_service()
        self.assertIs(svc1, svc2)

    def test_reset_service(self):
        svc1 = get_service()
        reset_service()
        svc2 = get_service()
        self.assertIsNot(svc1, svc2)

    def test_get_service_registers_defaults(self):
        svc = get_service()
        self.assertGreaterEqual(len(svc.list_ocr_adapters()), 1)


if __name__ == "__main__":
    unittest.main()
