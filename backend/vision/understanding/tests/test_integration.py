"""
集成测试: 端到端流程
覆盖: 权限 → 理解 → 日志 完整链路 / 感知+理解 / 联合能力 / 单例清理
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

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
    UnderstandingStatus,
)
from backend.vision.understanding.service import (
    UnderstandingService,
    reset_service,
)


class TestUnderstandingIntegration(unittest.TestCase):

    def setUp(self):
        reset_service()
        self.provider = MockVLMProvider()
        self.mgr = UnderstandingManager()
        self.mgr.register_adapter("mock", VLMAdapter(provider=self.provider))
        self.perm = PermissionChecker()
        self.ulog = UnderstandingLogger(max_entries=1000, enable_logging=False)
        self.svc = UnderstandingService(manager=self.mgr, permission=self.perm, ulog=self.ulog)
        self.svc.update_permission(understanding_enabled=True)
        self.svc._initialized = True
        self.image = np.zeros((100, 200, 3), dtype=np.uint8)

    def tearDown(self):
        reset_service()

    def test_full_flow_denied(self):
        """权限关闭: 权限拒绝 → 不调用 Adapter → 日志记录失败"""
        self.svc.reset_permission()
        result = self.svc.understand(UnderstandingRequest(image=self.image))
        self.assertEqual(result.status, UnderstandingStatus.PERMISSION_DENIED.value)
        self.assertFalse(result.is_ok)
        self.assertEqual(self.provider.call_count, 0)  # 未触发 Provider

        stats = self.svc.get_log_stats()
        self.assertEqual(stats["fail"], 1)
        self.assertEqual(stats["success"], 0)

    def test_full_flow_ok(self):
        """权限开启: 权限通过 → Adapter 执行 → 成功结果 → 日志记录"""
        result = self.svc.understand(UnderstandingRequest(image=self.image))
        self.assertTrue(result.is_ok)
        self.assertEqual(result.scene_type, SceneType.DESKTOP.value)
        self.assertEqual(result.metadata["provider"], "mock")

        stats = self.svc.get_log_stats()
        self.assertEqual(stats["success"], 1)
        self.assertGreater(stats["avg_latency_ms"], 0)

        logs = self.svc.get_logs(limit=10)
        events = [e["event"] for e in logs]
        self.assertIn("start", events)
        self.assertIn("success", events)

    def test_full_roundtrip(self):
        """结果 dict 往返: to_dict → from_dict 保持语义完整"""
        result = self.svc.describe_scene(self.image)
        d = result.to_dict()
        from backend.vision.understanding.schema import UnderstandingResult
        restored = UnderstandingResult.from_dict(d)
        self.assertEqual(restored.scene_type, result.scene_type)
        self.assertEqual(restored.description, result.description)
        self.assertEqual(restored.summary, result.summary)
        self.assertEqual(len(restored.subjects), len(result.subjects))
        self.assertEqual(restored.status, result.status)

    def test_understand_with_perception_service(self):
        """注入 PerceptionService → 感知上下文增强"""
        from backend.vision.perception.adapters.ocr_adapter import OCRAdapter
        from backend.vision.perception.manager import PerceptionManager
        from backend.vision.perception.providers.mock_provider import MockOCRProvider
        from backend.vision.perception.service import (
            PerceptionService as PService,
        )

        pmgr = PerceptionManager()
        pmgr.register_ocr_adapter(
            "mock", OCRAdapter(provider=MockOCRProvider(texts=["感知到的文字"]))
        )
        psvc = PService(manager=pmgr)
        psvc.load_config({
            "perception_enabled": True,
            "ocr_enabled": True,
            "detection_enabled": False,
        })
        self.svc.set_perception_service(psvc)

        result = self.svc.understand_with_perception(self.image)
        self.assertTrue(result.is_ok)
        # 感知结果拼入 prompt 后进入 Mock (Mock 忽略 prompt), 此处仅验证流程不报错

    def test_understand_with_perception_no_permission(self):
        """感知权限关闭 → 退化为普通理解"""
        from backend.vision.perception.manager import PerceptionManager
        from backend.vision.perception.service import PerceptionService as PService

        pmgr = PerceptionManager()
        psvc = PService(manager=pmgr)
        psvc.load_config({})  # 全部默认拒绝
        self.svc.set_perception_service(psvc)

        result = self.svc.understand_with_perception(self.image)
        self.assertTrue(result.is_ok)
        self.assertEqual(result.scene_type, SceneType.DESKTOP.value)

    def test_multiple_requests_isolated(self):
        """多次请求结果互相隔离 (不同 id)"""
        r1 = self.svc.describe_scene(self.image)
        r2 = self.svc.describe_scene(self.image)
        self.assertNotEqual(r1.id, r2.id)

    def test_region_crop_integration(self):
        """区域裁剪后仍正常理解"""
        req = UnderstandingRequest(image=self.image, region={"x": 5, "y": 5, "w": 80, "h": 80})
        result = self.svc.understand(req)
        self.assertTrue(result.is_ok)


if __name__ == "__main__":
    unittest.main()
