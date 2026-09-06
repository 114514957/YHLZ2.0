"""Tests for qqextract: cursor, JSON parse, storage, digest."""
import json
import tempfile
import asyncio
import unittest
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend import qqextract  # noqa: E402


class FakeLLM:
    def __init__(self, out):
        self.out = out

    async def __call__(self, messages, tools):
        return {"content": self.out}


class QqextractTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.old_cand = qqextract.CAND_DIR
        self.old_state = qqextract.STATE_FILE
        self.old_db = qqextract.L2_DB
        qqextract.CAND_DIR = self.tmp
        qqextract.STATE_FILE = self.tmp / "state.json"
        db = self.tmp / "mem.db"
        qqextract.L2_DB = db
        self.db = db
        (self.tmp / "all.jsonl").write_text(
            "\n".join([
                json.dumps({"group_id": "1", "text": "x" * 100, "ts": 1}, ensure_ascii=False),
                json.dumps({"group_id": "2", "text": "y" * 100, "ts": 2}, ensure_ascii=False),
            ]),
            encoding="utf-8",
        )

    def tearDown(self):
        qqextract.CAND_DIR = self.old_cand
        qqextract.STATE_FILE = self.old_state
        qqextract.L2_DB = self.old_db

    def test_cursor_pending(self):
        items, total = qqextract.read_pending_candidates(max_items=5)
        self.assertEqual(len(items), 2)
        self.assertEqual(total, 2)
        qqextract._save_state({"processed_lines": total})
        items2, _ = qqextract.read_pending_candidates()
        self.assertEqual(items2, [])

    def test_parse_json_fence(self):
        out = qqextract.parse_llm_json('```json\n{"items": [{"point": "a"}]}\n```')
        self.assertEqual(out["items"][0]["point"], "a")
        with self.assertRaises(ValueError):
            qqextract.parse_llm_json("no json here")

    def test_extract_and_store(self):
        items = [
            {"group_id": "1", "text": "实测 ollama 支持 qwen2.5 的 reasoning 需要开 --reasoning 参数" * 2},
        ]
        llm = FakeLLM(json.dumps({
            "items": [
                {"point": "ollama 跑 qwen2.5 需要 --reasoning 参数", "quote": "实测 ollama", "cat": "tech"},
                {"point": "太短", "quote": "x", "cat": "tech"},
            ]
        }, ensure_ascii=False))
        refined = asyncio.run(qqextract.extract(items, llm))
        self.assertEqual(len(refined), 1)
        n = qqextract.store_items(refined, group_id="1", ts=123, db_path=self.db)
        self.assertEqual(n, 1)
        import sqlite3
        con = sqlite3.connect(str(self.db))
        rows = con.execute("SELECT type, summary, evidence_ref FROM l2_items").fetchall()
        con.close()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], "knowledge")
        self.assertIn("[QQtech]", rows[0][1])
        self.assertIn("qq:g1:t123", rows[0][2])

    def test_digest(self):
        llm = FakeLLM(json.dumps({"items": [{"point": "知识摘要要点A的内容详细说明", "quote": "q", "cat": "tech"}]}, ensure_ascii=False))
        refined = asyncio.run(qqextract.extract([{"group_id": "1", "text": "x" * 100}], llm))
        qqextract.store_items(refined, group_id="1", ts=int(__import__("time").time()), db_path=self.db)
        import sqlite3
        con = sqlite3.connect(str(self.db))
        con.execute("UPDATE l2_items SET created_at=? WHERE type='knowledge'",
                    (int(__import__("time").time()),))
        con.commit()
        con.close()
        f = qqextract.digest(__import__("time").strftime("%Y-%m-%d"), db_path=self.db)
        content = Path(f).read_text(encoding="utf-8")
        self.assertIn("要点A", content)
        self.assertIn("# QQ 知识汇编", content)


if __name__ == "__main__":
    unittest.main()
