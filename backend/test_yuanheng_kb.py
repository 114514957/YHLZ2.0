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

    def test_sentence_query_trigram_fallback(self):
        """R2(0656)：中文整句查询无分隔符时，3-gram 重叠兜底应能召回。"""
        kb.kb_add("变调算法用 WORLD 比 PSOLA 更稳", category="tech")
        hits = kb.kb_query("查查知识库里变调算法的条目。")
        self.assertGreaterEqual(len(hits), 1)
        self.assertTrue(any("变调" in h["summary"] for h in hits))
        # 无关条目不得因兜底被顶上来
        kb.kb_add("今天天气不错适合出门散步", category="fact")
        hits2 = kb.kb_query("查查知识库里变调算法的条目。")
        self.assertTrue(all("变调" in h["summary"] for h in hits2))

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

    def test_wake_hit_public_safe_no_side_effects(self):
        kb.kb_add("ollama 本地推理建议开启 KV cache 量化以省显存", category="tech",
                  source="qq:g1")
        kb.kb_add("元亨最喜欢的摸鱼方式是发呆不写代码", category="method",
                  source="自主")
        hit = kb.kb_wake_hit("大家聊聊 ollama 的 KV cache 量化怎么开")
        self.assertIsNotNone(hit)
        self.assertIn("ollama", hit["summary"])
        # 私人来源的条目不算"知道的信息"（公共安全子集）
        self.assertIsNone(kb.kb_wake_hit("元亨最喜欢的摸鱼方式是发呆不写代码"))
        # 探针无副作用：uses 必须保持 0
        import sqlite3

        con = sqlite3.connect(str(kb.DEFAULT_KB_DB))
        uses = [r[0] for r in con.execute("SELECT uses FROM kb_items")]
        con.close()
        self.assertTrue(uses and all(v == 0 for v in uses))

    def test_wake_hit_min_chars(self):
        kb.kb_add("变调算法用 WORLD 比 PSOLA 更稳", category="tech")
        self.assertIsNone(kb.kb_wake_hit("变调", min_chars=4))
        self.assertIsNotNone(kb.kb_wake_hit("变调算法怎么调", min_chars=4))


if __name__ == "__main__":
    unittest.main()
