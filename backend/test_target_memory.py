"""Unit tests for TargetMemoryService (batch-1 ledger 0116-0120)."""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from backend.llm_reasoner import LLMReasoner
from backend.target_memory import L2Item, TargetMemoryService
from backend.target_memory_llm import MemoryLLMService


class _FakeExtractor:
    """Deterministic cloud-candidate generator hook (no real LLM)."""

    async def compress(self, dropped):
        return f"摘要(len={len(dropped)})", 1

    async def candidates(self, context):
        return [
            {
                "type": "preference",
                "importance": 9,
                "summary": "用户偏好简洁直接",
                "keywords": "偏好,简洁",
                "tier": "L2",
            },
            {
                "type": "event",
                "importance": 3,
                "summary": "一次普通问候",
                "keywords": "问候",
                "tier": "L2",
            },
        ]

    def adjudicate(self, item):
        return {"importance": int(item.get("importance", 3)), "status": "active"}


class MemoryServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        from backend.target_kw_index import KeywordIndex

        self._kw = KeywordIndex(self.tmp / "kw.db")
        self.service = TargetMemoryService(
            db_path=self.tmp / "mem.db", window_turns=3, kw_index=self._kw
        )
        self.service.set_llm_hooks(_FakeExtractor(), _FakeExtractor())

    async def tearDown(self):
        pass

    async def test_l1_window_and_compress(self) -> None:
        for i in range(5):
            self.service.append_turn(role="user", text=f"t{i}")
        with self.service._lock:
            self.assertLessEqual(len(self.service._turns), 3)
        await self.service.process_summary()
        self.assertIn("摘要(len=", self.service.context_block())

    async def test_l2_candidates_adjudicated_tiered(self) -> None:
        items = await self.service.submit_candidates(
            text="t", transcript="你好，元亨", evidence_ref="ledger-0001"
        )
        self.assertEqual(len(items), 2)
        adjudicated = await self.service.adjudicate_async(items)
        statuses = {a.id: a.status for a in adjudicated}
        self.assertIn("active", statuses.values())
        self.assertIn("downgraded", statuses.values())  # importance<=4 -> downgraded

    async def test_mark_statuses_never_delete(self) -> None:
        items = await self.service.submit_candidates(
            text="t", transcript="x", evidence_ref="r"
        )
        await self.service.adjudicate_async(items)
        with self.assertRaises(ValueError):
            self.service.mark(items[0].id, "deleted")
        self.service.mark(items[0].id, "archive")
        self.service.mark(items[0].id, "cold")

    async def test_recall_fts_and_rebuild(self) -> None:
        items = await self.service.submit_candidates(
            text="t", transcript="元亨喜欢简洁回答", evidence_ref="ledger-0001"
        )
        await self.service.adjudicate_async(items)
        hits = self.service.recall("简洁")
        self.assertTrue(any(h["summary"].startswith("用户偏好简洁") for h in hits))
        self.service.rebuild_fts()
        self.assertTrue(self.service.recall("简洁"))

    def test_persona_draft_reads_golden(self) -> None:
        draft = self.service.persona_draft()
        self.assertTrue(draft)
        self.assertIn("思想", draft)  # collab 设计思想节

    def test_health(self) -> None:
        info = self.service.health()
        self.assertEqual(info["provider"], "target-memory-v1")
        self.assertIn("l2_items", info)


class MemoryLLMServiceTests(unittest.IsolatedAsyncioTestCase):
    def test_parse_json_helpers(self) -> None:
        self.assertEqual(MemoryLLMService._parse_json_array('[{"a":1}]'), [{"a": 1}])
        self.assertEqual(MemoryLLMService._parse_json_object('noise {"x":2} end'), {"x": 2})
        self.assertEqual(MemoryLLMService._parse_json_array("no json"), [])


class ReasonerMemoryIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_reasoner_injects_persona_and_window(self) -> None:
        from backend.test_llm_provider_port import OtherProviderStub

        service = TargetMemoryService(db_path=Path(tempfile.mkdtemp()) / "m.db", window_turns=3)
        service.append_turn(role="user", text="早")
        reasoner = LLMReasoner(OtherProviderStub(), memory_service=service)
        chunks = [c async for c in reasoner.generate("元亨，你好", None)]
        self.assertTrue(len(chunks) >= 1)
        self.assertIn("先进始于计算", reasoner.provider.messages[0]["content"])
        self.assertIn("早", reasoner.provider.messages[1]["content"])
        self.assertTrue(any("元亨，你好" == m["content"] for m in reasoner.provider.messages))
        with service._lock:
            self.assertGreaterEqual(len(service._turns), 2)  # user + assistant recorded


if __name__ == "__main__":
    unittest.main()
