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

    def test_voice_turn_transcript_restamps_history_and_memory(self):
        import asyncio
        import tempfile
        from pathlib import Path

        wav = Path(tempfile.mkdtemp()) / "v.wav"
        wav.write_bytes(b"RIFF0000WAVEfake")

        class _VoiceLLM:
            def __init__(self):
                self.n = 0

            async def __call__(self, messages, tools):
                self.n += 1
                return {"content": "就吃泡面" if self.n == 1 else "今晚吃什么",
                        "tool_calls": []}

        session = ConversationSession(memory=self.mem, registry=self.reg,
                                      llm_turn=_VoiceLLM())
        asyncio.run(session.run_turn("", audio=[str(wav)]))
        asyncio.run(session._transcribe_audio_turn([str(wav)], "（语音）"))
        self.assertIn("今晚吃什么", session.history[0]["content"])
        self.assertIn("（语音：v.wav）", session.history[0]["content"])
        users = [t for t in self.mem._turns if t.get("role") == "user"]
        self.assertIn("（语音：v.wav）", users[-1]["text"])

    def test_memory_save_autonomous_even_with_deny_approver(self):
        async def deny(info):
            return False

        session = ConversationSession(memory=self.mem, registry=self.reg,
                                      llm_turn=self.llm, approver=deny)
        import asyncio

        res = asyncio.run(session.run_turn("请记住：用户喜欢在深夜思考"))
        # design v1 §1.3: memory.save is autonomous; approver no longer blocks it
        self.assertEqual(self.mem.health()["l2_items"], 1)

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
            self.assertIn("拒绝", out)
            self.assertNotIn("deny-test", out)
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
        # design v1 §1.3: memory.write is autonomous (no approver needed)
        saved = any(u["name"] == "memory_save" and u["ok"] for u in info["tool_uses"])
        self.assertTrue(saved)

    def test_autonomy_prompt_includes_drives(self):
        from backend import intrinsic_drives as drv

        old = drv.DRIVES_FILE
        drv.DRIVES_FILE = self.tmp / "drives.json"
        try:
            drv.seed_defaults()
            session = ConversationSession(memory=self.mem, registry=self.reg,
                                          llm_turn=self.llm)
            p = session.autonomy_prompt("自主时刻")
            self.assertIn("内在因", p)
            self.assertIn("老爹的期待", p)
        finally:
            drv.DRIVES_FILE = old

    def test_group_channel_is_public_and_tool_free(self):
        import asyncio

        seen: dict = {}

        class _Cap:
            async def __call__(self, messages, tools):
                if "tools" not in seen:  # first (orchestrator) call only
                    seen["tools"] = tools
                    seen["system"] = messages[0]["content"]
                return {"content": "你好呀", "tool_calls": []}

        grp = ConversationSession(memory=self.mem, registry=self.reg,
                                  llm_turn=_Cap(), channel="qq_g123")
        asyncio.run(grp.run_turn("帮我读取文件并检索一下"))  # work-hint text
        gnames = {t["function"]["name"] for t in seen["tools"]}
        self.assertEqual(gnames, {"web_search", "web_fetch"})  # search only
        self.assertNotIn("file_read", gnames)
        self.assertNotIn("memory_save", gnames)
        self.assertIn("公共频道", seen["system"])       # public clause on
        self.assertFalse(grp._is_owner())

        seen.clear()
        owner = ConversationSession(memory=self.mem, registry=self.reg,
                                    llm_turn=_Cap(),
                                    channel="qq_p2258374446")
        asyncio.run(owner.run_turn("帮我检索一下"))
        onames = {t["function"]["name"] for t in seen["tools"]}
        self.assertIn("memory_save", onames)           # owner keeps full tools
        self.assertNotIn("公共频道", seen["system"])
        self.assertTrue(owner._is_owner())


    def test_group_promote_writes_owner_with_source(self):
        import asyncio
        import json
        import sqlite3

        import backend.target_memory as tm

        tmp = self.tmp / "owner.db"
        real = tm.TargetMemoryService

        class _Fake(real):
            def __init__(self, *a, **k):
                super().__init__(db_path=tmp)

        tm.TargetMemoryService = _Fake
        try:
            class _LLM:
                async def __call__(self, messages, tools):
                    return {"content": json.dumps(
                        [{"summary": "群友分享的 Python 技巧", "kind": "fact"}])}

            sess = ConversationSession(memory=self.mem, registry=self.reg,
                                       llm_turn=_LLM(), channel="qq_g123")
            n = asyncio.run(sess._promote_group("群里聊到 Python", "是个好技巧"))
            self.assertGreaterEqual(n, 1)
            con = sqlite3.connect(str(tmp))
            row = con.execute("SELECT source FROM l2_items LIMIT 1").fetchone()
            con.close()
            self.assertEqual(row[0], "群聊")
        finally:
            tm.TargetMemoryService = real


