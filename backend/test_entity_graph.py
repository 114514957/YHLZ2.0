"""Tests for the light entity/relation graph (ledger 0243)."""
import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from backend import entity_graph as eg


class EntityGraphTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self._db = eg.DB_PATH
        eg.DB_PATH = self.tmp / "eg.db"

    def tearDown(self):
        eg.DB_PATH = self._db

    def test_extract_and_upsert_and_related(self):
        async def fake_llm(messages, tools):
            return {"content": json.dumps([
                {"subject": "老爹", "subject_type": "人物",
                 "relation": "是创造者", "object": "元亨", "object_type": "人物"},
                {"subject": "元亨", "subject_type": "人物",
                 "relation": "喜欢", "object": "猫", "object_type": "事物"},
            ])}

        triples = asyncio.run(eg.extract_triples("老爹创造了我，我喜欢猫", fake_llm))
        self.assertEqual(len(triples), 2)
        n = eg.upsert(triples)
        self.assertEqual(n, 2)
        rels = eg.related("元亨")
        self.assertTrue(any("创造者" in r for r in rels))
        self.assertTrue(any("喜欢 猫" in r for r in rels))

    def test_hits_accumulate_on_duplicate(self):
        t = [{"subject": "元亨", "subject_type": "人物",
              "relation": "喜欢", "object": "猫", "object_type": "事物"}]
        eg.upsert(t)
        eg.upsert(t)
        import sqlite3
        con = sqlite3.connect(str(eg.DB_PATH))
        hits = con.execute("SELECT hits FROM relations").fetchone()[0]
        con.close()
        self.assertEqual(hits, 2)

    def test_context_for_matches_entity(self):
        eg.upsert([{"subject": "老爹", "subject_type": "人物",
                    "relation": "是创造者", "object": "元亨", "object_type": "人物"}])
        ctx = eg.context_for("老爹今天在忙什么？")
        self.assertIn("老爹", ctx)
        self.assertIn("创造者", ctx)
        self.assertEqual(eg.context_for("今天天气不错"), "")


if __name__ == "__main__":
    unittest.main()
