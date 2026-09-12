"""
单元测试: openai_vlm_provider.py - OpenAICompatibleVLMProvider
覆盖: 可用性 / JSON 解析 / 降级 / 无 key 错误 / 信息
(不发起真实网络请求)
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from backend.vision.understanding.interface import UnderstandingOptions
from backend.vision.understanding.providers.base import ProviderError
from backend.vision.understanding.providers.openai_vlm_provider import (
    OpenAICompatibleVLMProvider,
)
from backend.vision.understanding.schema import SceneType


class TestOpenAICompatibleVLMProviderParse(unittest.TestCase):

    def setUp(self):
        # 无 key + 隔离 config, 只测试解析逻辑
        self.provider = OpenAICompatibleVLMProvider(api_key="", use_config=False)

    def test_extract_json_plain(self):
        text = '{"scene_type": "desktop", "summary": "s", "description": "d"}'
        data = self.provider._extract_json(text)
        self.assertIsNotNone(data)
        self.assertEqual(data["scene_type"], "desktop")

    def test_extract_json_markdown_block(self):
        text = '```json\n{"scene_type": "web", "summary": "s"}\n```'
        data = self.provider._extract_json(text)
        self.assertIsNotNone(data)
        self.assertEqual(data["scene_type"], "web")

    def test_extract_json_with_surrounding_text(self):
        text = '好的, 分析如下:\n{"scene_type": "desktop", "summary": "x"}\n希望对你有帮助。'
        data = self.provider._extract_json(text)
        self.assertIsNotNone(data)
        self.assertEqual(data["scene_type"], "desktop")

    def test_extract_json_invalid(self):
        text = "这不是 JSON 内容"
        self.assertIsNone(self.provider._extract_json(text))

    def test_parse_result_full(self):
        content = (
            '{"scene_type": "desktop", "summary": "桌面", '
            '"description": "有窗口", '
            '"subjects": [{"name": "window", "category": "ui", "position": {"x": 1, "y": 2, "w": 3, "h": 4}, "confidence": 0.9}], '
            '"confidence": 0.85}'
        )
        result = self.provider._parse_result(content)
        self.assertTrue(result.is_ok)
        self.assertEqual(result.scene_type, "desktop")
        self.assertEqual(result.summary, "桌面")
        self.assertEqual(len(result.subjects), 1)
        self.assertEqual(result.subjects[0].position.x, 1)
        self.assertEqual(result.source, "vlm")

    def test_parse_result_qa_source(self):
        content = '{"scene_type": "web", "summary": "答案", "description": "细节"}'
        result = self.provider._parse_result(content, UnderstandingOptions(question="q"))
        self.assertEqual(result.source, "qa")

    def test_parse_result_unknown_scene_type(self):
        content = '{"scene_type": "weird", "summary": "s"}'
        result = self.provider._parse_result(content)
        self.assertEqual(result.scene_type, SceneType.UNKNOWN.value)

    def test_parse_result_fallback_to_text(self):
        content = "纯文本描述, 不是 JSON"
        result = self.provider._parse_result(content)
        self.assertTrue(result.is_ok)
        self.assertEqual(result.scene_type, SceneType.UNKNOWN.value)
        self.assertEqual(result.description, content)
        self.assertIn("raw", result.metadata)

    def test_parse_result_skips_bad_subjects(self):
        content = (
            '{"scene_type": "desktop", "summary": "s", '
            '"subjects": [{"name": "ok", "category": "ui"}, "bad", null]}'
        )
        result = self.provider._parse_result(content)
        self.assertEqual(len(result.subjects), 1)
        self.assertEqual(result.subjects[0].name, "ok")


class TestOpenAICompatibleVLMProviderAvailability(unittest.TestCase):

    def test_no_api_key_not_available(self):
        provider = OpenAICompatibleVLMProvider(api_key="", use_config=False)
        self.assertFalse(provider.is_available())

    def test_has_api_key_available(self):
        provider = OpenAICompatibleVLMProvider(api_key="sk-test", use_config=False)
        self.assertTrue(provider.is_available())

    def test_understand_without_key_raises(self):
        provider = OpenAICompatibleVLMProvider(api_key="", use_config=False)
        with self.assertRaises(ProviderError):
            provider.understand(np.zeros((10, 10, 3), dtype=np.uint8))

    def test_understand_none_image_raises(self):
        provider = OpenAICompatibleVLMProvider(api_key="sk-test", use_config=False)
        with self.assertRaises(ProviderError):
            provider.understand(None)

    def test_get_info(self):
        provider = OpenAICompatibleVLMProvider(api_key="", use_config=False)
        info = provider.get_info()
        self.assertEqual(info["name"], "openai_vlm")
        self.assertFalse(info["has_api_key"])
        self.assertIn("model", info)


if __name__ == "__main__":
    unittest.main()
