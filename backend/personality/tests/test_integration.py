"""
YHLZ Personality Engine V3.4 - 集成测试

覆盖:
    - SQLite 持久化 + 检索全链路 (Service → Manager → Store)
    - 权限全链路 (默认拒绝 → 开启 → 拒绝重置)
    - 单例 Service + Manager 组合
    - 风格生成 / 切换 / 一致性评估全链路
"""
import os
import tempfile
import unittest

from backend.personality.manager import PersonalityManager
from backend.personality.permission import PermissionChecker
from backend.personality.schema import PersonalityProfile, PersonalityQuery
from backend.personality.service import (
    PersonalityService,
    get_service,
    reset_service,
)
from backend.personality.stores.sqlite_store import SQLitePersonalityStore


class TestSQLiteServiceIntegration(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="yhlz_personality_integ_")
        self._db = os.path.join(self._tmp, "integ.db")
        self.store = SQLitePersonalityStore(self._db)
        self.mgr = PersonalityManager()
        self.mgr.register_store("sqlite", self.store)
        self.svc = PersonalityService(manager=self.mgr, permission=PermissionChecker())
        self.svc.load_config({"personality_enabled": True, "db_path": self._db})

    def tearDown(self):
        reset_service()
        self.store.close()
        for name in (self._db, self._db + "-wal", self._db + "-shm"):
            if os.path.exists(name):
                try:
                    os.remove(name)
                except OSError:
                    pass

    def test_full_cycle(self):
        # 1. 保存
        res = self.svc.save(PersonalityProfile.create(
            name="工程师人格",
            description="严谨认真的工程人格",
            traits={"rigor": 4.5},
            guidelines=["先分析后回答"],
            active=True,
        ))
        self.assertTrue(res.success)
        self.assertEqual(self.svc.count(), 1)
        # 2. 检索
        q = self.svc.query(PersonalityQuery(keyword="工程师"))
        self.assertEqual(q.count, 1)
        self.assertEqual(q.profiles[0].traits["rigor"], 4.5)
        # 3. 风格
        style = self.svc.personality_style()
        self.assertTrue(style.success)
        self.assertIn("你是 工程师人格", style.style)
        # 4. 更新
        up = self.svc.update(res.profile_id, name="首席工程师人格")
        self.assertTrue(up.success)
        got = self.svc.retrieve(res.profile_id)
        self.assertEqual(got.profile.name, "首席工程师人格")
        # 5. 删除
        d = self.svc.delete(res.profile_id)
        self.assertTrue(d.success)
        self.assertEqual(self.svc.count(), 0)

    def test_permission_chain(self):
        # 默认拒绝
        self.svc.reset_permission()
        res = self.svc.save(PersonalityProfile.create(name="x"))
        self.assertFalse(res.success)
        self.assertEqual(res.status, "denied")
        # 开启
        self.svc.update_permission(personality_enabled=True)
        res = self.svc.save(PersonalityProfile.create(name="x"))
        self.assertTrue(res.success)
        # 再拒绝
        self.svc.update_permission(personality_enabled=False)
        res = self.svc.query(PersonalityQuery())
        self.assertFalse(res.success)
        self.assertEqual(res.status, "denied")

    def test_switch_and_assess(self):
        self.svc.save(PersonalityProfile.create(
            name="温柔人格", active=True,
            traits={"warmth": 5.0, "friendliness": 5.0, "conciseness": 3.0},
            preferences={"use_emojis": True},
        ))
        self.svc.save(PersonalityProfile.create(
            name="冷峻人格",
            traits={"warmth": 1.0, "friendliness": 1.0, "conciseness": 5.0},
            preferences={"use_emojis": False},
        ))
        self.svc.switch_profile(self.svc.query(PersonalityQuery(keyword="冷峻")).profiles[0].profile_id)
        current = self.svc.get_current_profile()
        self.assertEqual(current.profile.name, "冷峻人格")
        res = self.svc.assess_consistency("数据: 完成 100%")
        self.assertTrue(res.success)
        self.assertGreaterEqual(res.consistency, 0.0)


class TestPersonalitySingletonIntegration(unittest.TestCase):

    def tearDown(self):
        reset_service()
        old = os.environ.get("YHLZ_PERSONALITY_TEST_MODE")
        if old is None:
            os.environ.pop("YHLZ_PERSONALITY_TEST_MODE", None)

    def test_get_service_singleton_memory(self):
        os.environ["YHLZ_PERSONALITY_TEST_MODE"] = "true"
        try:
            s1 = get_service()
            s2 = get_service()
            self.assertIs(s1, s2)
            self.assertEqual(s1.manager.get_default_store().name, "memory")
        finally:
            os.environ.pop("YHLZ_PERSONALITY_TEST_MODE", None)

    def test_reset_service(self):
        os.environ["YHLZ_PERSONALITY_TEST_MODE"] = "true"
        try:
            s1 = get_service()
            reset_service()
            s2 = get_service()
            self.assertIsNot(s1, s2)
        finally:
            os.environ.pop("YHLZ_PERSONALITY_TEST_MODE", None)

    def test_singleton_sqlite_persistence(self):
        old = os.environ.get("YHLZ_PERSONALITY_TEST_MODE")
        os.environ.pop("YHLZ_PERSONALITY_TEST_MODE", None)
        tmp = tempfile.mkdtemp(prefix="yhlz_personality_sing_")
        db = os.path.join(tmp, "sing.db")
        try:
            svc = get_service(db_path=db)
            svc.load_config({"personality_enabled": True, "db_path": db})
            res = svc.save(PersonalityProfile.create(name="单例持久化人格"))
            self.assertTrue(res.success)
            self.assertTrue(os.path.exists(db))
            # 重新获取单例, 数据仍在
            svc2 = get_service(db_path=db)
            self.assertIs(svc, svc2)
            got = svc2.retrieve(res.profile_id)
            self.assertEqual(got.profile.name, "单例持久化人格")
        finally:
            reset_service()
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
