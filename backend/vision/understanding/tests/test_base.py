"""
单元测试: base.py - BaseVLMAdapter 模板方法
覆盖: 输入校验 / Provider 校验 / 异常隔离 / 耗时统计
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from backend.vision.understanding.base import BaseVLMAdapter
from backend.vision.understanding.interface import UnderstandingOptions
from backend.vision.understanding.providers.base import ProviderError, VLMProvider
from backend.vision.understanding.providers.mock_provider import MockVLMProvider
from backend.vision.understanding.schema import (
    SceneType,
    UnderstandingResult,
    UnderstandingStatus,
)


class TestBaseVLMAdapter(unittest.TestCase):

    def setUp(self):
        self.image = np.zeros((100, 200, 3), dtype=np.uint8)

    def test_empty_image(self):
        """空图像 → EMPTY_INPUT 错误结果, 不调 Provider"""
        adapter = BaseVLMAdapter(provider=MockVLMProvider())
        result = adapter.understand(None)
        self.assertFalse(result.is_ok)
        self.assertEqual(result.status, UnderstandingStatus.EMPTY_INPUT.value)

    def test_no_provider(self):
        """未配置 Provider → NO_PROVIDER"""
        adapter = BaseVLMAdapter(provider=None)
        result = adapter.understand(self.image)
        self.assertFalse(result.is_ok)
        self.assertEqual(result.status, UnderstandingStatus.NO_PROVIDER.value)

    def test_provider_unavailable(self):
        """Provider 不可用 → NO_PROVIDER"""
        provider = MockVLMProvider()
        provider.set_available(False)
        adapter = BaseVLMAdapter(provider=provider)
        result = adapter.understand(self.image)
        self.assertFalse(result.is_ok)
        self.assertEqual(result.status, UnderstandingStatus.NO_PROVIDER.value)

    def test_provider_exception(self):
        """Provider 抛 ProviderError → 错误结果"""
        provider = MockVLMProvider(mode="exception")
        adapter = BaseVLMAdapter(provider=provider)
        result = adapter.understand(self.image)
        self.assertFalse(result.is_ok)
        self.assertIn("Provider 错误", result.error or "")

    def test_success(self):
        """正常流程 → 成功结果 + 耗时记录"""
        adapter = BaseVLMAdapter(provider=MockVLMProvider())
        result = adapter.understand(self.image)
        self.assertTrue(result.is_ok)
        self.assertEqual(result.scene_type, SceneType.DESKTOP.value)
        self.assertGreater(result.processing_time, 0)
        self.assertEqual(result.metadata["provider"], "mock")

    def test_processing_time_recorded_on_error(self):
        """错误结果也记录耗时"""
        adapter = BaseVLMAdapter(provider=MockVLMProvider(mode="exception"))
        result = adapter.understand(self.image)
        self.assertGreater(result.processing_time, 0)

    def test_prompt_passed_to_provider(self):
        """自定义 prompt 传递到 Provider"""
        seen = {}

        class CaptureProvider(VLMProvider):
            name = "capture"

            def is_available(self):
                return True

            def understand(self, image, prompt=None, options=None):
                seen["prompt"] = prompt
                return UnderstandingResult.create_ok(
                    source="vlm", scene_type="desktop", description=str(prompt)
                )

        adapter = BaseVLMAdapter(provider=CaptureProvider())
        result = adapter.understand(self.image, prompt="自定义提示词")
        self.assertTrue(result.is_ok)
        self.assertEqual(seen["prompt"], "自定义提示词")

    def test_question_in_options(self):
        """options.question 传给 Mock 并影响 summary"""
        adapter = BaseVLMAdapter(provider=MockVLMProvider())
        opts = UnderstandingOptions(question="屏幕上有几个窗口?")
        result = adapter.understand(self.image, options=opts)
        self.assertTrue(result.is_ok)
        self.assertIn("窗口", result.summary)

    def test_get_info_includes_provider(self):
        provider = MockVLMProvider()
        adapter = BaseVLMAdapter(provider=provider)
        info = adapter.get_info()
        self.assertEqual(info["provider"]["name"], "mock")

    def test_set_provider_runtime_switch(self):
        """运行时替换 Provider"""
        adapter = BaseVLMAdapter(provider=MockVLMProvider(mode="exception"))
        adapter.set_provider(MockVLMProvider())
        result = adapter.understand(self.image)
        self.assertTrue(result.is_ok)

    def test_provider_returns_none(self):
        """Provider 返回 None → 错误结果"""

        class NoneProvider(VLMProvider):
            name = "none_provider"

            def is_available(self):
                return True

            def understand(self, image, prompt=None, options=None):
                return None

        adapter = BaseVLMAdapter(provider=NoneProvider())
        result = adapter.understand(self.image)
        self.assertFalse(result.is_ok)
        self.assertIn("空结果", result.error or "")

    def test_generic_exception_isolation(self):
        """Provider 抛普通异常 → 错误结果不外抛"""

        class BoomProvider(VLMProvider):
            name = "boom"

            def is_available(self):
                return True

            def understand(self, image, prompt=None, options=None):
                raise RuntimeError("boom")

        adapter = BaseVLMAdapter(provider=BoomProvider())
        result = adapter.understand(self.image)
        self.assertFalse(result.is_ok)
        self.assertIn("理解异常", result.error or "")


if __name__ == "__main__":
    unittest.main()
