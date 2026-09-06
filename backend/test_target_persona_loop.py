"""Persona consolidation loop tests (0165): close-the-loop reliability."""

import tempfile
import unittest
from pathlib import Path

from backend.target_memory import L2Item, TargetMemoryService
from backend.target_persona_loop import (
    PersonaConsolidationLoop,
    _PERSONA_PREFIX,
)


def _seed(mem: TargetMemoryService, n: int = 3, prefix: str = "") -> list[str]:
    ids = []
    for i in range(n):
        iid = f"mem_seed{i}_{prefix or 'a'}"
        mem.store_item(L2Item(
            id=iid, tier="L2", type="preference", importance=7,
            summary=f"用户偏好条目{i}: 元亨喜欢在深夜思考（种子）",
            content_hash="h", keywords=f"条目{i}",
            evidence_ref="test", created_at=0,
        ))
        mem.observe_hit(iid, 0.6)
        ids.append(iid)
    return ids


class _FakeLLM:
    DEFAULT_CLAIMS = [{"claim": "元亨应保持好奇与求索", "kind": "new", "tier": "core", "item_ids": []}]
    DEFAULT_DECISIONS = [{"claim": "元亨应保持好奇与求索", "kind": "new", "tier": "core",
                          "item_ids": ["mem_seed0_a"]}]

    def __init__(self, claims=None, decisions=None):
        self.claims = self.DEFAULT_CLAIMS if claims is None else claims
        self.decisions = self.DEFAULT_DECISIONS if decisions is None else decisions

    async def __call__(self, messages, tools):
        last = str(messages[-1]["content"] if messages else "")
        if "候选根基主张" in last:
            import json
            return {"content": json.dumps(self.decisions, ensure_ascii=False),
                    "tool_calls": []}
        import json
        return {"content": json.dumps(self.claims, ensure_ascii=False),
                "tool_calls": []}


