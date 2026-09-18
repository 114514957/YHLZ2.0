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
             "file_list", "file_read", "kb_add", "kb_query", "ledger_search",
             "memory_audit", "memory_profile", "memory_recall", "memory_save", "owner_approve", "qq_bootstrap", "qq_digest", "qq_export", "qq_process",
             "qq_runbatch", "qq_shutdown", "qq_status", "qq_summarize", "report_qq_weekly", "schedule_plan", "skill_add", "skill_feedback", "skill_search", "system_time", "task_plan",
             "web_fetch", "web_search"],
        )
        exported = self.registry.export_openai_tools()
        fn_names = {t["function"]["name"] for t in exported}
        self.assertTrue(fn_names >= {"ledger_search", "memory_recall",
                                     "memory_save", "system_time", "diary_write"})

    def test_category(self):
        setup_scheduler_tools(self.registry)
        cats = {t.category for t in self.registry.list_tools(category=SCHEDULER_CATEGORY)}
        self.assertTrue(cats)


class TestLedgerQueryVariants(unittest.TestCase):
    """Multi-variant ledger search (ledger 0425)."""

    def test_squeeze_strips_question_words(self):
        from backend.target_scheduler_tools import _squeeze_query

        self.assertEqual(_squeeze_query("上次 v6 训练的结果怎么样"), "v6 训练的结果")
        self.assertEqual(_squeeze_query("查一下元亨的日记"), "元亨的日记")
        self.assertEqual(_squeeze_query("上次"), "")

    def test_bigram_expand_no_space_query(self):
        from backend.target_scheduler_tools import _bigram_expand

        self.assertEqual(_bigram_expand("训练结果"), "训练 练结 结果")
        self.assertEqual(_bigram_expand("v6训练结果"), "v6训练 练结 结果")

    def test_merge_hits_keeps_best_and_ranks(self):
        from backend.target_scheduler_tools import _merge_hits

        a = [{"docid": "d1", "score": 1.0, "confidence": 0.5},
             {"docid": "d2", "score": 2.0, "confidence": 0.9}]
        b = [{"docid": "d1", "score": 3.0, "confidence": 0.7}]
        out = _merge_hits([a, b])
        self.assertEqual([h["docid"] for h in out], ["d2", "d1"])
        self.assertEqual(out[1]["score"], 3.0)  # best copy kept

    def test_sentence_query_brings_result_records(self):
        result = ledger_search("上次 v6 训练的结果怎么样", limit=8)
        self.assertIn("[ledger:", result)
        self.assertIn("v6", result)
        self.assertGreaterEqual(result.count("[ledger:"), 2)

    def test_no_space_query_is_not_empty(self):
        result = ledger_search("训练结果", limit=5)
        self.assertIn("[ledger:", result)


if __name__ == "__main__":
    unittest.main()
