"""
单元测试: manager.py - UnderstandingManager
覆盖: 注册表 / 路由 / 默认注册 / 单例 / 重置 / 异常隔离
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from backend.vision.understanding.adapters.vlm_adapter import VLMAdapter
from backend.vision.understanding.manager import (
    UnderstandingManager,
    UnderstandingManagerError,
    get_manager,
    reset_manager,
)
from backend.vision.understanding.providers.mock_provider import MockVLMProvider
from backend.vision.understanding.schema import SceneType, UnderstandingStatus


class TestUnderstandingManager(unittest.TestCase):

    def setUp(self):
        self.mgr = UnderstandingManager()
        self.image = np.zeros((100, 100, 3), dtype=np.uint8)

    def test_register_adapter(self):
        self.mgr.register_adapter("mock", VLMAdapter())
        self.assertTrue(self.mgr.has_adapter("mock"))
        self.assertEqual(self.mgr.list_names(), ["mock"])

    def test_register_duplicate_raises(self):
        self.mgr.register_adapter("mock", VLMAdapter())
        with self.assertRaises(UnderstandingManagerError):
            self.mgr.register_adapter("mock", VLMAdapter())

    def test_register_duplicate_override(self):
        self.mgr.register_adapter("mock", VLMAdapter())
        self.mgr.register_adapter("mock", VLMAdapter(), override=True)
        self.assertTrue(self.mgr.has_adapter("mock"))

    def test_unregister(self):
        self.mgr.register_adapter("mock", VLMAdapter())
        self.assertTrue(self.mgr.unregister_adapter("mock"))
        self.assertFalse(self.mgr.unregister_adapter("mock"))

    def test_get_adapter(self):
        self.mgr.register_adapter("mock", VLMAdapter())
        self.assertIsNotNone(self.mgr.get_adapter("mock"))
        self.assertIsNone(self.mgr.get_adapter("nope"))

    def test_get_default_adapter(self):
        self.assertIsNone(self.mgr.get_default_adapter())
        self.mgr.register_adapter("mock", VLMAdapter())
        self.assertIsNotNone(self.mgr.get_default_adapter())

    def test_understand_no_adapter(self):
        result = self.mgr.understand(self.image)
        self.assertFalse(result.is_ok)
        self.assertEqual(result.status, UnderstandingStatus.NO_PROVIDER.value)

    def test_understand_ok(self):
        self.mgr.register_adapter("mock", VLMAdapter())
        result = self.mgr.understand(self.image)
        self.assertTrue(result.is_ok)
        self.assertEqual(result.scene_type, SceneType.DESKTOP.value)

    def test_understand_named_adapter(self):
        self.mgr.register_adapter("mock", VLMAdapter())
        self.mgr.register_adapter("empty", VLMAdapter(provider=MockVLMProvider(mode="empty")))
        result = self.mgr.understand(self.image, adapter_name="empty")
        self.assertTrue(result.is_ok)
        self.assertEqual(result.scene_type, SceneType.EMPTY.value)

    def test_understand_unknown_adapter(self):
        self.mgr.register_adapter("mock", VLMAdapter())
        result = self.mgr.understand(self.image, adapter_name="nope")
        self.assertFalse(result.is_ok)

    def test_understand_exception_isolated(self):
        self.mgr.register_adapter("boom", VLMAdapter(provider=MockVLMProvider(mode="exception")))
        result = self.mgr.understand(self.image)
        self.assertFalse(result.is_ok)
        self.assertIn("Provider 错误", result.error or "")

    def test_register_defaults_mock(self):
        self.mgr.register_defaults(include_mock=True)
        self.assertTrue(self.mgr.has_adapter("mock"))
        self.assertTrue(self.mgr._default_registered)

    def test_register_defaults_idempotent(self):
        self.mgr.register_defaults(include_mock=True)
        self.mgr.register_defaults(include_mock=True)
        self.assertEqual(len(self.mgr.list_names()), 1)

    def test_reset(self):
        self.mgr.register_adapter("mock", VLMAdapter())
        self.mgr.reset()
        self.assertEqual(self.mgr.list_names(), [])
        self.assertFalse(self.mgr._default_registered)

    def test_list_adapters_info(self):
        self.mgr.register_adapter("mock", VLMAdapter())
        infos = self.mgr.list_adapters()
        self.assertEqual(len(infos), 1)
        self.assertEqual(infos[0]["type"], "vlm")
        self.assertIn("provider", infos[0])

    def test_status(self):
        self.mgr.register_adapter("mock", VLMAdapter())
        status = self.mgr.status()
        self.assertEqual(status["adapters_count"], 1)
        self.assertIn("adapters", status)


class TestManagerSingleton(unittest.TestCase):

    def tearDown(self):
        reset_manager()

    def test_get_manager_singleton(self):
        m1 = get_manager()
        m2 = get_manager()
        self.assertIs(m1, m2)

    def test_get_manager_registers_defaults(self):
        mgr = get_manager()
        self.assertGreaterEqual(len(mgr.list_names()), 1)

    def test_reset_manager(self):
        get_manager()
        reset_manager()
        self.assertIsNotNone(get_manager())


if __name__ == "__main__":
    unittest.main()
