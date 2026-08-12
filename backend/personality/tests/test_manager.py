"""
YHLZ Personality Engine V3.4 - Manager 单元测试

覆盖:
    - Store 注册 / 注销 / 查询
    - 默认注册 (测试模式内存 / 生产 SQLite)
    - 单例 get_manager / reset_manager
"""
import os
import tempfile
import unittest

from backend.personality.manager import (
    PersonalityManager,
    PersonalityManagerError,
    get_manager,
    reset_manager,
)
from backend.personality.schema import PersonalityProfile
from backend.personality.stores.memory_store import InMemoryPersonalityStore


class TestPersonalityManager(unittest.TestCase):

    def setUp(self):
        self.mgr = PersonalityManager()

    def test_register_store(self):
        store = InMemoryPersonalityStore()
        self.mgr.register_store("test", store)
        self.assertTrue(self.mgr.has_store("test"))
        self.assertEqual(self.mgr.get_store("test"), store)

    def test_register_duplicate_raises(self):
        self.mgr.register_store("test", InMemoryPersonalityStore())
        with self.assertRaises(PersonalityManagerError):
            self.mgr.register_store("test", InMemoryPersonalityStore())

    def test_register_duplicate_override(self):
        store = InMemoryPersonalityStore()
        self.mgr.register_store("test", InMemoryPersonalityStore())
        self.mgr.register_store("test", store, override=True)
        self.assertEqual(self.mgr.get_store("test"), store)

    def test_unregister(self):
        self.mgr.register_store("test", InMemoryPersonalityStore())
        self.assertTrue(self.mgr.unregister_store("test"))
        self.assertFalse(self.mgr.unregister_store("test"))
        self.assertFalse(self.mgr.has_store("test"))

    def test_default_store_is_first(self):
        s1 = InMemoryPersonalityStore()
        s2 = InMemoryPersonalityStore()
        self.mgr.register_store("a", s1)
        self.mgr.register_store("b", s2)
        self.assertEqual(self.mgr.get_default_store(), s1)

    def test_no_default_store(self):
        self.assertIsNone(self.mgr.get_default_store())

    def test_list_stores(self):
        self.mgr.register_store("a", InMemoryPersonalityStore())
        names = self.mgr.list_names()
        self.assertEqual(names, ["a"])
        info = self.mgr.list_stores()[0]
        self.assertEqual(info["name"], "a")

    def test_save_no_store_raises(self):
        with self.assertRaises(PersonalityManagerError):
            self.mgr.save(PersonalityProfile.default_profile())

    def test_save_routes_to_default(self):
        store = InMemoryPersonalityStore()
        self.mgr.register_store("a", store)
        pid = self.mgr.save(PersonalityProfile.create(name="路由测试"))
        self.assertIsNotNone(store.retrieve(pid))

    def test_register_defaults_memory_in_test_mode(self):
        old = os.environ.get("YHLZ_PERSONALITY_TEST_MODE")
        os.environ["YHLZ_PERSONALITY_TEST_MODE"] = "true"
        try:
            mgr = PersonalityManager()
            mgr.register_defaults(include_memory=True)
            self.assertEqual(mgr.get_default_store().name, "memory")
        finally:
            if old is None:
                os.environ.pop("YHLZ_PERSONALITY_TEST_MODE", None)
            else:
                os.environ["YHLZ_PERSONALITY_TEST_MODE"] = old

    def test_register_defaults_sqlite(self):
        old = os.environ.get("YHLZ_PERSONALITY_TEST_MODE")
        os.environ.pop("YHLZ_PERSONALITY_TEST_MODE", None)
        tmp = tempfile.mkdtemp(prefix="yhlz_personality_mgr_")
        db = os.path.join(tmp, "mgr.db")
        try:
            mgr = PersonalityManager()
            mgr.register_defaults(include_memory=False, db_path=db)
            self.assertEqual(mgr.get_default_store().name, "sqlite")
        finally:
            if old is not None:
                os.environ["YHLZ_PERSONALITY_TEST_MODE"] = old
            for name in (db, db + "-wal", db + "-shm"):
                if os.path.exists(name):
                    try:
                        os.remove(name)
                    except OSError:
                        pass

    def test_register_defaults_idempotent(self):
        mgr = PersonalityManager()
        mgr.register_defaults()
        first = mgr.get_default_store()
        mgr.register_defaults()
        self.assertEqual(mgr.get_default_store(), first)

    def test_reset(self):
        self.mgr.register_store("a", InMemoryPersonalityStore())
        self.mgr.reset()
        self.assertEqual(self.mgr.list_names(), [])
        self.assertFalse(self.mgr.status()["default_registered"])

    def test_status(self):
        self.mgr.register_store("a", InMemoryPersonalityStore())
        st = self.mgr.status()
        self.assertEqual(st["stores_count"], 1)
        self.assertEqual(st["default_store"], "memory")


class TestManagerSingleton(unittest.TestCase):

    def tearDown(self):
        reset_manager()
        old = os.environ.get("YHLZ_PERSONALITY_TEST_MODE")
        if old is None:
            os.environ.pop("YHLZ_PERSONALITY_TEST_MODE", None)

    def test_get_manager_singleton_test_mode(self):
        os.environ["YHLZ_PERSONALITY_TEST_MODE"] = "true"
        m1 = get_manager()
        m2 = get_manager()
        self.assertIs(m1, m2)
        self.assertEqual(m1.get_default_store().name, "memory")

    def test_reset_manager(self):
        os.environ["YHLZ_PERSONALITY_TEST_MODE"] = "true"
        m1 = get_manager()
        reset_manager()
        m2 = get_manager()
        self.assertIsNot(m1, m2)

    def test_get_manager_db_path_sqlite(self):
        old = os.environ.get("YHLZ_PERSONALITY_TEST_MODE")
        os.environ.pop("YHLZ_PERSONALITY_TEST_MODE", None)
        tmp = tempfile.mkdtemp(prefix="yhlz_personality_sing_")
        db = os.path.join(tmp, "sing.db")
        try:
            mgr = get_manager(db_path=db)
            self.assertEqual(mgr.get_default_store().name, "sqlite")
            pid = mgr.save(PersonalityProfile.create(name="单例人格"))
            self.assertTrue(os.path.exists(db))
            self.assertIsNotNone(mgr.get_default_store().retrieve(pid))
        finally:
            if old is not None:
                os.environ["YHLZ_PERSONALITY_TEST_MODE"] = old
            for name in (db, db + "-wal", db + "-shm"):
                if os.path.exists(name):
                    try:
                        os.remove(name)
                    except OSError:
                        pass


if __name__ == "__main__":
    unittest.main()
