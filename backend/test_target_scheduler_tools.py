"""Scheduler tool set tests (ledger 0144 minimum set)."""

import unittest

from backend.agent.tool_registry import ToolRegistry
from backend.target_scheduler_tools import (
    ledger_search,
    recall_memory,
    setup_scheduler_tools,
    system_time,
    SCHEDULER_CATEGORY,
)


class TestSchedulerHandlers(unittest.TestCase):
    def test_ledger_search_finds_anchor(self):
        result = ledger_search("元亨")
        self.assertIsInstance(result, str)
        self.assertTrue(result)

    def test_ledger_search_empty_query(self):
        result = ledger_search("")
        self.assertIn("未找到", result)

    def test_system_time_string(self):
        result = system_time()
        self.assertGreater(len(result), 10)
        self.assertIn("星期", result)

    def test_recall_memory_shape(self):
        result = recall_memory("不存在的内容xy")
        self.assertIsInstance(result, str)

    def test_diary_write_list_delete(self):
        import tempfile
        import time
        from pathlib import Path

        import backend.target_scheduler_tools as st

        tmp = Path(tempfile.mkdtemp()) / "diary.md"
        old = st.DIARY_FILE
        st.DIARY_FILE = tmp
        try:
            self.assertIn("已写入", st.diary_write("今天天气不错，想写点什么"))
            time.sleep(1.1)
            self.assertIn("已写入", st.diary_write("第二条：我想了很多"))
            listing = st.diary_list(limit=2)
            self.assertIn("第二条", listing)
            stamp = listing.split("## ")[1].split("\n")[0].strip()
            self.assertIn("已删除", st.diary_delete(stamp))
            self.assertNotIn("第二条", st.diary_list(limit=5))
        finally:
            st.DIARY_FILE = old


class TestSchedulerRegistration(unittest.TestCase):
    def setUp(self):
        self.registry = ToolRegistry()

    def test_register_min_set(self):
        names = setup_scheduler_tools(self.registry)
        self.assertEqual(
            sorted(names),
            ["diary_delete", "diary_list", "diary_write",
             "file_list", "file_read", "ledger_search", "memory_recall",
             "memory_save", "system_time", "task_plan", "web_fetch", "web_search"],
        )
        exported = self.registry.export_openai_tools()
        fn_names = {t["function"]["name"] for t in exported}
        self.assertTrue(fn_names >= {"ledger_search", "memory_recall",
                                     "memory_save", "system_time", "diary_write"})

    def test_category(self):
        setup_scheduler_tools(self.registry)
        cats = {t.category for t in self.registry.list_tools(category=SCHEDULER_CATEGORY)}
        self.assertTrue(cats)


if __name__ == "__main__":
    unittest.main()
