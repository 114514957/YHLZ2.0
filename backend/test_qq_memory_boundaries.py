"""Offline QQ bridge and persona privacy contracts. No live messages."""
import asyncio
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from tools import qq_bot as qq
from backend.target_entry import ConversationSession
from backend.target_memory import TargetMemoryService
from backend.target_prompts import render_system_prompt, MEMORY_BOUNDARY_CLAUSE


class QQBridgeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        for name, value in [("dev_runner", None), ("_load_state", lambda: {})]:
            p = patch.object(qq, name, value)
            p.start()
            self.addCleanup(p.stop)
        self.bridge = qq.QQBridge("unused", "900", Path("unused"), masters={"100"})
        self.bridge.log = Mock()

        async def _ws_send(raw):
            # Phase 2: ordinary replies now await the OneBot ack; the fake
            # socket returns the echo so the send resolves immediately.
            import json as _json

            msg = _json.loads(raw)
            fut = self.bridge._pending.get(msg.get("echo"))
            if fut is not None and not fut.done():
                fut.set_result({"status": "ok", "retcode": 0})

        self.ws = Mock(send=AsyncMock(side_effect=_ws_send))
        self.turn = patch.object(qq, "_daemon_turn", return_value="收到")
        self.call = self.turn.start()
        self.addCleanup(self.turn.stop)

    def event(self, mid=1, group=None, sender="100", text="你好"):
        msg = [{"type": "text", "data": {"text": text}}]
        if group is not None:
            msg.append({"type": "at", "data": {"qq": "900"}})
        return {"post_type": "message", "message_type": "group" if group else "private",
                "user_id": sender, "group_id": group, "message_id": mid, "message": msg}

    async def test_replayed_message_is_not_reexecuted(self):
        ev = self.event()
        await self.bridge.handle(self.ws, ev)
        await self.bridge.handle(self.ws, ev)
        self.assertEqual(self.call.call_count, 1)
        self.assertEqual(self.bridge.duplicate_events, 1)

    async def test_no_id_remains_compatible(self):
        for _ in range(2):
            await self.bridge.handle(self.ws, self.event(mid=None))
        self.assertEqual(self.call.call_count, 2)

    async def test_dedup_distinguishes_group_and_sender(self):
        for group, sender in [("1", "100"), ("2", "100"), ("1", "101")]:
            self.assertTrue(self.bridge._claim_message(self.event(group=group, sender=sender), "qq_g"+group))

    async def test_dedup_ttl_and_capacity(self):
        with patch.object(qq, "MESSAGE_DEDUP_LIMIT", 2), patch.object(qq.time, "monotonic", return_value=10):
            for mid in range(3):
                self.assertTrue(self.bridge._claim_message(self.event(mid), "qq_p100"))
            self.assertEqual(len(self.bridge._seen_events), 2)
        with patch.object(qq.time, "monotonic", return_value=10+qq.MESSAGE_DEDUP_TTL):
            self.assertTrue(self.bridge._claim_message(self.event(2), "qq_p100"))

    async def test_request_does_not_block_event_loop(self):
        started, release = threading.Event(), threading.Event()
        threads = []
        def slow(*args, **kwargs):
            threads.append(threading.get_ident())
            started.set()
            release.wait(2)
            return "收到"
        self.call.side_effect = slow
        task = asyncio.create_task(self.bridge.handle(self.ws, self.event()))
        try:
            for _ in range(100):
                if started.is_set():
                    break
                await asyncio.sleep(.005)
            self.assertTrue(started.is_set())
            self.assertFalse(task.done())
            self.assertNotEqual(threads[0], threading.get_ident())
        finally:
            release.set()
            await task

    async def test_empty_masters_private_is_chat_not_command(self):
        self.bridge.masters = set()
        await self.bridge.handle(self.ws, self.event())
        await self.bridge._relay_outbox(self.ws)
        self.call.assert_called_once()          # 2026-10-06: 非主人私聊按聊天处理
        self.ws.send.assert_awaited()           # 普通聊天回复经统一投递发出

    async def test_invalid_events_do_not_reach_daemon(self):
        for ev in [self.event(sender="bad"), self.event(group="../bad"),
                   self.event(sender="999")]:
            await self.bridge.handle(self.ws, ev)
        # only the valid non-owner private message survives as plain chat
        self.assertEqual(self.call.call_count, 1)
        self.assertEqual(self.call.call_args.args[0], "你好")

    async def test_malformed_segments_are_ignored(self):
        ev = self.event()
        ev["message"].extend([None, "bad", {"type": "text", "data": []},
                              {"type": "text", "data": {"text": 123}}])
        await self.bridge.handle(self.ws, ev)
        self.assertEqual(self.call.call_args.args[0], "你好")

    async def test_errors_are_visible_without_secret_or_retry(self):
        self.call.side_effect = RuntimeError("secret credential")
        await self.bridge.handle(self.ws, self.event())
        await self.bridge.handle(self.ws, self.event())
        self.assertEqual(self.call.call_count, 1)
        self.assertEqual(self.bridge.backend_errors, 1)
        self.assertNotIn("secret credential", str(self.bridge.log.call_args_list))
        self.assertNotIn("secret credential", str(self.ws.send.call_args_list))
        self.ws.send.assert_awaited_once()

    async def test_group_speaker_is_attributed(self):
        await self.bridge.handle(self.ws, self.event(group="123"))
        text, channel = self.call.call_args.args[:2]
        self.assertTrue(text.startswith("[QQ群发言者 user_id=100] 你好"))
        self.assertEqual(channel, "qq_g123")

    async def test_group_can_send_non_dangerous_file_but_not_launch_dev(self):
        # 2026-09-30: 群聊「完整发图」——非危险图/文件可发；dev 任务仍仅主人。
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "pic.png"
            f.write_bytes(b"img")
            with patch.object(
                    qq, "_extract_markers",
                    return_value=("收到", [str(f)], [str(f)], [], False,
                                  ["do work"], [], [], [], [])):
                self.bridge._send_image = AsyncMock()
                self.bridge._send_file = AsyncMock()
                self.bridge._start_dev = AsyncMock()
                await self.bridge.handle(self.ws, self.event(group="123"))
                self.bridge._send_image.assert_called_once()
                self.bridge._send_file.assert_called_once()
                self.bridge._start_dev.assert_not_called()

    async def test_transport_failure_is_not_empty_success(self):
        # Use the original function while blocking all actual HTTP.
        self.turn.stop()
        with patch.object(qq.urllib.request, "urlopen", side_effect=TimeoutError):
            with self.assertRaises(RuntimeError):
                qq._daemon_turn("test", "qq_p100")


