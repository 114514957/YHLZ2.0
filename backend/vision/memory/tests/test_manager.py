"""
YHLZ Vision Memory V1.0 - Manager 单元测试

覆盖:
    - Store 注册 / 注销 / 查询
    - 默认注册 (测试模式内存 / 生产 SQLite)
    - 路由保存
    - 单例 get_manager / reset_manager
"""
import os
import tempfile
import unittest

from backend.vision.memory.manager import (
    MemoryManager,
    MemoryManagerError,
    get_manager,
    reset_manager,
)
from backend.vision.memory.schema import VisualMemoryRecord
from backend.vision.memory.stores.memory_store import InMemoryMemoryStore


def _make(description="测试"):
    return VisualMemoryRecord.create(description=description)


class TestMemoryManager(unittest.TestCase):

    def setUp(self):
        self.mgr = MemoryManager()

    def tearDown(self):
        self.mgr.reset()

    def test_register_store(self):
        store = InMemoryMemoryStore()
        self.mgr.register_store("test", store)
        self.assertTrue(self.mgr.has_store("test"))
        self.assertEqual(self.mgr.list_names(), ["test"])

    def test_register_duplicate_raises(self):
        store = InMemoryMemoryStore()
        self.mgr.register_store("test", store)
        with self.assertRaises(MemoryManagerError):
            self.mgr.register_store("test", store)

    def test_register_override(self):
        store = InMemoryMemoryStore()
        self.mgr.register_store("test", store)
        self.mgr.register_store("test", store, override=True)
        self.assertEqual(len(self.mgr.list_names()), 1)

    def test_unregister(self):
        self.mgr.register_store("test", InMemoryMemoryStore())
        self.assertTrue(self.mgr.unregister_store("test"))
        self.assertFalse(self.mgr.unregister_store("test"))

    def test_get_store(self):
        store = InMemoryMemoryStore()
        self.mgr.register_store("test", store)
        self.assertIs(self.mgr.get_store("test"), store)
        self.assertIsNone(self.mgr.get_store("missing"))

    def test_default_store_is_first(self):
        store1 = InMemoryMemoryStore()
        store2 = InMemoryMemoryStore()
        self.mgr.register_store("a", store1)
        self.mgr.register_store("b", store2)
        self.assertIs(self.mgr.get_default_store(), store1)

    def test_save_route(self):
        store = InMemoryMemoryStore()
        self.mgr.register_store("test", store)
        mid = self.mgr.save(_make("路由保存"))
        self.assertEqual(store.retrieve(mid).description, "路由保存")

    def test_save_no_store_raises(self):
        with self.assertRaises(MemoryManagerError):
            self.mgr.save(_make())

    def test_register_defaults_memory_in_test_mode(self):
        os.environ["YHLZ_VISION_MEMORY_TEST_MODE"] = "true"
        try:
            mgr = MemoryManager()
            mgr.register_defaults(include_memory=True)
            names = mgr.list_names()
            self.assertEqual(names, ["memory"])
            self.assertIsInstance(mgr.get_default_store(), InMemoryMemoryStore)
            mgr.reset()
        finally:
            os.environ.pop("YHLZ_VISION_MEMORY_TEST_MODE", None)

    def test_register_defaults_sqlite(self):
        os.environ.pop("YHLZ_VISION_MEMORY_TEST_MODE", None)
        tmp = tempfile.mkdtemp(prefix="yhlz_mgr_")
        db = os.path.join(tmp, "mgr.db")
        try:
            mgr = MemoryManager()
            mgr.register_defaults(include_memory=True, db_path=db)
            self.assertEqual(mgr.list_names(), ["sqlite"])
            self.assertEqual(mgr.get_default_store().name, "sqlite")
            mid = mgr.save(_make("manager sqlite"))
            self.assertTrue(os.path.exists(db))
            self.assertIsNotNone(mgr.get_default_store().retrieve(mid))
            mgr.reset()
        finally:
            for name in (db, db + "-wal", db + "-shm"):
                if os.path.exists(name):
                    try:
                        os.remove(name)
                    except OSError:
                        pass

    def test_register_defaults_idempotent(self):
        os.environ["YHLZ_VISION_MEMORY_TEST_MODE"] = "true"
        try:
            mgr = MemoryManager()
            mgr.register_defaults(include_memory=True)
            mgr.register_defaults(include_memory=True)
            self.assertEqual(len(mgr.list_names()), 1)
            mgr.reset()
        finally:
            os.environ.pop("YHLZ_VISION_MEMORY_TEST_MODE", None)

    def test_status(self):
        store = InMemoryMemoryStore()
        self.mgr.register_store("test", store)
        status = self.mgr.status()
        self.assertEqual(status["stores_count"], 1)
        self.assertEqual(status["default_store"], store.name)
        self.assertEqual(status["stores"][0]["name"], "test")

    def test_reset(self):
        self.mgr.register_store("test", InMemoryMemoryStore())
        self.mgr.reset()
        self.assertEqual(self.mgr.list_names(), [])


class TestMemoryManagerSingleton(unittest.TestCase):

    def tearDown(self):
        reset_manager()

    def test_singleton_same_instance(self):
        m1 = get_manager()
        m2 = get_manager()
        self.assertIs(m1, m2)

    def test_reset_manager(self):
        m1 = get_manager()
        reset_manager()
        m2 = get_manager()
        self.assertIsNot(m1, m2)


if __name__ == "__main__":
    unittest.main()
