"""
测试: memory 子系统 (SQLite 存储 + Manager)
覆盖: CRUD / 搜索 / 对话存储 / 自动提取 / 短期记忆 / 衰减
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from backend.agent.memory.base import MemoryEntry
from backend.agent.memory.sqlite_store import SQLiteMemoryStore
from backend.agent.memory.manager import MemoryManager, reset_memory_manager


class TestSQLiteMemoryStore(unittest.TestCase):
    """SQLite 存储层"""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="yhlz_agent_mem_")
        self.db_path = os.path.join(self.tmp_dir, "test_mem.db")
        self.store = SQLiteMemoryStore(db_path=self.db_path)

    def tearDown(self):
        self.store.close()
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_add_and_get(self):
        entry = MemoryEntry.create(content="用户喜欢咖啡", category="preference")
        mid = self.store.add(entry)
        self.assertEqual(mid, entry.id)
        got = self.store.get(mid)
        self.assertIsNotNone(got)
        self.assertEqual(got.content, "用户喜欢咖啡")
        self.assertEqual(got.category, "preference")

    def test_get_nonexistent(self):
        self.assertIsNone(self.store.get("nonexistent_id"))

    def test_update(self):
        entry = MemoryEntry.create(content="test", category="fact")
        self.store.add(entry)
        ok = self.store.update(entry.id, content="updated", weight=0.5)
        self.assertTrue(ok)
        got = self.store.get(entry.id)
        self.assertEqual(got.content, "updated")
        self.assertEqual(got.weight, 0.5)

    def test_delete(self):
        entry = MemoryEntry.create(content="to delete")
        mid = self.store.add(entry)
        self.assertTrue(self.store.delete(mid))
        self.assertIsNone(self.store.get(mid))
        self.assertFalse(self.store.delete(mid))

    def test_list_all(self):
        for i in range(5):
            self.store.add(MemoryEntry.create(content=f"item{i}", category="fact"))
        items = self.store.list_all(limit=10)
        self.assertEqual(len(items), 5)

    def test_list_by_category(self):
        self.store.add(MemoryEntry.create(content="f1", category="fact"))
        self.store.add(MemoryEntry.create(content="p1", category="preference"))
        facts = self.store.list_all(category="fact")
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0].content, "f1")

    def test_search_chinese(self):
        """中文关键词搜索"""
        self.store.add(MemoryEntry.create(content="用户喜欢喝咖啡", category="preference"))
        self.store.add(MemoryEntry.create(content="今天天气不错", category="fact"))
        results = self.store.search("咖啡")
        self.assertGreater(len(results), 0)
        self.assertIn("咖啡", results[0].content)

    def test_search_english(self):
        """英文关键词搜索"""
        self.store.add(MemoryEntry.create(content="user loves python", category="fact"))
        results = self.store.search("python")
        self.assertGreater(len(results), 0)

    def test_search_empty_query(self):
        """空查询返回空"""
        self.store.add(MemoryEntry.create(content="test"))
        self.assertEqual(self.store.search(""), [])

    def test_count(self):
        self.store.add(MemoryEntry.create(content="a", category="fact"))
        self.store.add(MemoryEntry.create(content="b", category="preference"))
        self.assertEqual(self.store.count(), 2)
        self.assertEqual(self.store.count("fact"), 1)

    def test_clear(self):
        self.store.add(MemoryEntry.create(content="a"))
        self.store.add(MemoryEntry.create(content="b"))
        n = self.store.clear()
        self.assertEqual(n, 2)
        self.assertEqual(self.store.count(), 0)


class TestMemoryManager(unittest.TestCase):
    """记忆管理器"""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="yhlz_mgr_")
        self.db_path = os.path.join(self.tmp_dir, "mgr.db")
        os.environ["YHLZ_AGENT_MEMORY_DB"] = self.db_path
        reset_memory_manager()
        self.mgr = MemoryManager(store=SQLiteMemoryStore(db_path=self.db_path), enable_auto_extract=False)

    def tearDown(self):
        self.mgr.close()
        reset_memory_manager()
        os.environ.pop("YHLZ_AGENT_MEMORY_DB", None)
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_add_and_get(self):
        async def run():
            mid = await self.mgr.add_async("hello", category="fact")
            self.assertTrue(mid.startswith("mem_"))
            got = await self.mgr.get_async(mid)
            self.assertIsNotNone(got)
            self.assertEqual(got.content, "hello")
        asyncio.run(run())

    def test_invalid_category(self):
        with self.assertRaises(Exception):
            self.mgr.add("test", category="invalid_category")

    def test_search(self):
        async def run():
            await self.mgr.add_async("用户喜欢红茶", "preference")
            results = await self.mgr.search_async("红茶")
            self.assertGreater(len(results), 0)
        asyncio.run(run())

    def test_store_dialogue(self):
        """存储对话 (不自动提取)"""
        async def run():
            n = await self.mgr.store_dialogue_async("你好", "你好哥们", extract=False)
            self.assertEqual(n, 1)  # 只存对话记忆
        asyncio.run(run())

    def test_store_dialogue_with_extract(self):
        """存储对话 + 规则提取"""
        mgr = MemoryManager(
            store=SQLiteMemoryStore(db_path=self.db_path),
            enable_auto_extract=True,
            llm_adapter=None,  # 用规则提取
        )
        async def run():
            n = await mgr.store_dialogue_async("我喜欢喝咖啡", "好的, 记住了", extract=True)
            self.assertGreaterEqual(n, 1)  # 至少 1 条对话记忆
            # 可能提取出偏好
            facts = await mgr.search_async("喜欢")
            self.assertGreater(len(facts), 0)
        asyncio.run(run())

    def test_short_term_memory(self):
        """短期记忆"""
        async def run():
            await self.mgr.store_dialogue_async("q1", "a1", extract=False)
            await self.mgr.store_dialogue_async("q2", "a2", extract=False)
            items = self.mgr.get_short_term()
            self.assertEqual(len(items), 2)
            self.assertEqual(items[-1]["user"], "q2")
        asyncio.run(run())

    def test_clear(self):
        async def run():
            await self.mgr.add_async("a")
            await self.mgr.add_async("b")
            n = await self.mgr.clear_async()
            self.assertEqual(n, 2)
            self.assertEqual(await self.mgr.count_async(), 0)
        asyncio.run(run())

    def test_delete_and_update(self):
        async def run():
            mid = await self.mgr.add_async("to delete")
            ok = await self.mgr.delete_async(mid)
            self.assertTrue(ok)
            self.assertIsNone(await self.mgr.get_async(mid))

            mid2 = await self.mgr.add_async("to update")
            ok2 = await self.mgr.update_async(mid2, content="updated")
            self.assertTrue(ok2)
            got = await self.mgr.get_async(mid2)
            self.assertEqual(got.content, "updated")
        asyncio.run(run())


if __name__ == "__main__":
    unittest.main(verbosity=2)
