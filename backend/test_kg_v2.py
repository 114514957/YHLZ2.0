"""记忆图谱 v2 单测：证据校验、噪音过滤、幂等、1-hop 提示、回滚开关。"""
import json
import os
import tempfile
import unittest
from pathlib import Path

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

    async def test_rollback_switch(self):
        os.environ["YHLZ_KG_V2"] = "0"
        try:
            self.assertFalse(memory_kg.v2_enabled())
        finally:
            os.environ.pop("YHLZ_KG_V2", None)
        self.assertTrue(memory_kg.v2_enabled())


if __name__ == "__main__":
    unittest.main()
