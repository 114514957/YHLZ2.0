"""
单元测试: mock_provider.py - MockVLMProvider
覆盖: 合成结果 / 错误模式 / 可用性切换 / 空图 / QA 模式
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from backend.vision.understanding.interface import UnderstandingOptions
from backend.vision.understanding.providers.base import ProviderError
from backend.vision.understanding.providers.mock_provider import MockVLMProvider
from backend.vision.understanding.schema import SceneType, UnderstandingSubject


class TestMockVLMProvider(unittest.TestCase):

    def setUp(self):
        self.image = np.zeros((100, 200, 3), dtype=np.uint8)

    def test_default_ok(self):
        provider = MockVLMProvider()
        self.assertTrue(provider.is_available())
        result = provider.understand(self.image)
        self.assertTrue(result.is_ok)
        self.assertEqual(result.scene_type, SceneType.DESKTOP.value)
        self.assertGreater(len(result.subjects), 0)
        self.assertIn("桌面", result.description)
        self.assertEqual(result.metadata["provider"], "mock")

    def test_empty_mode(self):
        provider = MockVLMProvider(mode="empty")
        result = provider.understand(self.image)
        self.assertTrue(result.is_ok)
        self.assertEqual(result.scene_type, SceneType.EMPTY.value)
        self.assertEqual(result.subjects, [])

    def test_exception_mode(self):
        provider = MockVLMProvider(mode="exception")
        with self.assertRaises(ProviderError):
            provider.understand(self.image)

    def test_unavailable_mode(self):
        provider = MockVLMProvider(mode="unavailable")
        with self.assertRaises(ProviderError):
            provider.understand(self.image)

    def test_available_false(self):
        provider = MockVLMProvider()
        provider.set_available(False)
        self.assertFalse(provider.is_available())
        with self.assertRaises(ProviderError):
            provider.understand(self.image)

    def test_none_image(self):
        provider = MockVLMProvider()
        with self.assertRaises(ProviderError):
            provider.understand(None)

    def test_question_mode(self):
        provider = MockVLMProvider()
        opts = UnderstandingOptions(question="屏幕上有几个窗口?")
        result = provider.understand(self.image, options=opts)
        self.assertTrue(result.is_ok)
        self.assertIn("窗口", result.summary)
        self.assertIn("回答", result.summary)

    def test_custom_scene(self):
        provider = MockVLMProvider(
            scene_type="web",
            description="一个网页",
            summary="网页内容",
            subjects=[UnderstandingSubject(name="button", category="ui")],
        )
        result = provider.understand(self.image)
        self.assertEqual(result.scene_type, "web")
        self.assertEqual(result.description, "一个网页")
        self.assertEqual(result.summary, "网页内容")
        self.assertEqual(len(result.subjects), 1)
        self.assertEqual(result.subjects[0].name, "button")

    def test_call_count(self):
        provider = MockVLMProvider()
        provider.understand(self.image)
        provider.understand(self.image)
        self.assertEqual(provider.call_count, 2)

    def test_set_mode_runtime(self):
        provider = MockVLMProvider()
        provider.set_mode("empty")
        result = provider.understand(self.image)
        self.assertEqual(result.scene_type, SceneType.EMPTY.value)
        provider.set_mode("ok")
        result = provider.understand(self.image)
        self.assertEqual(result.scene_type, SceneType.DESKTOP.value)

    def test_reset(self):
        provider = MockVLMProvider(mode="exception")
        provider.set_available(False)
        provider.reset()
        self.assertTrue(provider.is_available())
        result = provider.understand(self.image)
        self.assertTrue(result.is_ok)

    def test_get_info(self):
        provider = MockVLMProvider()
        info = provider.get_info()
        self.assertEqual(info["name"], "mock")
        self.assertEqual(info["type"], "vlm")
        self.assertIn("mode", info)
        self.assertIn("call_count", info)


if __name__ == "__main__":
    unittest.main()
