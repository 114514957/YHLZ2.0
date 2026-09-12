"""
单元测试: adapters/vlm_adapter.py - VLMAdapter
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from backend.vision.understanding.adapters.vlm_adapter import VLMAdapter
from backend.vision.understanding.providers.mock_provider import MockVLMProvider
from backend.vision.understanding.schema import SceneType


class TestVLMAdapter(unittest.TestCase):

    def setUp(self):
        self.image = np.zeros((100, 100, 3), dtype=np.uint8)

    def test_default_mock_provider(self):
        adapter = VLMAdapter()
        self.assertIsNotNone(adapter.provider)
        self.assertTrue(adapter.is_available())

    def test_understand_ok(self):
        adapter = VLMAdapter()
        result = adapter.understand(self.image)
        self.assertTrue(result.is_ok)
        self.assertEqual(result.scene_type, SceneType.DESKTOP.value)

    def test_understand_with_custom_provider(self):
        provider = MockVLMProvider(scene_type="web")
        adapter = VLMAdapter(provider=provider)
        result = adapter.understand(self.image)
        self.assertEqual(result.scene_type, "web")

    def test_set_provider_runtime(self):
        adapter = VLMAdapter(provider=MockVLMProvider(scene_type="web"))
        adapter.set_provider(MockVLMProvider(scene_type="game"))
        result = adapter.understand(self.image)
        self.assertEqual(result.scene_type, "game")

    def test_get_info(self):
        adapter = VLMAdapter()
        info = adapter.get_info()
        self.assertEqual(info["type"], "vlm")
        self.assertEqual(info["name"], "VLMAdapter")
        self.assertEqual(info["default_provider"], "mock")
        self.assertIn("provider", info)


if __name__ == "__main__":
    unittest.main()
