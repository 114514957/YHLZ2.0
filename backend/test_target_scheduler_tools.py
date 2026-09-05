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


class TestSchedulerRegistration(unittest.TestCase):
    def setUp(self):
        self.registry = ToolRegistry()

    def test_register_min_set(self):
        names = setup_scheduler_tools(self.registry)
        self.assertEqual(sorted(names), ["ledger_search", "memory_recall", "memory_save", "system_time"])
        exported = self.registry.export_openai_tools()
        fn_names = {t["function"]["name"] for t in exported}
        self.assertTrue({"ledger_search", "memory_recall", "memory_save", "system_time"} <= fn_names)

    def test_category(self):
        setup_scheduler_tools(self.registry)
        cats = {t.category for t in self.registry.list_tools(category=SCHEDULER_CATEGORY)}
        self.assertTrue(cats)


if __name__ == "__main__":
    unittest.main()
