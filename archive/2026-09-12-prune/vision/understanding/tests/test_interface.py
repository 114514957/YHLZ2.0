"""
单元测试: interface.py - VLMAdapter 抽象接口
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from backend.vision.understanding.interface import (
    UnderstandingAdapterError,
    UnderstandingOptions,
    VLMAdapter,
)


class TestVLMAdapterInterface(unittest.TestCase):

    def test_abstract_cannot_instantiate(self):
        """抽象基类不可实例化"""
        with self.assertRaises(TypeError):
            VLMAdapter()

    def test_abstract_methods(self):
        """抽象方法未实现时不可实例化"""
        class Incomplete(VLMAdapter):
            pass
        with self.assertRaises(TypeError):
            Incomplete()

    def test_interface_methods_raise(self):
        """接口方法直接调用抛 NotImplementedError"""
        class Impl(VLMAdapter):
            name = "test"

            def is_available(self):
                raise NotImplementedError

            def understand(self, image, prompt=None, options=None):
                raise NotImplementedError

        impl = Impl()
        with self.assertRaises(NotImplementedError):
            impl.is_available()
        with self.assertRaises(NotImplementedError):
            impl.understand(None)

    def test_get_info(self):
        class Impl(VLMAdapter):
            name = "test_vlm"

            def is_available(self):
                return True

            def understand(self, image, prompt=None, options=None):
                raise NotImplementedError

        info = Impl().get_info()
        self.assertEqual(info["name"], "test_vlm")
        self.assertEqual(info["type"], "vlm")
        self.assertTrue(info["available"])

    def test_error_is_exception(self):
        """UnderstandingAdapterError 是 Exception 子类"""
        self.assertTrue(issubclass(UnderstandingAdapterError, Exception))


class TestUnderstandingOptions(unittest.TestCase):

    def test_defaults(self):
        opts = UnderstandingOptions()
        self.assertIsNone(opts.prompt)
        self.assertIsNone(opts.question)
        self.assertEqual(opts.language, "zh")
        self.assertEqual(opts.max_tokens, 512)
        self.assertEqual(opts.temperature, 0.3)
        self.assertEqual(opts.timeout, 30.0)

    def test_custom(self):
        opts = UnderstandingOptions(
            prompt="描述",
            question="有什么?",
            language="en",
            max_tokens=128,
            temperature=0.1,
            timeout=10.0,
            extra={"model": "x"},
        )
        self.assertEqual(opts.prompt, "描述")
        self.assertEqual(opts.question, "有什么?")
        self.assertEqual(opts.language, "en")
        self.assertEqual(opts.max_tokens, 128)
        self.assertEqual(opts.extra["model"], "x")

    def test_to_dict_from_dict(self):
        opts = UnderstandingOptions(prompt="p", question="q", timeout=5.0)
        d = opts.to_dict()
        self.assertEqual(d["prompt"], "p")
        opts2 = UnderstandingOptions.from_dict(d)
        self.assertEqual(opts2.prompt, "p")
        self.assertEqual(opts2.timeout, 5.0)


if __name__ == "__main__":
    unittest.main()
