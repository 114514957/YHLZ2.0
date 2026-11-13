"""台账写入结构化（2026-11-13）：元数据行 + 标题查重。"""
import tempfile
import unittest
from pathlib import Path

from backend import ledger_store as ls
from backend.ledger_index_v2 import parse_records
from backend.target_scheduler_tools import _duplicate_titles


class LedgerWriteMetaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "ledger.md"
        self.path.write_text("# 测试台账\n", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_metadata_line_written_and_parsed(self):
        ls.add_record("结构化写入", "- 正文", path=self.path,
                      tags="检索,索引", kind="结论", links="1,2",
                      status="active", sync_index=False)
        text = self.path.read_text(encoding="utf-8")
        self.assertIn("- 元数据：kind=结论；tags=检索,索引；links=1,2；status=active", text)
        rec = parse_records(self.path)[0]
        self.assertEqual(rec["kind"], "结论")
        self.assertEqual(rec["tags"], "检索,索引")
        self.assertEqual(rec["links"], "1,2")
        self.assertEqual(rec["status"], "active")

    def test_no_metadata_line_when_empty(self):
        ls.add_record("无元数据", "- 正文", path=self.path, sync_index=False)
        self.assertNotIn("元数据：", self.path.read_text(encoding="utf-8"))

    def test_duplicate_titles_exact_and_similar(self):
        ls.add_record("翻唱投产验收", "- 正文", path=self.path, sync_index=False)
        ls.add_record("工作台 UI 改版", "- 正文", path=self.path, sync_index=False)
        exact = _duplicate_titles("翻唱投产验收", path=self.path)
        self.assertEqual(exact[0]["no"], 1)
        similar = _duplicate_titles("翻唱投产验收记录", path=self.path)
        self.assertTrue(similar)
        self.assertEqual(similar[0]["no"], 1)
        none = _duplicate_titles("完全不同的标题内容", path=self.path)
        self.assertEqual(none, [])


if __name__ == "__main__":
    unittest.main()
