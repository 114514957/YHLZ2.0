"""Tests for the ledger CRUD store (backend/ledger_store.py).

All tests run against a throwaway ledger in a temp dir and disable index sync,
so the real docs/上下文台账.md and the search cache are never touched.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from backend import ledger_store as ls  # noqa: E402

SAMPLE = """# 测试台账

> 说明行。

## 记录 0001：初始建账

- 时间：2026-01-01
- 目标：只读探索
- 是否修改文件：否

## 记录 0002：首个决策

- 时间：2026-01-02
- 结论：采用方案 C。

"""


class LedgerStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "ledger.md"
        self.path.write_text(SAMPLE, encoding="utf-8")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _add(self, title, body, **kw):
        kw.setdefault("sync_index", False)
        return ls.add_record(title, body, path=self.path, **kw)

    # ---------- read ----------
    def test_parse_records(self):
        recs = ls.parse_records(path=self.path)
        self.assertEqual([r.no for r in recs], [1, 2])
        self.assertEqual(recs[0].title, "初始建账")
        self.assertIn("只读探索", recs[0].body_text())

    def test_next_record_no(self):
        self.assertEqual(ls.next_record_no(self.path), 3)

    def test_get_record(self):
        rec = ls.get_record(2, path=self.path)
        self.assertIsNotNone(rec)
        self.assertIn("方案 C", rec["text"])
        self.assertIsNone(ls.get_record(99, path=self.path))

    def test_search(self):
        hits = ls.search("决策", path=self.path)
        self.assertEqual([h["no"] for h in hits], [2])
        self.assertEqual(ls.search("不存在的词", path=self.path), [])

    def test_list_newest_first(self):
        rows = ls.list_records(path=self.path)
        self.assertEqual([r["no"] for r in rows], [2, 1])

    # ---------- add ----------
    def test_add_auto_number_and_stamp(self):
        res = self._add("新记录", "- 结论：已添加")
        self.assertEqual(res["no"], 3)
        text = self.path.read_text(encoding="utf-8")
        self.assertIn("## 记录 0003：新记录", text)
        self.assertIn("时间：", text)
        self.assertEqual(ls.next_record_no(self.path), 4)

    def test_add_explicit_no_conflict(self):
        self._add("临时", "- 内容", no=9)
        with self.assertRaises(ls.LedgerError):
            self._add("冲突", "- 内容", no=9)

    def test_add_refuses_sensitive(self):
        with self.assertRaises(ls.LedgerError):
            self._add("密钥", "- key: sk-abcdefgh1234")

    def test_add_multiline_body(self):
        self._add("多行", "第一行\n第二行\n\n第三行")
        rec = ls.get_record(ls.next_record_no(self.path) - 1, path=self.path)
        self.assertIn("第三行", rec["text"])

    # ---------- update ----------
    def test_update_title(self):
        ls.update_record(1, title="改名了", path=self.path, sync_index=False)
        self.assertEqual(ls.get_record(1, path=self.path)["title"], "改名了")

    def test_update_append(self):
        ls.update_record(1, append_lines="- 补充：新证据", path=self.path, sync_index=False)
        self.assertIn("新证据", ls.get_record(1, path=self.path)["text"])

    def test_update_replace_body(self):
        ls.update_record(1, replace_body="- 时间：2026-09-29\n- 全部重写",
                         path=self.path, sync_index=False)
        text = ls.get_record(1, path=self.path)["text"]
        self.assertIn("全部重写", text)
        self.assertNotIn("只读探索", text)

    def test_update_missing(self):
        with self.assertRaises(ls.LedgerError):
            ls.update_record(77, title="x", path=self.path, sync_index=False)

    def test_update_noop(self):
        with self.assertRaises(ls.LedgerError):
            ls.update_record(1, path=self.path, sync_index=False)

    # ---------- delete ----------
    def test_delete_requires_confirm(self):
        with self.assertRaises(ls.LedgerError):
            ls.delete_record(1, path=self.path, sync_index=False)

    def test_delete_ok(self):
        ls.delete_record(1, path=self.path, confirm=True, sync_index=False)
        self.assertIsNone(ls.get_record(1, path=self.path))
        self.assertIsNotNone(ls.get_record(2, path=self.path))

    # ---------- integrity ----------
    def test_backup_created(self):
        import backend.ledger_store as mod
        old = mod.BACKUP_DIR
        mod.BACKUP_DIR = Path(self.tmp.name) / "bak"
        try:
            self._add("备份测试", "- 内容")
            files = list(mod.BACKUP_DIR.glob("*.md"))
            self.assertGreaterEqual(len(files), 1)
        finally:
            mod.BACKUP_DIR = old

    def test_preamble_preserved(self):
        self._add("保留前言", "- 内容")
        text = self.path.read_text(encoding="utf-8")
        self.assertIn("# 测试台账", text)
        self.assertIn("> 说明行。", text)

    def test_sensitive_scan(self):
        self.assertTrue(ls.sensitive_hits("token sk-abcdefgh1234"))
        self.assertFalse(ls.sensitive_hits("普通文本，无密钥"))


if __name__ == "__main__":
    unittest.main()
