"""
YHLZ Embodied AI V6.0 - 记忆索引单元测试 (Memory Index)

覆盖 (memory/memory_index.py):
    - 登记 / 更新 / 注销
    - 组合查询 (类型/阶段/价值)
    - 白名单校验 / 上限 / 统计
"""
import unittest

from backend.embodied.companion.memory import (
    MEMORY_STAGES,
    MEMORY_TYPES,
    IndexError,
    MemoryIndex,
)


class TestIndexInit(unittest.TestCase):
    """初始化与白名单"""

    def test_default_init(self):
        m = MemoryIndex()
        self.assertIsNotNone(m)

    def test_max_entries_validation(self):
        with self.assertRaises(IndexError):
            MemoryIndex(max_entries=0)

    def test_memory_types(self):
        for t in ("identity", "relationship", "experience",
                  "reflection", "creative"):
            self.assertIn(t, MEMORY_TYPES)

    def test_memory_stages(self):
        for s in ("active", "cold", "archive", "recycle"):
            self.assertIn(s, MEMORY_STAGES)


class TestRegister(unittest.TestCase):
    """登记"""

    def setUp(self):
        self.idx = MemoryIndex()

    def test_register(self):
        e = self.idx.register("e1", "experience")
        self.assertEqual(e["record_id"], "e1")
        self.assertEqual(e["type"], "experience")
        self.assertEqual(e["stage"], "active")

    def test_register_empty_id(self):
        with self.assertRaises(IndexError):
            self.idx.register("", "experience")

    def test_register_bad_type(self):
        with self.assertRaises(IndexError):
            self.idx.register("e1", "bogus")

    def test_register_bad_stage(self):
        with self.assertRaises(IndexError):
            self.idx.register("e1", "experience", stage="frozen")

    def test_register_value_range(self):
        with self.assertRaises(IndexError):
            self.idx.register("e1", "experience", value=1.5)

    def test_register_value_negative(self):
        with self.assertRaises(IndexError):
            self.idx.register("e1", "experience", value=-0.1)

    def test_register_with_meta(self):
        e = self.idx.register("e1", "experience", meta={"k": "v"})
        self.assertEqual(e["meta"]["k"], "v")

    def test_register_update_existing(self):
        self.idx.register("e1", "experience", value=0.3)
        self.idx.register("e1", "experience", value=0.9)
        self.assertEqual(self.idx.get("e1")["value"], 0.9)

    def test_register_max_entries(self):
        idx = MemoryIndex(max_entries=2)
        idx.register("a", "experience")
        idx.register("b", "experience")
        with self.assertRaises(IndexError):
            idx.register("c", "experience")

    def test_register_max_existing_allowed(self):
        idx = MemoryIndex(max_entries=1)
        idx.register("a", "experience")
        e = idx.register("a", "experience", value=0.5)
        self.assertEqual(e["value"], 0.5)


class TestUpdate(unittest.TestCase):
    """更新"""

    def setUp(self):
        self.idx = MemoryIndex()
        self.idx.register("e1", "experience", stage="active",
                          value=0.5, importance=0.3)

    def test_update_stage(self):
        self.idx.update("e1", stage="cold")
        self.assertEqual(self.idx.get("e1")["stage"], "cold")

    def test_update_value(self):
        self.idx.update("e1", value=0.9)
        self.assertEqual(self.idx.get("e1")["value"], 0.9)

    def test_update_importance(self):
        self.idx.update("e1", importance=1.2)
        self.assertEqual(self.idx.get("e1")["importance"], 1.2)

    def test_update_missing(self):
        self.assertIsNone(self.idx.update("nope", stage="cold"))

    def test_update_bad_stage(self):
        with self.assertRaises(IndexError):
            self.idx.update("e1", stage="bad")

    def test_update_bad_value(self):
        with self.assertRaises(IndexError):
            self.idx.update("e1", value=2.0)

    def test_update_partial_keeps_rest(self):
        self.idx.update("e1", value=0.7)
        e = self.idx.get("e1")
        self.assertEqual(e["type"], "experience")
        self.assertEqual(e["importance"], 0.3)


class TestUnregister(unittest.TestCase):
    """注销"""

    def setUp(self):
        self.idx = MemoryIndex()
        self.idx.register("e1", "experience")

    def test_unregister(self):
        self.assertTrue(self.idx.unregister("e1"))
        self.assertIsNone(self.idx.get("e1"))

    def test_unregister_missing(self):
        self.assertFalse(self.idx.unregister("nope"))

    def test_unregister_frees_slot(self):
        idx = MemoryIndex(max_entries=1)
        idx.register("a", "experience")
        idx.unregister("a")
        idx.register("b", "experience")
        self.assertIsNotNone(idx.get("b"))


class TestQuery(unittest.TestCase):
    """查询"""

    def setUp(self):
        self.idx = MemoryIndex()
        self.idx.register("e1", "experience", stage="active",
                          value=0.9, importance=1.5)
        self.idx.register("e2", "experience", stage="cold",
                          value=0.4, importance=0.5)
        self.idx.register("r1", "reflection", stage="archive",
                          value=0.8, importance=1.0)
        self.idx.register("c1", "creative", stage="active",
                          value=0.7, importance=0.9)

    def test_query_all(self):
        hits = self.idx.query()
        self.assertEqual(len(hits), 4)

    def test_query_by_type(self):
        hits = self.idx.query(mtype="experience")
        self.assertEqual(len(hits), 2)

    def test_query_by_stage(self):
        hits = self.idx.query(stage="active")
        self.assertEqual(len(hits), 2)

    def test_query_value_min(self):
        hits = self.idx.query(value_min=0.7)
        self.assertEqual(len(hits), 3)

    def test_query_importance_min(self):
        hits = self.idx.query(importance_min=1.0)
        self.assertEqual(len(hits), 2)

    def test_query_combined(self):
        hits = self.idx.query(mtype="experience", stage="active")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["record_id"], "e1")

    def test_query_sorted_by_importance(self):
        hits = self.idx.query()
        importances = [h["importance"] for h in hits]
        self.assertEqual(importances,
                         sorted(importances, reverse=True))

    def test_query_limit(self):
        hits = self.idx.query(limit=2)
        self.assertEqual(len(hits), 2)

    def test_query_no_match(self):
        self.assertEqual(self.idx.query(mtype="identity"), [])


class TestStatsAndClear(unittest.TestCase):
    """统计与清空"""

    def setUp(self):
        self.idx = MemoryIndex()
        self.idx.register("e1", "experience", stage="active")
        self.idx.register("e2", "experience", stage="cold")
        self.idx.register("r1", "reflection", stage="active")

    def test_stats_structure(self):
        st = self.idx.stats()
        for key in ("mode", "total", "by_type", "by_stage"):
            self.assertIn(key, st)

    def test_stats_counts(self):
        st = self.idx.stats()
        self.assertEqual(st["total"], 3)
        self.assertEqual(st["by_type"]["experience"], 2)
        self.assertEqual(st["by_stage"]["active"], 2)

    def test_clear(self):
        self.assertEqual(self.idx.clear(), 3)
        self.assertEqual(self.idx.stats()["total"], 0)

    def test_clear_empty(self):
        idx = MemoryIndex()
        self.assertEqual(idx.clear(), 0)

    def test_get_after_clear(self):
        self.idx.clear()
        self.assertIsNone(self.idx.get("e1"))


if __name__ == "__main__":
    unittest.main()
