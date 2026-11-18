"""记忆图谱 v2 单测：证据校验、噪音过滤、幂等、1-hop 提示、回滚开关。"""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from backend import kg_v2, memory_kg


def _fake_llm(triples):
    async def llm(messages, tools):
        return {"content": json.dumps(triples, ensure_ascii=False)}

    return llm


TEXT = "老爹创建了元亨。元亨喜欢喝可乐。今天跑了工具。"


class KgV2Tests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["YHLZ_KG_DB"] = str(Path(self.tmp.name) / "kg.db")
        kg_v2._last_ingest = 0.0
        self.triples = [
            {"subject": "老爹", "relation": "创建", "object": "元亨",
             "evidence": "老爹创建了元亨", "confidence": 0.95},
            {"subject": "元亨", "relation": "喜欢", "object": "可乐",
             "evidence": "元亨喜欢喝可乐", "confidence": 0.8},
            # 代词实体
            {"subject": "你", "relation": "喜欢", "object": "可乐",
             "evidence": "元亨喜欢喝可乐", "confidence": 0.9},
            # 证据不在原文（编造）
            {"subject": "利贞", "relation": "是", "object": "助手",
             "evidence": "这句话不在原文里", "confidence": 0.9},
            # 过程噪音
            {"subject": "计划表", "relation": "到点", "object": "09:30+daily",
             "evidence": "今天跑了工具", "confidence": 0.9},
            # 置信度太低
            {"subject": "元亨", "relation": "讨厌", "object": "下雨",
             "evidence": "元亨喜欢喝可乐", "confidence": 0.1},
        ]

    def tearDown(self):
        os.environ.pop("YHLZ_KG_DB", None)
        self.tmp.cleanup()

    async def test_extract_filters_noise_and_requires_evidence(self):
        got = await kg_v2.extract_triples(TEXT, llm_turn=_fake_llm(self.triples))
        pairs = {(t["subject"], t["relation"], t["object"]) for t in got}
        self.assertIn(("老爹", "创建", "元亨"), pairs)
        self.assertIn(("元亨", "喜欢", "可乐"), pairs)
        self.assertNotIn(("你", "喜欢", "可乐"), pairs)
        self.assertNotIn(("利贞", "是", "助手"), pairs)
        self.assertNotIn(("元亨", "讨厌", "下雨"), pairs)
        self.assertEqual(len(got), 2)

    async def test_upsert_idempotent_and_hits(self):
        got = await kg_v2.extract_triples(TEXT, llm_turn=_fake_llm(self.triples))
        self.assertEqual(kg_v2.upsert(got, TEXT, source="test"), 2)
        self.assertEqual(kg_v2.upsert(got, TEXT, source="test"), 2)
        st = kg_v2.stats()
        self.assertEqual(st["docs"], 1)
        self.assertEqual(st["relations"], 2)
        self.assertEqual(st["entities"], 3)

    async def test_context_for_returns_known_facts(self):
        got = await kg_v2.extract_triples(TEXT, llm_turn=_fake_llm(self.triples))
        kg_v2.upsert(got, TEXT, source="test")
        block = kg_v2.context_for("元亨最近怎么样")
        self.assertIn("元亨", block)
        self.assertIn("喜欢 可乐", block)
        self.assertEqual(kg_v2.context_for("今天天气不错"), "")

    async def test_semantic_docs_dual_recall(self):
        with kg_v2._conn() as con:
            con.execute("INSERT INTO docs(hash,text,source,ts) VALUES(?,?,?,?)",
                        ("h1", "苹果很甜，老爹喜欢", "test", 1.0))
            con.execute("INSERT INTO docs(hash,text,source,ts) VALUES(?,?,?,?)",
                        ("h2", "香蕉是黄色的", "test", 1.0))

        def fake_embed(texts):
            return np.array([[1.0, 0.0] if "苹果" in t else [0.0, 1.0]
                             for t in texts], dtype=np.float32)

        with patch("backend.vector_memory.semantic_ready", return_value=True), \
                patch("backend.vector_memory.embed_cls", side_effect=fake_embed):
            hits = kg_v2.semantic_docs("苹果", top=2)
            got = kg_v2.retrieve("苹果")
        self.assertEqual(hits[0]["text"][:4], "苹果很甜")
        self.assertTrue(got["docs"])
        self.assertEqual(kg_v2.stats()["docs_with_emb"], 2)

    async def test_episodes_and_profile(self):
        t1 = [{"subject": "元亨", "relation": "喜欢", "object": "可乐",
               "evidence": "元亨喜欢可乐", "confidence": 0.9}]
        t2 = [{"subject": "元亨", "relation": "负责", "object": "写代码",
               "evidence": "元亨负责写代码", "confidence": 0.9}]
        kg_v2.upsert(t1, "元亨喜欢可乐", source="chat", ts=1000)
        kg_v2.upsert(t2, "元亨负责写代码", source="chat", ts=1000 + 7 * 3600)
        self.assertEqual(kg_v2.rebuild_episodes(gap_hours=6), 2)
        prof = kg_v2.profile("元亨")
        rels = {(f["rel"], f["dst"]) for f in prof["facts"]}
        self.assertIn(("喜欢", "可乐"), rels)
        self.assertIn(("负责", "写代码"), rels)

    async def test_temporal_supersede(self):
        kg_v2.upsert([{"subject": "老爹", "relation": "住在", "object": "杭州",
                       "evidence": "老爹住在杭州", "confidence": 0.9}],
                     "老爹住在杭州", source="test", ts=1000)
        kg_v2.upsert([{"subject": "老爹", "relation": "住在", "object": "上海",
                       "evidence": "老爹搬到上海了", "confidence": 0.9}],
                     "老爹搬到上海了", source="test", ts=2000)
        block = kg_v2.context_for("老爹住哪")
        self.assertIn("上海", block)
        self.assertNotIn("杭州", block)
        with kg_v2._conn() as con:
            old = con.execute(
                "SELECT status,valid_to FROM relations r JOIN entities d ON d.id=r.dst "
                "WHERE d.name='杭州'").fetchone()
            cur = con.execute(
                "SELECT status FROM relations r JOIN entities d ON d.id=r.dst "
                "WHERE d.name='上海'").fetchone()
        self.assertEqual(old[0], "superseded")
        self.assertIsNotNone(old[1])
        self.assertEqual(cur[0], "active")

    async def test_decay_restore_and_protect(self):
        kg_v2.upsert([{"subject": "元亨", "relation": "喜欢", "object": "旧玩具",
                       "evidence": "元亨喜欢旧玩具", "confidence": 0.5}],
                     "元亨喜欢旧玩具", source="test", ts=1000)
        with kg_v2._conn() as con:
            rid = con.execute("SELECT id FROM relations").fetchone()[0]
        self.assertEqual(kg_v2.decay(max_age_days=1), 1)
        self.assertEqual(kg_v2.context_for("元亨"), "")
        self.assertTrue(kg_v2.restore(rid))
        self.assertIn("旧玩具", kg_v2.context_for("元亨"))
        self.assertTrue(kg_v2.protect(rid))
        self.assertEqual(kg_v2.forget(rid), True)
        self.assertEqual(kg_v2.maintenance()["by_status"].get("archived"), 1)

    async def test_rollback_switch(self):
        os.environ["YHLZ_KG_V2"] = "0"
        try:
            self.assertFalse(memory_kg.v2_enabled())
        finally:
            os.environ.pop("YHLZ_KG_V2", None)
        self.assertTrue(memory_kg.v2_enabled())


if __name__ == "__main__":
    unittest.main()
