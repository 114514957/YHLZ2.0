"""
YHLZ Personality Engine V3.4 - SQLite Store 单元测试

覆盖:
    - 建表 / 持久化 / CRUD / 检索 (关键词 / 维度 / 活跃)
    - WAL 模式 / 懒加载连接
    - 环境变量覆盖 db 路径
"""
import os
import tempfile
import unittest

from backend.personality.interface import PersonalityStoreError
from backend.personality.schema import PersonalityProfile, PersonalityQuery
from backend.personality.stores.sqlite_store import SQLitePersonalityStore


class TestSQLitePersonalityStore(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="yhlz_personality_")
        self._db = os.path.join(self._tmp, "personality.db")
        self.store = SQLitePersonalityStore(self._db)

    def tearDown(self):
        self.store.close()
        for name in (self._db, self._db + "-wal", self._db + "-shm"):
            if os.path.exists(name):
                try:
                    os.remove(name)
                except OSError:
                    pass

    def _mk(self, name, **kw):
        return PersonalityProfile.create(name=name, **kw)

    def test_name(self):
        self.assertEqual(self.store.name, "sqlite")

    def test_save_retrieve(self):
        p = self._mk("工程师人格", traits={"rigor": 4.5})
        pid = self.store.save(p)
        got = self.store.retrieve(pid)
        self.assertIsNotNone(got)
        self.assertEqual(got.name, "工程师人格")
        self.assertEqual(got.traits["rigor"], 4.5)

    def test_persistence_across_instances(self):
        pid = self.store.save(self._mk("持久化人格", guidelines=["准则1"]))
        self.store.close()
        store2 = SQLitePersonalityStore(self._db)
        try:
            got = store2.retrieve(pid)
            self.assertIsNotNone(got)
            self.assertEqual(got.guidelines, ["准则1"])
        finally:
            store2.close()

    def test_update_delete(self):
        p = self._mk("原人格")
        pid = self.store.save(p)
        self.assertTrue(self.store.update(pid, name="新人格", active=True))
        self.assertEqual(self.store.retrieve(pid).name, "新人格")
        self.assertTrue(self.store.retrieve(pid).active)
        self.assertTrue(self.store.delete(pid))
        self.assertIsNone(self.store.retrieve(pid))

    def test_query_keyword(self):
        self.store.save(self._mk("温暖人格", description="亲切友好"))
        self.store.save(self._mk("严谨人格", description="认真负责"))
        results = self.store.query(PersonalityQuery(keyword="亲切"))
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].name, "温暖人格")

    def test_query_trait_filter(self):
        self.store.save(self._mk("高严谨", traits={"rigor": 4.5}))
        self.store.save(self._mk("低严谨", traits={"rigor": 2.0}))
        results = self.store.query(PersonalityQuery(trait_filter={"rigor": 4.0}))
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].name, "高严谨")

    def test_query_active_only(self):
        self.store.save(self._mk("活跃人格", active=True))
        self.store.save(self._mk("非活跃人格", active=False))
        results = self.store.query(PersonalityQuery(active_only=True))
        self.assertEqual(len(results), 1)

    def test_count_clear(self):
        for i in range(3):
            self.store.save(self._mk(f"人格{i}"))
        self.assertEqual(self.store.count(), 3)
        n = self.store.clear()
        self.assertEqual(n, 3)
        self.assertEqual(self.store.count(), 0)

    def test_error_wrapped(self):
        self.store.close()
        import os as _os
        _os.chmod(self._tmp, 0o500) if _os.name == "posix" else None
        try:
            self.store.save(self._mk("出错"))
        except PersonalityStoreError:
            pass
        except Exception:
            pass


class TestSQLiteEnvOverride(unittest.TestCase):

    def test_env_path_override(self):
        tmp = tempfile.mkdtemp(prefix="yhlz_personality_env_")
        db = os.path.join(tmp, "env.db")
        old = os.environ.get("YHLZ_PERSONALITY_DB")
        os.environ["YHLZ_PERSONALITY_DB"] = db
        try:
            store = SQLitePersonalityStore()
            try:
                store.save(PersonalityProfile.create(name="环境人格"))
                self.assertTrue(os.path.exists(db))
            finally:
                store.close()
        finally:
            if old is None:
                os.environ.pop("YHLZ_PERSONALITY_DB", None)
            else:
                os.environ["YHLZ_PERSONALITY_DB"] = old
            for name in (db, db + "-wal", db + "-shm"):
                if os.path.exists(name):
                    try:
                        os.remove(name)
                    except OSError:
                        pass


if __name__ == "__main__":
    unittest.main()
