"""
YHLZ Vision Memory V1.0 - 内存存储单元测试

覆盖:
    - save / retrieve / update / delete
    - query 全条件过滤 (时间/场景/标签/关键词/重要程度)
    - 排序 (最新在前) / 分页 (limit/offset)
    - 容量上限 (超限删最旧)
    - count / clear / close
"""
import unittest
import time

from backend.vision.memory.schema import MemoryQuery, VisualMemoryRecord
from backend.vision.memory.stores.memory_store import InMemoryMemoryStore


def _make(description, scene_type="desktop", tags=None, importance="medium",
          timestamp=None, confidence=0.8):
    return VisualMemoryRecord.create(
        description=description,
        scene_type=scene_type,
        tags=tags or [],
        importance=importance,
        confidence=confidence,
        timestamp=timestamp if timestamp is not None else time.time(),
    )


class TestInMemoryMemoryStore(unittest.TestCase):

    def setUp(self):
        self.store = InMemoryMemoryStore(max_entries=100)

    def tearDown(self):
        self.store.close()

    def test_name(self):
        self.assertEqual(self.store.name, "memory")

    def test_save_retrieve(self):
        r = _make("保存一条记忆")
        mid = self.store.save(r)
        got = self.store.retrieve(mid)
        self.assertIsNotNone(got)
        self.assertEqual(got.description, "保存一条记忆")
        self.assertEqual(got.id, mid)

    def test_retrieve_missing(self):
        self.assertIsNone(self.store.retrieve("not_exist"))

    def test_save_overwrite(self):
        r = _make("原始内容")
        mid = self.store.save(r)
        r2 = _make("覆盖内容")
        r2.id = mid
        self.store.save(r2)
        got = self.store.retrieve(mid)
        self.assertEqual(got.description, "覆盖内容")
        self.assertEqual(self.store.count(), 1)

    def test_update(self):
        mid = self.store.save(_make("原始"))
        self.assertTrue(self.store.update(mid, description="更新后"))
        self.assertEqual(self.store.retrieve(mid).description, "更新后")

    def test_update_missing(self):
        self.assertFalse(self.store.update("not_exist", description="x"))

    def test_update_invalid_field(self):
        mid = self.store.save(_make("原始"))
        self.assertFalse(self.store.update(mid, image="原始图片"))
        self.assertEqual(self.store.retrieve(mid).description, "原始")

    def test_update_touch_timestamp(self):
        mid = self.store.save(_make("原始"))
        t0 = self.store.retrieve(mid).updated_at
        time.sleep(0.01)
        self.store.update(mid, importance="high")
        self.assertGreater(self.store.retrieve(mid).updated_at, t0)

    def test_delete(self):
        mid = self.store.save(_make("待删除"))
        self.assertTrue(self.store.delete(mid))
        self.assertIsNone(self.store.retrieve(mid))
        self.assertFalse(self.store.delete(mid))

    def test_query_all(self):
        self.store.save(_make("a"))
        self.store.save(_make("b"))
        self.assertEqual(len(self.store.query(MemoryQuery())), 2)

    def test_query_newest_first(self):
        self.store.save(_make("old"))
        time.sleep(0.01)
        self.store.save(_make("new"))
        results = self.store.query(MemoryQuery())
        self.assertEqual(results[0].description, "new")
        self.assertEqual(results[1].description, "old")

    def test_query_keyword(self):
        self.store.save(_make("桌面上有代码编辑器"))
        self.store.save(_make("窗口里有音乐播放器"))
        results = self.store.query(MemoryQuery(keyword="代码"))
        self.assertEqual(len(results), 1)
        self.assertIn("代码", results[0].description)

    def test_query_scene_type(self):
        self.store.save(_make("桌面", scene_type="desktop"))
        self.store.save(_make("文档", scene_type="document"))
        results = self.store.query(MemoryQuery(scene_type="document"))
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].scene_type, "document")

    def test_query_tag(self):
        self.store.save(_make("内容1", tags=["代码", "工作"]))
        self.store.save(_make("内容2", tags=["娱乐"]))
        results = self.store.query(MemoryQuery(tag="代码"))
        self.assertEqual(len(results), 1)

    def test_query_importance(self):
        self.store.save(_make("普通", importance="medium"))
        self.store.save(_make("重要", importance="high"))
        results = self.store.query(MemoryQuery(importance="high"))
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].description, "重要")

    def test_query_time_range(self):
        t0 = time.time()
        self.store.save(_make("过去", timestamp=t0 - 100))
        self.store.save(_make("现在", timestamp=t0))
        self.store.save(_make("未来", timestamp=t0 + 100))
        results = self.store.query(
            MemoryQuery(time_from=t0 - 10, time_to=t0 + 10)
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].description, "现在")

    def test_query_limit_offset(self):
        for i in range(10):
            self.store.save(_make(f"记录{i}"))
        results = self.store.query(MemoryQuery(limit=3, offset=0))
        self.assertEqual(len(results), 3)
        results2 = self.store.query(MemoryQuery(limit=3, offset=3))
        self.assertEqual(len(results2), 3)
        self.assertNotEqual(results[0].id, results2[0].id)

    def test_max_entries_eviction(self):
        store = InMemoryMemoryStore(max_entries=5)
        for i in range(10):
            store.save(_make(f"记录{i}"))
        self.assertEqual(store.count(), 5)
        # 保留的是最新的 5 条
        got = [r.description for r in store.query(MemoryQuery(limit=20))]
        self.assertEqual(got, [f"记录{i}" for i in range(9, 4, -1)])
        store.close()

    def test_count(self):
        self.assertEqual(self.store.count(), 0)
        self.store.save(_make("a"))
        self.store.save(_make("b"))
        self.assertEqual(self.store.count(), 2)

    def test_clear(self):
        self.store.save(_make("a"))
        self.store.save(_make("b"))
        n = self.store.clear()
        self.assertEqual(n, 2)
        self.assertEqual(self.store.count(), 0)

    def test_query_invalid_limit(self):
        self.store.save(_make("a"))
        results = self.store.query(MemoryQuery(limit=-1))
        self.assertEqual(len(results), 0)


if __name__ == "__main__":
    unittest.main()
