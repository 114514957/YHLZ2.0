"""
YHLZ Personality Engine V3.4 - Interface 单元测试

覆盖:
    - PersonalityStore 抽象接口方法完整性
    - PersonalityStoreError 异常
"""
import unittest
from abc import ABC

from backend.personality.interface import PersonalityStore, PersonalityStoreError


class TestPersonalityStoreInterface(unittest.TestCase):

    def test_is_abstract(self):
        self.assertTrue(issubclass(PersonalityStore, ABC))

    def test_cannot_instantiate(self):
        with self.assertRaises(TypeError):
            PersonalityStore()

    def test_abstract_methods(self):
        abstract = PersonalityStore.__abstractmethods__
        expected = {"name", "save", "retrieve", "update", "delete", "query", "count", "clear"}
        self.assertEqual(set(abstract), expected)

    def test_error_is_exception(self):
        err = PersonalityStoreError("测试错误")
        self.assertIsInstance(err, Exception)
        self.assertIn("测试错误", str(err))

    def test_concrete_store_instantiable(self):
        from backend.personality.stores.memory_store import InMemoryPersonalityStore
        store = InMemoryPersonalityStore()
        self.assertEqual(store.name, "memory")
        store.close()


if __name__ == "__main__":
    unittest.main()