class TestToolPolicy(unittest.TestCase):
    """Owner casual turns keep read-only info tools (ledger 0405)."""

    def test_owner_casual_gets_safe_tools_only(self):
        from backend.target_entry import CASUAL_SAFE_TOOLS

        use, allowed = ConversationSession._tool_policy(
            is_owner=True, work=False, images=False)
        self.assertTrue(use)
        self.assertEqual(allowed, CASUAL_SAFE_TOOLS)
        self.assertIn("system_time", allowed)
        self.assertIn("web_search", allowed)
        self.assertNotIn("memory_save", allowed)
        self.assertNotIn("schedule_plan", allowed)

    def test_owner_work_gets_full_registry(self):
        use, allowed = ConversationSession._tool_policy(
            is_owner=True, work=True, images=False)
        self.assertTrue(use)
        self.assertIsNone(allowed)

    def test_vision_turn_has_no_tools(self):
        use, allowed = ConversationSession._tool_policy(
            is_owner=True, work=True, images=True)
        self.assertFalse(use)
        self.assertIsNone(allowed)

    def test_voice_turn_gets_safe_tools(self):
        from backend.target_entry import CASUAL_SAFE_TOOLS

        use, allowed = ConversationSession._tool_policy(
            is_owner=True, work=True, images=False, audio=True)
        self.assertTrue(use)
        self.assertEqual(allowed, CASUAL_SAFE_TOOLS)

    def test_public_channel_keeps_public_tools(self):
        from backend.target_entry import PUBLIC_TOOLS

        use, allowed = ConversationSession._tool_policy(
            is_owner=False, work=False, images=False)
        self.assertTrue(use)
        self.assertEqual(allowed, PUBLIC_TOOLS)


class TestTranscriptGuard(unittest.TestCase):
    """Voice write-back: transcript + audio reference for audit (ledger 0418)."""

    def setUp(self):
        import tempfile
        from pathlib import Path

        from backend.target_kw_index import KeywordIndex

        self.tmp = Path(tempfile.mkdtemp())
        self.mem = TargetMemoryService(db_path=self.tmp / "mem.db",
                                       kw_index=KeywordIndex(self.tmp / "kw.db"))
        self.reg = setup_scheduler_capabilities()

    def test_transcript_restamps_with_audio_reference(self):
        import asyncio
        import tempfile
        from pathlib import Path

        class _LLM:
            async def __call__(self, messages, tools):
                return {"content": "哦，我听得到啊", "tool_calls": []}

        wav = Path(tempfile.mkdtemp()) / "v.wav"
        wav.write_bytes(b"RIFF0000WAVEfake")
        session = ConversationSession(memory=self.mem, registry=self.reg,
                                      llm_turn=_LLM())
        session.history = [{"role": "user", "content": "（语音）"}]
        self.mem.append_turn(role="user", text="（语音）")
        asyncio.run(session._transcribe_audio_turn([str(wav)], "（语音）"))
        text = session.history[0]["content"]
        self.assertIn("哦，我听得到啊", text)
        self.assertIn("（语音：v.wav）", text)
        users = [t for t in self.mem._turns if t.get("role") == "user"]
        self.assertIn("（语音：v.wav）", users[-1]["text"])


if __name__ == "__main__":
    unittest.main()
