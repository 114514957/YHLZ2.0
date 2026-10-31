"""P4 offline tests: group history window/summary, sticker library, degrade.

No network, no vision backend, no torch. Run:
    .venv\\Scripts\\python.exe -m unittest backend.test_qq_bridge_p4
"""
import json
import os
import pathlib
import sys
import tempfile
import unittest
from unittest import mock
from unittest.mock import AsyncMock

from backend.qq_group_store import GroupHistoryStore
from backend.qq_stickers import (
    NullVision, StickerStore, decide_status, validate_result,
)

_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(_ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(_ROOT / "tools"))

RESULT = {
    "decision": "accept", "is_reusable_sticker": True, "confidence": 0.92,
    "description": "小猫躺平", "keywords": ["累了", "躺平", "休息", "摸鱼"],
    "emotion": ["疲惫"], "use_when": ["闲聊"], "avoid_when": ["求助"],
    "contains_private_info": False,
}


class GroupStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.store = GroupHistoryStore(self.tmp / "g.db", bot_uin="900",
                                       turns=50)

    def test_window_is_exact_50_before_current(self):
        for i in range(1, 61):
            self.store.add(group_id="A", message_id=f"m{i}", sender_id="1",
                           text=f"t{i}")
        seq = self.store.add(group_id="A", message_id="m61", sender_id="1",
                             text="cur")
        ids = [m["message_id"] for m in self.store.window("A",
                                                          before_seq=seq)]
        self.assertEqual(ids, [f"m{i}" for i in range(11, 61)])

    def test_cross_group_isolation_and_dedupe(self):
        self.store.add(group_id="A", message_id="a1", sender_id="1", text="a")
        self.store.add(group_id="B", message_id="b1", sender_id="2", text="b")
        dup_seq = self.store.add(group_id="A", message_id="a1", sender_id="1",
                                 text="dup")
        self.assertEqual(dup_seq, 0)
        self.assertEqual(self.store.count("A"), 1)
        self.assertEqual(self.store.count("B"), 1)
        self.assertEqual([m["message_id"] for m in self.store.window("A")],
                         ["a1"])

    def test_summary_facts_carry_source_ids(self):
        for i in range(1, 6):
            self.store.add(group_id="G", message_id=f"x{i}", sender_id="1",
                           text=("在吗？" if i == 2 else f"内容{i}"))
        block = self.store.context_block("G")
        fact_lines = [ln for ln in block["summary"].splitlines()
                      if ln.startswith("[")]
        self.assertTrue(fact_lines)
        for line in [ln for ln in fact_lines if ln.startswith("[x")]:
            self.assertIn("[x", line)
        self.assertIn("[x2]", block["summary"])

    def test_partial_completeness_and_backfill_contract(self):
        self.store.add(group_id="C", message_id="c1", sender_id="1", text="hi")
        block = self.store.context_block("C")
        self.assertTrue(block["completeness"].startswith("partial"))
        self.assertFalse(self.store.backfill_supported())
        merge = self.store.merge_backfill([
            {"group_id": "C", "message_id": "c2", "sender_id": "1", "text": "n"},
            {"group_id": "C", "message_id": "c1", "sender_id": "1", "text": "d"},
        ])
        self.assertEqual(merge["inserted"], 1)

    def test_bot_echo_stored_but_not_a_reply_trigger(self):
        self.store.add(group_id="G", message_id="bot:1", sender_id="900",
                       text="元亨的话", is_bot=True)
        win = self.store.window("G")
        self.assertTrue(win[0]["is_bot"])


class StickerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.store = StickerStore(self.tmp / "s.db",
                                  media_dir=self.tmp / "media")

    def _ingest(self, name: str, payload: bytes, scope="group:1"):
        p = self.tmp / name
        p.write_bytes(payload)
        return self.store.ingest(str(p), source_message_id=name,
                                 source_kind="group", source_id="1",
                                 scope=scope)

    def test_validate_result_strict(self):
        self.assertIsNotNone(validate_result(dict(RESULT)))
        bad = dict(RESULT)
        bad["keywords"] = ["a", "b"]
        self.assertIsNone(validate_result(bad))
        unknown = dict(RESULT)
        unknown["shell"] = "rm -rf /"
        self.assertIsNone(validate_result(unknown))
        self.assertIsNone(validate_result({**RESULT, "confidence": 2}))

    def test_decide_status_thresholds(self):
        self.assertEqual(decide_status(RESULT), "active")
        review = dict(RESULT, confidence=0.70)
        self.assertEqual(decide_status(review), "review")
        reject = dict(RESULT, confidence=0.30)
        self.assertEqual(decide_status(reject), "rejected")
        private = dict(RESULT, contains_private_info=True)
        self.assertEqual(decide_status(private), "rejected")
        not_sticker = dict(RESULT, is_reusable_sticker=False)
        self.assertEqual(decide_status(not_sticker), "rejected")

    def test_exact_dedupe_and_no_phash_merge(self):
        first = self._ingest("a.jpg", b"same")
        self.assertEqual(first["status"], "new")
        dup = self._ingest("b.jpg", b"same")
        self.assertEqual(dup["status"], "duplicate")
        near = self._ingest("c.jpg", b"same-plus-text")
        self.assertEqual(near["status"], "new")
        self.assertNotEqual(near["asset_id"], first["asset_id"])

    def test_scope_search_resolve_and_cooldown(self):
        info = self._ingest("s.jpg", b"sticker")
        self.store.recognize(info["asset_id"], dict(RESULT))
        scope1 = self.store.search("group:1", "今天好累想摸鱼")
        self.assertEqual(len(scope1), 1)
        self.assertEqual(self.store.search("group:2", "今天好累想摸鱼"), [])
        self.assertTrue(self.store.resolve(info["asset_id"], "group:1"))
        self.assertEqual(self.store.resolve(info["asset_id"], "group:2"), "")
        self.store.record_use(info["asset_id"], "group:1", "confirmed")
        self.assertFalse(self.store.can_send(info["asset_id"], "group:1"))
        self.assertTrue(self.store.can_send(info["asset_id"], "group:2"))
        self.assertEqual(self.store.search("group:1", "完全无关xyz"), [])

    def test_null_vision_keeps_pending(self):
        info = self._ingest("p.jpg", b"pending")
        self.assertFalse(NullVision().available)
        self.assertEqual(self.store.recognize(info["asset_id"], None),
                         "pending")
        summary = self.store.summary()
        self.assertEqual(summary["assets"].get("pending"), 1)

    def test_no_torch_import(self):
        self.assertNotIn("torch", sys.modules)
        self.assertNotIn("funasr", sys.modules)


class DegradeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, {"YHLZ_QQ_PROFILE": "lite"})
        self.env.start()
        self.addCleanup(self.env.stop)
        import qq_bot as qq

        self.qq = qq
        self.calls = {"turn": 0}

        def fake_turn(*a, **k):
            self.calls["turn"] += 1
            return "chat-ok"

        self.turn = mock.patch.object(qq, "_daemon_turn", side_effect=fake_turn)
        self.turn.start()
        self.addCleanup(self.turn.stop)
        self.bridge = qq.QQBridge("unused", "3655185302",
                                  pathlib.Path("unused"),
                                  masters={"2258374446"})
        self.bridge.log = mock.Mock()
        self.bridge._say = AsyncMock()
        self.bridge._deliver = AsyncMock()

    def event(self, mid, sender, text):
        return {"post_type": "message", "message_type": "private",
                "user_id": sender, "message_id": mid,
                "message": [{"type": "text", "data": {"text": text}}]}

    async def test_degrade_does_not_consume_chat_cooldown(self):
        self.bridge._daemon_ok = lambda: False
        await self.bridge.handle(None, self.event(1, "10086", "你好"))
        await self.bridge.handle(None, self.event(2, "10086", "还在吗"))
        self.assertEqual(self.calls["turn"], 0)
        self.assertEqual(self.bridge._say.await_count, 1)  # 300s 限频
        self.bridge._daemon_ok = lambda: True
        await self.bridge.handle(None, self.event(3, "10086", "恢复"))
        self.assertEqual(self.calls["turn"], 1)

    async def test_control_channel_still_works_while_degraded(self):
        class StubDev:
            def status_text(self):
                return "[利贞] 状态=idle（stub）"

        self.bridge._lite_dev = StubDev()
        self.qq._lite_dev = StubDev()
        self.bridge._daemon_ok = lambda: False
        await self.bridge.handle(None, self.event(1, "2258374446", "#devstatus"))
        self.assertTrue(any("[利贞] 状态=" in str(c.args[2])
                            for c in self.bridge._say.await_args_list))


class MentionReplyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.env = mock.patch.dict(os.environ, {
            "YHLZ_QQ_PROFILE": "lite",
            "YHLZ_QQ_STATE_DIR": str(self.tmp),
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        import qq_bot as qq

        self.qq = qq
        self.bridge = qq.QQBridge("unused", "3655185302",
                                  pathlib.Path("unused"),
                                  masters={"2258374446"})
        self.bridge.log = mock.Mock()
        self.bridge._say = AsyncMock()
        self.bridge._deliver = AsyncMock(return_value={"status": "confirmed"})
        self.bridge._daemon_ok = lambda: True
        self.bridge._group_daily_ok = lambda: True

    def event(self, mid, sender, text, group="555", at=False):
        msg = [{"type": "text", "data": {"text": text}}]
        if at and group:
            msg.append({"type": "at", "data": {"qq": "3655185302"}})
        return {"post_type": "message",
                "message_type": "group" if group else "private",
                "user_id": sender, "group_id": group, "message_id": mid,
                "message": msg}

    def _params_list(self):
        return [c.args[0] for c in self.bridge._deliver.await_args_list
                if c.args and isinstance(c.args[0], dict)]

    def _list_calls(self):
        return [p for p in self._params_list()
                if isinstance(p.get("message"), list)]

    async def test_known_person_mention_and_quote(self):
        self.bridge._group_db().add(group_id="555", message_id="m1",
                                    sender_id="200", sender_name="乙",
                                    text="先聊两句", at=1)
        with mock.patch.object(self.qq, "_daemon_turn",
                               return_value="谢谢 [[at: 200]] [[reply: m1]]"):
            await self.bridge.handle(None,
                                     self.event(2, "10086", "在吗", at=True))
        calls = self._list_calls()
        self.assertEqual(len(calls), 1)
        msg = calls[0]["message"]
        self.assertEqual(msg[0], {"type": "reply", "data": {"id": "m1"}})
        self.assertEqual(msg[1], {"type": "at", "data": {"qq": "200"}})
        self.assertEqual(msg[2]["type"], "text")

    async def test_unknown_mention_and_quote_dropped(self):
        self.bridge._group_db().add(group_id="555", message_id="m1",
                                    sender_id="200", text="x", at=1)
        with mock.patch.object(self.qq, "_daemon_turn",
                               return_value="[[at: 999]] [[reply: nope]] 你好"):
            await self.bridge.handle(None,
                                     self.event(2, "10086", "在吗", at=True))
        self.assertEqual(self._list_calls(), [])
        texts = [p.get("message") for p in self._params_list()]
        self.assertIn("你好", texts)

    async def test_private_chat_strips_markers(self):
        with mock.patch.object(
                self.qq, "_daemon_turn",
                return_value="[[at: 200]] 你好 [[reply: m1]]"):
            await self.bridge.handle(None,
                                     self.event(3, "10086", "hi", group=None))
        texts = [p.get("message") for p in self._params_list()]
        self.assertIn("你好", texts)
        self.assertFalse(any(isinstance(t, list) for t in texts))

    async def test_share_attachments_are_sent(self):
        # 2026-10-06: daemon returns file.share attachments -> bridge sends them.
        with tempfile.TemporaryDirectory() as td:
            f = pathlib.Path(td) / "pic.png"
            f.write_bytes(b"img")
            self.bridge._send_image = mock.AsyncMock()
            self.bridge._send_file = mock.AsyncMock()
            with mock.patch.object(
                    self.qq, "_daemon_turn",
                    return_value={"answer": "给你", "attachments": [str(f)]}):
                await self.bridge.handle(
                    None, self.event(4, "10086", "发张图", group=None))
            self.bridge._send_image.assert_awaited_once()
            self.bridge._send_file.assert_not_awaited()
            texts = [p.get("message") for p in self._params_list()]
            self.assertIn("给你", texts)

    async def test_share_attachment_only_no_text(self):
        with tempfile.TemporaryDirectory() as td:
            f = pathlib.Path(td) / "doc.txt"
            f.write_text("x", encoding="utf-8")
            self.bridge._send_image = mock.AsyncMock()
            self.bridge._send_file = mock.AsyncMock()
            with mock.patch.object(
                    self.qq, "_daemon_turn",
                    return_value={"answer": "", "attachments": [str(f)]}):
                await self.bridge.handle(
                    None, self.event(5, "10086", "发文件", group=None))
            self.bridge._send_file.assert_awaited_once()
            self.bridge._send_image.assert_not_awaited()


class CommandMenuTests(unittest.IsolatedAsyncioTestCase):
    """# 菜单（2026-10-09）：主人发 # 出菜单；未知指令指路；非主人不触发。"""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.env = mock.patch.dict(os.environ, {
            "YHLZ_QQ_PROFILE": "lite",
            "YHLZ_QQ_STATE_DIR": str(self.tmp),
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        import qq_bot as qq

        self.qq = qq
        self.bridge = qq.QQBridge("unused", "3655185302",
                                  pathlib.Path("unused"),
                                  masters={"2258374446"})
        self.bridge.log = mock.Mock()
        self.bridge._say = AsyncMock()
        self.bridge._deliver = AsyncMock(return_value={"status": "confirmed"})
        self.bridge._daemon_ok = lambda: True
        self.turn = mock.patch.object(qq, "_daemon_turn", return_value="收到")
        self.turn.start()
        self.addCleanup(self.turn.stop)

    def event(self, mid, sender, text):
        return {"post_type": "message", "message_type": "private",
                "user_id": sender, "message_id": mid,
                "message": [{"type": "text", "data": {"text": text}}]}

    def _menu_sent(self) -> bool:
        return any("【元亨指令菜单】" in str(c.args[2])
                   for c in self.bridge._say.await_args_list)

    async def test_hash_alone_outputs_menu(self):
        await self.bridge.handle(None, self.event(1, "2258374446", "#"))
        self.assertTrue(self._menu_sent())
        menu = next(str(c.args[2]) for c in self.bridge._say.await_args_list
                    if "【元亨指令菜单】" in str(c.args[2]))
        for token in ("#dev", "#profiles", "#voice", "#backend"):
            self.assertIn(token, menu)

    async def test_menu_aliases(self):
        for mid, text in ((2, "#help"), (3, "#菜单"), (4, "＃")):
            self.bridge._say.reset_mock()
            await self.bridge.handle(None, self.event(mid, "2258374446", text))
            self.assertTrue(self._menu_sent(), msg=text)

    async def test_unknown_command_points_to_menu(self):
        await self.bridge.handle(None, self.event(5, "2258374446", "#whatever"))
        texts = [str(c.args[2]) for c in self.bridge._say.await_args_list]
        self.assertTrue(any("未知指令" in t and "看菜单" in t for t in texts))

    async def test_nonowner_hash_is_not_menu(self):
        await self.bridge.handle(None, self.event(6, "10086", "#"))
        self.assertFalse(self._menu_sent())


if __name__ == "__main__":
    unittest.main()