class TestConsolidation(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.cog = self.tmp / "foundation.md"
        self.cog.write_text("## 版本\n- v1 (seed)\n", encoding="utf-8")
        from backend.target_kw_index import KeywordIndex
        import backend.target_persona_loop as pl

        self._pl = pl
        self._pending_orig = pl.PENDING_FILE
        pl.PENDING_FILE = self.tmp / "cognition_pending.json"  # isolate queue
        self.kw = KeywordIndex(self.tmp / "kw.db")
        self.mem = TargetMemoryService(db_path=self.tmp / "mem.db", kw_index=self.kw)

    def tearDown(self):
        self._pl.PENDING_FILE = self._pending_orig

    def _loop(self, llm, approver=None):
        return PersonaConsolidationLoop(llm, self.mem, cognition_file=self.cog,
                                        approver=approver)

    def test_apply_appends_version_and_stamps(self):
        import asyncio
        ids = _seed(self.mem)
        loop = self._loop(_FakeLLM(), approver=lambda c, k, t: True)
        r = asyncio.run(loop.consolidate_once())
        self.assertEqual(r["status"], "ok")
        self.assertGreaterEqual(r["version"], 2)
        text = self.cog.read_text(encoding="utf-8")
        self.assertIn("元亨自沉淀 v2", text)
        self.assertIn("保持好奇", text)
        # stamped so it is not re-proposed
        rows = self.mem._unconsolidated_items() if hasattr(self.mem, "_unconsolidated_items") else []
        stamped = self.mem.belief_report("mem_seed0_a")
        self.assertEqual(stamped["status"], "active")  # never deleted
        import sqlite3
        con = sqlite3.connect(str(self.mem.db_path))
        ev = con.execute("SELECT evidence_ref FROM l2_items WHERE id='mem_seed0_a'").fetchone()[0]
        con.close()
        self.assertTrue(ev.startswith(_PERSONA_PREFIX))

    def test_nothing_to_consolidate_when_all_stamped(self):
        import asyncio
        ids = _seed(self.mem)
        llm = _FakeLLM(decisions=[
            {"claim": f"条目{i} 值得沉淀", "kind": "new", "tier": "method", "item_ids": [i]}
            for i in ids
        ])
        asyncio.run(self._loop(llm, approver=lambda c, k, t: True).consolidate_once())
        # all stamped now -> second run idles
        r2 = asyncio.run(self._loop(_FakeLLM()).consolidate_once())
        self.assertEqual(r2["status"], "idle")

    def test_no_claims_when_llm_empty(self):
        import asyncio
        _seed(self.mem)
        llm = _FakeLLM(claims=[])
        r = asyncio.run(self._loop(llm).consolidate_once())
        self.assertEqual(r["status"], "no-claims")

    def test_refute_records_in_section(self):
        import asyncio
        _seed(self.mem)
        llm = _FakeLLM(
            claims=[{"claim": "旧观点已证伪", "kind": "refute", "tier": "core", "item_ids": []}],
            decisions=[{"claim": "旧观点已证伪", "kind": "refute", "tier": "core",
                        "item_ids": ["mem_seed0_a"]}],
        )
        r = asyncio.run(self._loop(llm, approver=lambda c, k, t: True).consolidate_once())
        self.assertEqual(r["status"], "ok")
        self.assertIn("证伪修订", self.cog.read_text(encoding="utf-8"))

    def test_pending_when_no_approver(self):
        """A1 (ledger 0187): without an owner approver, core/method claims are
        parked in the pending queue — never auto-written to the foundation."""
        import asyncio
        import json

        import backend.target_persona_loop as pl

        _seed(self.mem)
        r = asyncio.run(self._loop(_FakeLLM()).consolidate_once())
        self.assertEqual(r["status"], "pending-approval")
        self.assertTrue(pl.PENDING_FILE.exists())
        pending = json.loads(pl.PENDING_FILE.read_text(encoding="utf-8"))
        self.assertTrue(any("保持好奇" in p["claim"] for p in pending))
        # foundation untouched
        self.assertNotIn("元亨自沉淀", self.cog.read_text(encoding="utf-8"))

    def test_declined_not_written(self):
        import asyncio
        _seed(self.mem)
        loop = self._loop(_FakeLLM(), approver=lambda c, k, t: False)
        r = asyncio.run(loop.consolidate_once())
        self.assertEqual(r["status"], "no-approved")
        self.assertNotIn("元亨自沉淀", self.cog.read_text(encoding="utf-8"))

    def test_meta_tier_never_auto_written(self):
        import asyncio
        _seed(self.mem)
        llm = _FakeLLM(
            decisions=[{"claim": "待证伪的想法", "kind": "new", "tier": "meta",
                        "item_ids": ["mem_seed0_a"]}],
        )
        r = asyncio.run(self._loop(llm, approver=lambda c, k, t: True).consolidate_once())
        self.assertEqual(r["status"], "no-approved")
        self.assertNotIn("待证伪", self.cog.read_text(encoding="utf-8"))

    def test_a3_refute_proposal_matches_and_files(self):
        """A3 (ledger 0193): correction statement that matches a foundation
        claim files a refute proposal; never edits the foundation directly."""
        import json
        import backend.target_persona_loop as pl

        self.cog.write_text("# 认知根基\n\n## 版本\n- [新增|core] 元亨珍视深夜思考\n",
                            encoding="utf-8")
        msg = pl.maybe_open_refute_proposal(
            self.cog.read_text(encoding="utf-8"),
            "我之前说错了：深夜思考其实不是最重要的",
            pending_file=pl.PENDING_FILE)
        self.assertIn("证伪提案", msg)
        self.assertNotIn("证伪修订", self.cog.read_text(encoding="utf-8"))
        pend = json.loads(pl.PENDING_FILE.read_text(encoding="utf-8"))
        self.assertTrue(any(e.get("refutes_foundation", "").startswith("元亨珍视深夜")
                            for e in pend))

    def test_a3_no_match_does_nothing(self):
        import backend.target_persona_loop as pl

        self.cog.write_text("# 认知根基\n\n- [新增|core] 元亨珍视深夜思考\n",
                            encoding="utf-8")
        msg = pl.maybe_open_refute_proposal(
            self.cog.read_text(encoding="utf-8"),
            "我今天心情不错，想聊聊天", pending_file=pl.PENDING_FILE)
        self.assertEqual(msg, "")


if __name__ == "__main__":
    unittest.main()
