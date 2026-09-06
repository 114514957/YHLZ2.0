"""Tests for Yuanheng KB store."""
import tempfile
import unittest
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend import yuanheng_kb as kb  # noqa: E402


class KbTest(unittest.TestCase):
    def setUp(self):
        tmp = Path(tempfile.mkdtemp()) / "kb.db"
        self._orig = kb.DEFAULT_KB_DB
        kb.DEFAULT_KB_DB = tmp

    def tearDown(self):
        kb.DEFAULT_KB_DB = self._orig

    def test_add_query_stats(self):
        r = kb.kb_add("ollama 本地推理建议开启 KV cache 量化以省显存", category="tech",
                      source="qq:test")
        self.assertTrue(r.startswith("已入库"), r)
        r2 = kb.kb_add("ollama 本地推理建议开启KV cache 量化省显存",
                       category="tech")
        self.assertIn("重复", r2)
        hits = kb.kb_query("ollama KV cache 量化")
        self.assertGreaterEqual(len(hits), 1)
        self.assertEqual(hits[0]["category"], "tech")
        st = kb.kb_stats()
        self.assertEqual(st["items"], 1)
        self.assertEqual(st["by_category"], {"tech": 1})

    def test_category_default(self):
        kb.kb_add("未知类别时应当落入 tech 默认", category="whatever")
        st = kb.kb_stats()
        self.assertEqual(st["by_category"], {"tech": 1})

    def test_digest_uses_kb(self):
        from backend import qqextract

        # write into kb with today timestamp then digest must include it
        import time as _t

        kb.kb_add("今日新学：llama.cpp 支持多并发 prefill 提速百倍", category="tech",
                  source="qq:g1", created_at=_t.time())
        f = qqextract.digest(_t.strftime("%Y-%m-%d"))
        content = Path(f).read_text(encoding="utf-8")
        self.assertIn("llama.cpp", content)
        self.assertIn("今日新学", content)


if __name__ == "__main__":
    unittest.main()