class PersonaBoundaryTests(unittest.TestCase):
    def test_public_ignores_all_private_inputs(self):
        with patch("backend.target_prompts.load_persona_five_dim", side_effect=AssertionError("private access")):
            text = render_system_prompt(public=True, persona="PRIVATE_PERSONA", five_dim=["PRIVATE_DIM"],
                style_lines=["PRIVATE_STYLE"], tools=[{"function": {"name": "memory_save"}},
                                                     {"function": {"name": "web_search"}}])
        for secret in ["PRIVATE_PERSONA", "PRIVATE_DIM", "PRIVATE_STYLE", "memory_save"]:
            self.assertNotIn(secret, text)
        self.assertIn("web_search", text)
        self.assertIn(MEMORY_BOUNDARY_CLAUSE, text)

    def test_owner_preserves_persona_and_style(self):
        text = render_system_prompt(persona="PRIVATE_PERSONA", five_dim=["PRIVATE_DIM"], style_lines=["PRIVATE_STYLE"])
        for value in ["PRIVATE_PERSONA", "PRIVATE_DIM", "PRIVATE_STYLE"]:
            self.assertIn(value, text)

    def test_public_session_does_not_read_private_draft(self):
        session = ConversationSession.__new__(ConversationSession)
        session.channel = "qq_g123"
        session.memory = Mock(persona_draft=Mock(side_effect=AssertionError("private access")))
        session.registry = Mock(export_openai_tools=lambda: [])
        session.style_inject = True
        session.render_system()
        session.memory.persona_draft.assert_not_called()

    def test_default_channels_share_only_owner_l2_and_have_hooks(self):
        with tempfile.TemporaryDirectory() as tmp, patch("backend.target_memory.DEFAULT_DB", Path(tmp)/"memstore"/"mem.db"), \
             patch("backend.llm_vllm_provider.LlmVllmProvider", return_value=object()), \
             patch("backend.target_entry.setup_scheduler_capabilities", return_value=Mock()), \
             patch("backend.target_entry.bind_memory_save_service"), \
             patch("backend.target_scheduler_tools.bind_memory_recall_service"), \
             patch("backend.memory_carriers.bind_memory_carriers"):
            sessions = [ConversationSession(channel=c, llm_turn=AsyncMock()) for c in ["private", "qq_p2258374446", "qq_g123", "../odd"]]
            a,b,g,odd = sessions
            self.assertEqual(a.memory.db_path, b.memory.db_path)
            self.assertNotEqual(a.memory._l1_path(), b.memory._l1_path())
            self.assertNotEqual(g.memory.db_path, a.memory.db_path)
            self.assertEqual(g.memory.db_path.name, "qq_g123.db")
            self.assertEqual(odd.memory.db_path.parent, Path(tmp)/"qq_groups")
            for session in sessions:
                self.assertIsNotNone(session.memory._extractor)
                self.assertIsNotNone(session.memory._judge)


class ArchiveBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        patcher = patch("backend.target_entry.SESSIONS_DIR", self.root / "sessions")
        patcher.start()
        self.addCleanup(patcher.stop)

    def session(self, channel):
        s = ConversationSession.__new__(ConversationSession)
        s.channel = channel
        s.history_limit = 20
        s.history = [{"role": "user", "content": "synthetic history"}]
        s._session_name = ""
        s.memory = TargetMemoryService(db_path=self.root/(channel+".db"), l1_scope=channel)
        return s

    def test_same_channel_roundtrip(self):
        a = self.session("qq_g1")
        a.save_session("group1")
        b = self.session("qq_g1")
        self.assertEqual(b.load_session("group1"), 1)
        self.assertEqual(a.history, b.history)

    def test_foreign_channel_cannot_load_or_overwrite(self):
        owner = self.session("console")
        path = owner.save_session("console")
        before = path.read_bytes()
        other = self.session("qq_g1")
        for call in [other.load_session, other.save_session]:
            with self.assertRaises(ValueError): call("console")
        self.assertEqual(before, path.read_bytes())
        self.assertEqual(other._session_name, "")

    def test_no_path_traversal_or_windows_device(self):
        s = self.session("console")
        for name in ["../outside", "..", "C:\\outside", "a/b", "a:b", "CON", "aux.txt", "tail."]:
            for call in [s.load_session, s.save_session]:
                with self.assertRaises(ValueError, msg=name): call(name)

    def test_legacy_owner_works_but_public_requires_migration(self):
        import json
        root = self.root/"sessions"; root.mkdir()
        p = root/"legacy.json"
        p.write_text(json.dumps({"history":[{"role":"user","content":"old"}]}), encoding="utf-8")
        self.assertEqual(self.session("console").load_session("legacy"), 1)
        group = self.session("qq_g1")
        for call in [group.load_session, group.save_session]:
            with self.assertRaises(ValueError): call("legacy")

    def test_bounded_archive_preserves_older_summary_after_restart(self):
        import asyncio
        from types import SimpleNamespace
        s = self.session("console")
        s.history = [{"role":"user", "content":str(i)} for i in range(30)]
        for msg in s.history:
            s.memory.append_turn(role=msg["role"],text=msg["content"])
        s.memory.set_llm_hooks(SimpleNamespace(compress=AsyncMock(return_value=("older facts",1))),None)
        asyncio.run(s.memory.process_summary())
        self.assertEqual(s.memory._summary,"older facts")
        s.save_session("long")
        fresh=self.session("console")
        self.assertEqual(fresh.load_session("long"),20)
        self.assertEqual(fresh.memory._summary,"older facts")
        self.assertFalse(fresh.memory._summary_pending)

    def test_bad_history_rejected_without_mutating_session(self):
        import json
        root=self.root/"sessions";root.mkdir()
        (root/"bad.json").write_text(json.dumps({"channel":"console","history":None}),encoding="utf-8")
        s=self.session("console")
        before=list(s.history)
        with self.assertRaises(ValueError): s.load_session("bad")
        self.assertEqual(s.history,before)
        self.assertEqual(s._session_name, "")


if __name__ == "__main__":
    unittest.main()
