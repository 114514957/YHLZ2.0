"""
YHLZ Personality Engine V3.4 - 内存 Store 单元测试

覆盖:
    - save / retrieve / update / delete / count / clear
    - query: 关键词 / 维度阈值 / 活跃过滤 / 分页
    - 排序 (created_at 倒序) 与容量上限
"""
import unittest

from backend.personality.schema import PersonalityProfile, PersonalityQuery
from backend.personality.stores.memory_store import InMemoryPersonalityStore


class TestInMemoryPersonalityStore(unittest.TestCase):

    def setUp(self):
        self.store = InMemoryPersonalityStore()

    def tearDown(self):
        self.store.close()

    def _mk(self, name, **kw):
        return PersonalityProfile.create(name=name, **kw)

    def test_save_retrieve(self):
        p = self._mk("测试人格", description="温暖")
        pid = self.store.save(p)
        got = self.store.retrieve(pid)
        self.assertIsNotNone(got)
        self.assertEqual(got.name, "测试人格")
        self.assertEqual(got.description, "温暖")

    def test_retrieve_missing(self):
        self.assertIsNone(self.store.retrieve("not-exist"))

    def test_update_fields(self):
        p = self._mk("原人格")
        pid = self.store.save(p)
        self.assertTrue(self.store.update(pid, name="新人格", active=True))
        got = self.store.retrieve(pid)
        self.assertEqual(got.name, "新人格")
        self.assertTrue(got.active)

    def test_update_invalid_field_ignored(self):
        p = self._mk("原人格")
        pid = self.store.save(p)
        self.assertTrue(self.store.update(pid, name="新人格", not_allowed=123))
        got = self.store.retrieve(pid)
        self.assertEqual(got.name, "新人格")

    def test_update_missing(self):
        self.assertFalse(self.store.update("not-exist", name="x"))

    def test_delete(self):
        pid = self.store.save(self._mk("删除人格"))
        self.assertTrue(self.store.delete(pid))
        self.assertFalse(self.store.delete(pid))
        self.assertEqual(self.store.count(), 0)

    def test_count_clear(self):
        for i in range(3):
            self.store.save(self._mk(f"人格{i}"))
        self.assertEqual(self.store.count(), 3)
        n = self.store.clear()
        self.assertEqual(n, 3)
        self.assertEqual(self.store.count(), 0)

    def test_query_keyword(self):
        self.store.save(self._mk("工程师人格", description="严谨认真"))
        self.store.save(self._mk("温暖人格", description="亲切友好"))
        q = PersonalityQuery(keyword="工程师")
        results = self.store.query(q)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].name, "工程师人格")

    def test_query_trait_filter(self):
        self.store.save(self._mk("高温暖", traits={"warmth": 4.5}))
        self.store.save(self._mk("低温暖", traits={"warmth": 2.0}))
        q = PersonalityQuery(trait_filter={"warmth": 4.0})
        results = self.store.query(q)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].name, "高温暖")

    def test_query_active_only(self):
        self.store.save(self._mk("活跃人格", active=True))
        self.store.save(self._mk("非活跃人格", active=False))
        q = PersonalityQuery(active_only=True)
        results = self.store.query(q)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].name, "活跃人格")

    def test_query_limit_offset(self):
        for i in range(10):
            self.store.save(self._mk(f"人格{i}"))
        q = PersonalityQuery(limit=3, offset=2)
        results = self.store.query(q)
        self.assertEqual(len(results), 3)

    def test_query_order_desc_by_created(self):
        import time
        p1 = self._mk("先建", active=True)
        p2 = self._mk("后建", active=True)
        self.store.save(p1)
        time.sleep(0.01)
        self.store.save(p2)
        results = self.store.query(PersonalityQuery(active_only=True))
        self.assertEqual(results[0].name, "后建")
        self.assertEqual(results[1].name, "先建")

    def test_max_entries_eviction(self):
        store = InMemoryPersonalityStore(max_entries=3)
        for i in range(5):
            store.save(self._mk(f"人格{i}"))
        self.assertEqual(store.count(), 3)
        # 最旧的两个被淘汰, 最新 3 个保留
        for name in ("人格2", "人格3", "人格4"):
            found = False
            for p in store.query(PersonalityQuery()):
                if p.name == name:
                    found = True
            self.assertTrue(found, f"{name} 应保留")


if __name__ == "__main__":
    unittest.main()
