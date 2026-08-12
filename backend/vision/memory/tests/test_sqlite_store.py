"""
YHLZ Vision Memory V1.0 - SQLite 存储单元测试

覆盖:
    - 临时数据库创建 / 全操作 (save/retrieve/update/delete/query/count/clear/close)
    - 持久化 (关闭后重新打开数据仍在)
    - 检索条件 (时间/场景/标签/关键词/重要程度)
    - 环境变量覆盖 db 路径 (测试隔离)
"""
import os
import tempfile
import unittest
import time

from backend.vision.memory.schema import MemoryQuery, VisualMemoryRecord
from backend.vision.memory.stores.sqlite_store import SQLiteMemoryStore


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


class TestSQLiteMemoryStore(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="yhlz_mem_test_")
        self._db = os.path.join(self._tmp, "test_memories.db")
        self.store = SQLiteMemoryStore(self._db)

    def tearDown(self):
        self.store.close()
        for name in (self._db, self._db + "-wal", self._db + "-shm"):
            if os.path.exists(name):
                try:
                    os.remove(name)
                except OSError:
                    pass

    def test_name(self):
        self.assertEqual(self.store.name, "sqlite")

    def test_save_retrieve(self):
        r = _make("SQLite 保存")
        mid = self.store.save(r)
        got = self.store.retrieve(mid)
        self.assertIsNotNone(got)
        self.assertEqual(got.description, "SQLite 保存")
        self.assertEqual(got.id, mid)

    def test_retrieve_missing(self):
        self.assertIsNone(self.store.retrieve("not_exist"))

    def test_save_overwrite(self):
        mid = self.store.save(_make("原始"))
        r2 = _make("覆盖")
        r2.id = mid
        self.store.save(r2)
        self.assertEqual(self.store.retrieve(mid).description, "覆盖")
        self.assertEqual(self.store.count(), 1)

    def test_update(self):
        mid = self.store.save(_make("原始", scene_type="desktop"))
        self.assertTrue(self.store.update(mid, description="更新后", scene_type="web"))
        got = self.store.retrieve(mid)
        self.assertEqual(got.description, "更新后")
        self.assertEqual(got.scene_type, "web")

    def test_update_json_fields(self):
        mid = self.store.save(_make("原始", tags=["a"]))
        self.assertTrue(self.store.update(mid, tags=["a", "b"], metadata={"k": 1}))
        got = self.store.retrieve(mid)
        self.assertEqual(got.tags, ["a", "b"])
        self.assertEqual(got.metadata, {"k": 1})

    def test_update_missing(self):
        self.assertFalse(self.store.update("not_exist", description="x"))

    def test_update_invalid_field(self):
        mid = self.store.save(_make("原始"))
        self.assertFalse(self.store.update(mid, image="原始图片"))
        self.assertEqual(self.store.retrieve(mid).description, "原始")

    def test_update_empty_fields(self):
        mid = self.store.save(_make("原始"))
        self.assertFalse(self.store.update(mid))

    def test_delete(self):
        mid = self.store.save(_make("待删除"))
        self.assertTrue(self.store.delete(mid))
        self.assertIsNone(self.store.retrieve(mid))
        self.assertFalse(self.store.delete(mid))

    def test_query_all_newest_first(self):
        self.store.save(_make("old"))
        time.sleep(0.01)
        self.store.save(_make("new"))
        results = self.store.query(MemoryQuery())
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].description, "new")

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

    def test_query_time_range(self):
        t0 = time.time()
        self.store.save(_make("过去", timestamp=t0 - 100))
        self.store.save(_make("现在", timestamp=t0))
        self.store.save(_make("未来", timestamp=t0 + 100))
        results = self.store.query(MemoryQuery(time_from=t0 - 10, time_to=t0 + 10))
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].description, "现在")

    def test_query_combined_conditions(self):
        self.store.save(_make("代码编辑器", scene_type="desktop", tags=["工作"], importance="high"))
        self.store.save(_make("代码编辑器", scene_type="web", tags=["工作"]))
        results = self.store.query(
            MemoryQuery(keyword="代码", scene_type="desktop", importance="high")
        )
        self.assertEqual(len(results), 1)

    def test_query_limit_offset(self):
        for i in range(10):
            self.store.save(_make(f"记录{i}"))
        results = self.store.query(MemoryQuery(limit=3, offset=0))
        self.assertEqual(len(results), 3)
        results2 = self.store.query(MemoryQuery(limit=3, offset=3))
        self.assertEqual(len(results2), 3)
        self.assertNotEqual(results[0].id, results2[0].id)

    def test_persistence_after_close(self):
        mid = self.store.save(_make("持久化记录", scene_type="web", tags=["测试"]))
        self.store.close()
        store2 = SQLiteMemoryStore(self._db)
        try:
            got = store2.retrieve(mid)
            self.assertIsNotNone(got)
            self.assertEqual(got.description, "持久化记录")
            self.assertEqual(got.scene_type, "web")
            self.assertEqual(got.tags, ["测试"])
        finally:
            store2.close()

    def test_count_clear(self):
        self.assertEqual(self.store.count(), 0)
        self.store.save(_make("a"))
        self.store.save(_make("b"))
        self.assertEqual(self.store.count(), 2)
        n = self.store.clear()
        self.assertEqual(n, 2)
        self.assertEqual(self.store.count(), 0)

    def test_env_db_path_override(self):
        db2 = os.path.join(self._tmp, "env_override.db")
        old = os.environ.get("YHLZ_VISION_MEMORY_DB")
        os.environ["YHLZ_VISION_MEMORY_DB"] = db2
        try:
            store = SQLiteMemoryStore(None)
            self.assertEqual(store._db_path, db2)
            store.save(_make("env 路径"))
            self.assertTrue(os.path.exists(db2))
            store.close()
        finally:
            if old is None:
                os.environ.pop("YHLZ_VISION_MEMORY_DB", None)
            else:
                os.environ["YHLZ_VISION_MEMORY_DB"] = old

    def test_invalid_db_path_creates_dirs(self):
        db3 = os.path.join(self._tmp, "nested", "dirs", "mem.db")
        store = SQLiteMemoryStore(db3)
        try:
            store.save(_make("嵌套路径"))
            self.assertTrue(os.path.exists(db3))
            self.assertEqual(store.count(), 1)
        finally:
            store.close()


if __name__ == "__main__":
    unittest.main()
