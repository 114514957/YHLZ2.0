"""
单元测试: base.py - BaseOCRAdapter / BaseDetectionAdapter 模板方法
覆盖: 默认 Mock Provider 流程 / Provider 缺失 / Provider 不可用 / 异常隔离 / 耗时记录
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from backend.vision.perception.base import BaseDetectionAdapter, BaseOCRAdapter
from backend.vision.perception.interface import PerceptionOptions
from backend.vision.perception.providers.base import (
    DetectionProvider,
    OCRProvider,
    ProviderError,
)
from backend.vision.perception.providers.mock_provider import (
    MockDetectionProvider,
    MockOCRProvider,
)


class TestBaseOCRAdapter(unittest.TestCase):

    def setUp(self):
        self.image = np.zeros((100, 200, 3), dtype=np.uint8)

    def test_default_with_mock_provider(self):
        """默认注入 Mock Provider, 正常识别"""
        adapter = BaseOCRAdapter(provider=MockOCRProvider())
        self.assertTrue(adapter.is_available())
        result = adapter.recognize(self.image)
        self.assertTrue(result.success)
        self.assertEqual(result.provider, "mock")
        self.assertGreater(len(result.texts), 0)
        self.assertGreater(result.processing_time_ms, 0)

    def test_no_provider(self):
        """未配置 Provider"""
        adapter = BaseOCRAdapter(provider=None)
        self.assertFalse(adapter.is_available())
        result = adapter.recognize(self.image)
        self.assertFalse(result.success)
        self.assertIn("未配置", result.error)

    def test_none_image(self):
        """输入图像为空"""
        adapter = BaseOCRAdapter(provider=MockOCRProvider())
        result = adapter.recognize(None)
        self.assertFalse(result.success)
        self.assertIn("空", result.error)

    def test_provider_unavailable(self):
        """Provider 不可用"""
        provider = MockOCRProvider(available=False)
        adapter = BaseOCRAdapter(provider=provider)
        result = adapter.recognize(self.image)
        self.assertFalse(result.success)
        self.assertIn("不可用", result.error)

    def test_provider_exception_isolated(self):
        """Provider 抛异常应被捕获"""
        provider = MockOCRProvider(mode="exception")
        adapter = BaseOCRAdapter(provider=provider)
        result = adapter.recognize(self.image)
        # 异常被 Provider 转换为 ProviderError, Adapter 捕获后返回错误结果
        self.assertFalse(result.success)
        self.assertIn("Provider 错误", result.error)

    def test_min_confidence_filter(self):
        """Adapter 应用 min_confidence 过滤"""
        from backend.vision.perception.schema import DetectedText
        provider = MockOCRProvider(texts=["a", "b", "c"], confidence=0.5)
        adapter = BaseOCRAdapter(provider=provider)
        opts = PerceptionOptions(min_confidence=0.6)
        result = adapter.recognize(self.image, opts)
        # 所有文本置信度 0.5 < 0.6, 全部过滤
        self.assertTrue(result.success)
        self.assertEqual(len(result.texts), 0)

    def test_set_provider(self):
        """运行时切换 Provider"""
        adapter = BaseOCRAdapter(provider=None)
        self.assertFalse(adapter.is_available())
        adapter.set_provider(MockOCRProvider())
        self.assertTrue(adapter.is_available())

    def test_get_info_contains_provider(self):
        adapter = BaseOCRAdapter(provider=MockOCRProvider())
        info = adapter.get_info()
        self.assertEqual(info["name"], "base_ocr")
        self.assertEqual(info["type"], "ocr")
        self.assertIn("provider", info)
        self.assertEqual(info["provider"]["name"], "mock")


class TestBaseDetectionAdapter(unittest.TestCase):

    def setUp(self):
        self.image = np.zeros((480, 640, 3), dtype=np.uint8)

    def test_default_with_mock_provider(self):
        adapter = BaseDetectionAdapter(provider=MockDetectionProvider())
        result = adapter.detect(self.image)
        self.assertTrue(result.success)
        self.assertEqual(result.provider, "mock")
        self.assertGreater(len(result.objects), 0)

    def test_no_provider(self):
        adapter = BaseDetectionAdapter(provider=None)
        result = adapter.detect(self.image)
        self.assertFalse(result.success)
        self.assertIn("未配置", result.error)

    def test_none_image(self):
        adapter = BaseDetectionAdapter(provider=MockDetectionProvider())
        result = adapter.detect(None)
        self.assertFalse(result.success)

    def test_provider_unavailable(self):
        provider = MockDetectionProvider(available=False)
        adapter = BaseDetectionAdapter(provider=provider)
        result = adapter.detect(self.image)
        self.assertFalse(result.success)
        self.assertIn("不可用", result.error)

    def test_provider_exception_isolated(self):
        provider = MockDetectionProvider(mode="exception")
        adapter = BaseDetectionAdapter(provider=provider)
        result = adapter.detect(self.image)
        self.assertFalse(result.success)

    def test_max_objects_filter(self):
        adapter = BaseDetectionAdapter(provider=MockDetectionProvider())
        opts = PerceptionOptions(max_objects=1)
        result = adapter.detect(self.image, opts)
        self.assertEqual(len(result.objects), 1)

    def test_min_confidence_filter(self):
        adapter = BaseDetectionAdapter(provider=MockDetectionProvider())
        opts = PerceptionOptions(min_confidence=0.85)
        result = adapter.detect(self.image, opts)
        # 默认对象置信度: 0.92, 0.88, 0.75
        # >= 0.85 的: 0.92, 0.88 → 2 个
        self.assertEqual(len(result.objects), 2)


class TestProviderErrorPropagation(unittest.TestCase):
    """验证 Provider 抛异常时 Adapter 行为"""

    def test_custom_provider_raises_provider_error(self):
        class BadProvider(OCRProvider):
            name = "bad"

            def is_available(self) -> bool:
                return True

            def recognize_text(self, image, options=None):
                raise ProviderError("custom error")

        adapter = BaseOCRAdapter(provider=BadProvider())
        result = adapter.recognize(np.zeros((10, 10, 3), dtype=np.uint8))
        self.assertFalse(result.success)
        self.assertIn("Provider 错误", result.error)

    def test_custom_provider_raises_generic_exception(self):
        class BadProvider(DetectionProvider):
            name = "bad"

            def is_available(self) -> bool:
                return True

            def detect_objects(self, image, options=None):
                raise RuntimeError("unexpected")

        adapter = BaseDetectionAdapter(provider=BadProvider())
        result = adapter.detect(np.zeros((10, 10, 3), dtype=np.uint8))
        self.assertFalse(result.success)
        self.assertIn("Detection 异常", result.error)


if __name__ == "__main__":
    unittest.main()
