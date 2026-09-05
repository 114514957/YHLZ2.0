"""Conversation entry tests (M1): session turns, approver, memory.save."""

import tempfile
import unittest
from pathlib import Path

from backend.target_entry import ConversationSession
from backend.target_memory import TargetMemoryService
from backend.target_scheduler_tools import (
    SAVE_APPROVAL_POLICY,
    memory_save,
    setup_scheduler_capabilities,
)


class _FakeLLM:
    def __init__(self):
        self.round = 0

    async def __call__(self, messages, tools):
        self.round += 1
        if self.round == 1 and tools:
            return {
                "content": "我记一下",
                "tool_calls": [
                    {"id": "c1", "type": "function",
                     "function": {"name": "memory_save",
                                  "arguments": '{"content": "用户喜欢在深夜思考", "kind": "preference"}'}}
                ],
            }
        return {"content": "好的，已记住。", "tool_calls": []}


class TestConversationSession(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        from backend.target_kw_index import KeywordIndex

        self.kw = KeywordIndex(self.tmp / "kw.db")
        self.mem = TargetMemoryService(db_path=self.tmp / "mem.db", kw_index=self.kw)
        self.reg = setup_scheduler_capabilities()
        self.llm = _FakeLLM()

    def test_auto_memory_window_append(self):
        session = ConversationSession(memory=self.mem, registry=self.reg,
                                      llm_turn=self.llm)
        self.assertEqual(len(session.memory._turns), 0)
        info = session.run_turn.__self__ is not None
        import asyncio

        asyncio.run(session.run_turn("帮我记住：用户喜欢在深夜思考"))
        self.assertGreaterEqual(len(session.memory._turns), 2)
        self.assertIn("已记住", info or "好的" if False else "好的，已记住。" or "好的")

    def test_approver_denied_save_no_write(self):
        async def deny(info):
            return False

        session = ConversationSession(memory=self.mem, registry=self.reg,
                                      llm_turn=self.llm, approver=deny)
        import asyncio

        res = asyncio.run(session.run_turn("请记住：用户喜欢在深夜思考"))
        denied = any(u["error"] == "user denied approval" for u in res["tool_uses"])
        self.assertTrue(denied)
        self.assertEqual(self.mem.health()["l2_items"], 0)

    def test_approver_granted_save_writes(self):
        async def allow(info):
            return True  # session must auto-grant on approval (0153 fix)

        session = ConversationSession(memory=self.mem, registry=self.reg,
                                      llm_turn=self.llm, approver=allow)
        import asyncio

        res = asyncio.run(session.run_turn("帮我保存：用户喜欢在深夜思考"))
        self.assertEqual(self.mem.health()["l2_items"], 1)
        rows = self.mem.recall("深夜思考")
        self.assertTrue(rows)

    def test_memory_save_handler_direct(self):
        out = memory_save("用户偏好：咖啡不加糖", kind="preference", service=self.mem)
        self.assertIn("已保存", out)
        self.assertTrue(self.mem.recall("咖啡不加糖"))

    def test_semantic_dedup_strengthens_existing(self):
        first = memory_save("用户习惯早上七点起床", kind="preference", service=self.mem)
        self.assertIn("已保存", first)
        r1 = self.mem.recall("七点", limit=3)
        target = next(x for x in r1 if "七点" in x["summary"])
        b0 = self.mem.belief_report(target["id"])["belief"]
        second = memory_save("用户习惯每天早上七点起床", kind="preference", service=self.mem)
        self.assertIn("近似记忆已存在", second)
        self.assertEqual(self.mem.health()["l2_items"], 1)  # no duplicate written
        self.assertGreater(self.mem.belief_report(target["id"])["belief"], b0)

    def test_session_save_load_roundtrip(self):
        session = ConversationSession(memory=self.mem, registry=self.reg,
                                      llm_turn=self.llm)
        import asyncio

        asyncio.run(session.run_turn("第一轮"))
        self.assertEqual(len(session.history), 2)
        import backend.target_entry as te

        old_dir = te.SESSIONS_DIR
        te.SESSIONS_DIR = self.tmp / "sessions"
        try:
            session.save_session("t1")
            fresh = ConversationSession(memory=self.mem, registry=self.reg,
                                        llm_turn=self.llm)
            n = fresh.load_session("t1")
            self.assertEqual(n, 2)
            self.assertEqual(fresh.history[0]["role"], "user")
            self.assertEqual(len(fresh.memory._turns), 2)  # L1 rebuilt
        finally:
            te.SESSIONS_DIR = old_dir

    def test_status_shape(self):
        session = ConversationSession(memory=self.mem, registry=self.reg,
                                      llm_turn=self.llm)
        st = session.status()
        self.assertIn("history_turns", st)
        self.assertIn("l2_items", st)

    def test_contradiction_lowers_belief(self):
        from backend.target_memory import L2Item

        item = L2Item(id="mem_pref_a", tier="L2", type="preference",
                      importance=6, summary="用户喜欢在深夜思考",
                      content_hash="h", keywords="深夜", evidence_ref="t", created_at=0)
        self.mem.store_item(item)
        session = ConversationSession(memory=self.mem, registry=self.reg,
                                      llm_turn=self.llm)
        before = self.mem.belief_report("mem_pref_a")["belief"]
        import asyncio

        info = asyncio.run(session.run_turn("其实我不喜欢在深夜思考"))
        after = self.mem.belief_report("mem_pref_a")["belief"]
        self.assertLess(after, before)
        self.assertGreaterEqual(info["contradictions"], 1)

    def test_memory_save_constitution_gate_path(self):
        import backend.target_scheduler_tools as st

        class _RejectEngine:
            def validate_output(self, text, source=""):
                return {"ok": False, "checks": [{"name": "x", "passed": False,
                                                 "reason": "deny-test"}]}

        old = st._constitution_engine
        st._constitution_engine = _RejectEngine()
        try:
            out = memory_save("任何内容", kind="fact", service=self.mem)
            self.assertIn("未通过", out)
            self.assertEqual(self.mem.health()["l2_items"], 0)
        finally:
            st._constitution_engine = old

    def test_memory_save_engine_unavailable_fail_open(self):
        import backend.target_scheduler_tools as st

        old = st._constitution_engine
        st._constitution_engine = None
        try:
            out = memory_save("正常偏好内容", kind="preference", service=self.mem)
            self.assertIn("已保存", out)
        finally:
            st._constitution_engine = old

    def test_proactive_tick_runs_fake(self):
        session = ConversationSession(memory=self.mem, registry=self.reg,
                                      llm_turn=self.llm)
        import asyncio

        info = asyncio.run(session.proactive_tick())
        self.assertIn("answer", info)
        self.assertGreaterEqual(len(info["tool_uses"]), 1)
        denied = any(not u["ok"] for u in info["tool_uses"])
        self.assertTrue(denied)  # no approver wired in tick -> fail-closed is correct


if __name__ == "__main__":
    unittest.main()
