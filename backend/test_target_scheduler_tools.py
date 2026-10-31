"""Scheduler tool set tests (ledger 0144 minimum set)."""

import unittest
from pathlib import Path

from backend.target_scheduler_tools import (
    ledger_search,
    recall_memory,
    system_time,
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


class TestLedgerIndexFreshFallback(unittest.TestCase):
    def test_stale_catalog_falls_back_to_current_ledger(self):
        import tempfile
        import time
        import backend.target_scheduler_tools as st
        from backend.target_kw_index import KeywordIndex

        with tempfile.TemporaryDirectory() as td:
            root = Path(td); db = root / "kw.db"; ledger = root / "ledger.md"
            ledger.write_text("## 记录 0001：新记录\n结论：刚刚追加的MCP修复\n", encoding="utf-8")
            kw = KeywordIndex(db)
            kw.upsert_doc(docid="ledger:old:1", source="ledger", summary="旧索引内容")
            con = kw._conn(writable=True)
            con.execute("CREATE TABLE kw_meta (key TEXT PRIMARY KEY, val REAL)")
            con.execute("INSERT INTO kw_meta VALUES ('ledger_built_at', ?)", (0.0,))
            con.commit(); con.close()
            old_ledger, old_cache = st.LEDGER, st._KW_CACHE
            st.LEDGER = ledger; st._KW_CACHE = {"default": kw}
            try:
                result = st.ledger_search("刚刚追加的MCP修复", limit=3)
            finally:
                st.LEDGER, st._KW_CACHE = old_ledger, old_cache
            self.assertIn("[ledger:0001:2]", result)
            self.assertIn("刚刚追加的MCP修复", result)

class TestLedgerIndexRebuild(unittest.TestCase):
    def test_bulk_rebuild_replaces_only_ledger_source(self):
        import tempfile
        from backend.target_kw_index import KeywordIndex
        from tools.ledger_mem_import import index_ledger_all_rows

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db = root / "kw.db"
            ledger = root / "ledger.md"
            ledger.write_text(
                "## 记录 0001：测试\n结论：MCP检索恢复\n"
                "## 记录 0002：另一个\n- 全双工正常\n",
                encoding="utf-8",
            )
            kw = KeywordIndex(db)
            kw.upsert_doc(docid="memory:1", source="l2", summary="保留的记忆")
            count = index_ledger_all_rows(ledger, db_path=db)
            self.assertEqual(count, 2)
            self.assertTrue(kw.query("MCP检索", source="ledger"))
            self.assertTrue(kw.query("保留的记忆", source="l2"))
            ledger.write_text("## 记录 0003：新版本\n结论：只保留新内容\n", encoding="utf-8")
            count = index_ledger_all_rows(ledger, db_path=db)
            self.assertEqual(count, 1)
            self.assertFalse(kw.query("MCP检索", source="ledger"))
            self.assertTrue(kw.query("新版本", source="ledger"))
            self.assertTrue(kw.query("保留的记忆", source="l2"))

    def test_empty_batch_clears_stale_ledger_rows(self):
        import tempfile
        from backend.target_kw_index import KeywordIndex
        from tools.ledger_mem_import import index_ledger_all_rows

        with tempfile.TemporaryDirectory() as td:
            root = Path(td); db = root / "kw.db"; ledger = root / "ledger.md"
            ledger.write_text("## 记录 0001：旧\n结论：旧索引\n", encoding="utf-8")
            index_ledger_all_rows(ledger, db_path=db)
            ledger.write_text("# 只有标题\n", encoding="utf-8")
            self.assertEqual(index_ledger_all_rows(ledger, db_path=db), 0)
            self.assertFalse(KeywordIndex(db).query("旧索引", source="ledger"))


if __name__ == "__main__":
    unittest.main()
