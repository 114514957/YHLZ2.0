"""Ledger v2（记录级 FTS5）测试：2026-11-13 P0。"""
import tempfile
import unittest
from pathlib import Path

from backend.ledger_index_v2 import LedgerV2, parse_records, tokens

LEDGER = """# 测试台账

## 记录 0001：黄金样本整理

- 时间：2026-11-01
- 决策：黄金样本放到 docs/素材。

## 记录 0002：翻唱投产

- 时间：2026-11-06
- 结论：S1-S7 全跑通，Kim 分轨。

## 记录 0002：翻唱投产（重复编号）

- 时间：2026-11-06
- 状态：重复的标题，验证去重。

## 记录 0003：显存预算

- 时间：2026-11-08
- 踩坑：训练台默认 4.5GB，改成 5GB。
"""


class LedgerV2Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.ledger = self.root / "ledger.md"
        self.ledger.write_text(LEDGER, encoding="utf-8")
        self.db = self.root / "v2.db"

    def tearDown(self):
        self.tmp.cleanup()

    def test_tokens_bigram(self):
        t = tokens("黄金样本")
        self.assertIn("黄金", t)
        self.assertIn("样本", t)

    def test_parse_and_build(self):
        recs = parse_records(self.ledger)
        self.assertEqual(len(recs), 4)
        lv = LedgerV2(self.db)
        info = lv.rebuild(self.ledger)
        self.assertEqual(info["records"], 4)
        self.assertTrue(self.db.exists())

    def test_search_record_level(self):
        lv = LedgerV2(self.db)
        lv.rebuild(self.ledger)
        hits = lv.search("黄金样本", limit=3, ledger=self.ledger)
        self.assertTrue(hits)
        self.assertEqual(hits[0]["rec"], 1)
        self.assertIn("黄金", hits[0]["snippet"])

    def test_search_dedupes_record_number(self):
        lv = LedgerV2(self.db)
        lv.rebuild(self.ledger)
        hits = lv.search("翻唱投产", limit=5, ledger=self.ledger)
        recs = [h["rec"] for h in hits]
        self.assertEqual(recs.count(2), 1)

    def test_filters(self):
        lv = LedgerV2(self.db)
        lv.rebuild(self.ledger)
        hits = lv.search("", limit=5)  # 空查询直接返回 []
        self.assertEqual(hits, [])
        hits = lv.search("时间", limit=5, since="2026-11-07", ledger=self.ledger)
        # 只有 0003 的日期在 11-07 之后
        self.assertTrue(all(h["ts"] >= "2026-11-07" for h in hits))
        hits = lv.search("翻唱", limit=5, kind="结论", ledger=self.ledger)
        self.assertTrue(all(h["kind"] == "结论" for h in hits))

    def test_ensure_fresh_rebuilds_on_change(self):
        lv = LedgerV2(self.db)
        lv.rebuild(self.ledger)
        self.assertIsNone(lv.ensure_fresh(self.ledger))
        with self.ledger.open("a", encoding="utf-8") as f:
            f.write("\n## 记录 0004：新记录\n\n- 时间：2026-11-09\n- 结论：新增。\n")
        info = lv.ensure_fresh(self.ledger)
        self.assertIsNotNone(info)
        hits = lv.search("新增", limit=3, ledger=self.ledger)
        self.assertTrue(hits)


if __name__ == "__main__":
    unittest.main()
