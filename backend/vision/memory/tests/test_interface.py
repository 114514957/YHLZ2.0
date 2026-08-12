"""
YHLZ Vision Memory V1.0 - Interface 单元测试

覆盖:
    - MemoryStore ABC 抽象方法
    - 实例化抽象类报错
    - MemoryStoreError 可用性
"""
import unittest
from abc import ABC

from backend.vision.memory.interface import MemoryStore, MemoryStoreError


class TestMemoryStoreInterface(unittest.TestCase):

    def test_is_abstract(self):
        self.assertTrue(issubclass(MemoryStore, ABC))

    def test_cannot_instantiate(self):
        with self.assertRaises(TypeError):
            MemoryStore()

    def test_has_required_methods(self):
        for name in [
            "name", "save", "retrieve", "update", "delete",
            "query", "count", "clear",
        ]:
            self.assertTrue(
                hasattr(MemoryStore, name),
                f"MemoryStore 缺少方法/属性: {name}",
            )
        # close 有默认实现
        self.assertTrue(callable(MemoryStore.close))

    def test_error_is_exception(self):
        err = MemoryStoreError("测试错误")
        self.assertIsInstance(err, Exception)
        self.assertEqual(str(err), "测试错误")


if __name__ == "__main__":
    unittest.main()
