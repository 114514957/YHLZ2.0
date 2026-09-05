"""Keyword-index (inverted catalog) tests — ledger 0148 plan."""

import tempfile
import unittest
from pathlib import Path

from backend.target_kw_index import KeywordIndex, tokenize


class TestTokenizer(unittest.TestCase):
    def test_latin_and_cjk_mixed(self):
        toks = tokenize("麦克风 mic 测试 Mic")
        self.assertEqual(toks.get("mic"), 2)
        self.assertIn("麦克", toks)
        self.assertIn("克风", toks)
        self.assertIn("麦克风", toks)

    def test_empty(self):
        self.assertEqual(tokenize("  .?! "), {})


class TestKeywordIndex(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.kw = KeywordIndex(Path(self.tmp.name) / "kw.db")

    def tearDown(self):
        self.tmp.cleanup()

    def test_upsert_and_query_cjk(self):
        self.kw.upsert_doc(docid="ledger:0141:1", source="ledger",
                           summary="麦克风物理增益极低", record_title="记录0141")
        rows = self.kw.query("麦克风")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["docid"], "ledger:0141:1")
        self.assertGreater(rows[0]["score"], 0)

    def test_upsert_idempotent(self):
        self.kw.upsert_doc(docid="x1", source="l2", summary="记忆")
        self.kw.upsert_doc(docid="x1", source="l2", summary="记忆")
        rows = self.kw.query("记忆")
        self.assertEqual(len(rows), 1)
        self.assertEqual(self.kw.count(), 1)

    def test_delete_doc(self):
        self.kw.upsert_doc(docid="x1", source="l2", summary="记忆测试")
        self.kw.delete_doc("x1")
        self.assertEqual(self.kw.query("记忆"), [])
        self.assertEqual(self.kw.count(), 0)

    def test_ranking_prefers_more_matches(self):
        self.kw.upsert_doc(docid="a", source="ledger", summary="麦克风")
        self.kw.upsert_doc(docid="b", source="ledger", summary="麦克风物理增益极低麦克风")
        rows = self.kw.query("麦克风")
        self.assertEqual(rows[0]["docid"], "b")

    def test_source_filter(self):
        self.kw.upsert_doc(docid="a", source="ledger", summary="麦克风")
        self.kw.upsert_doc(docid="b", source="l2", summary="麦克风")
        rows = self.kw.query("麦克风", source="l2")
        self.assertEqual([r["docid"] for r in rows], ["b"])

    def test_status_filter_hides_cold(self):
        self.kw.upsert_doc(docid="a", source="ledger", summary="麦克风", status="archive")
        self.assertEqual(self.kw.query("麦克风"), [])

    def test_english_query(self):
        self.kw.upsert_doc(docid="a", source="ledger", summary="Ollama 本地模型")
        self.assertEqual(len(self.kw.query("ollama")), 1)

    def test_health_counts(self):
        self.kw.upsert_doc(docid="a", source="ledger", summary="记忆测试文本")
        h = self.kw.health()
        self.assertEqual(h["docs"], 1)
        self.assertGreater(h["terms"], 0)


if __name__ == "__main__":
    unittest.main()
