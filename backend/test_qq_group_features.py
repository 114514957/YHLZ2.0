"""QQ 群参与：唤醒闸门（@/名字/已知知识/主人）/ 日限额 / 上下文 / 表情包。

2026-10-08 起：群消息先过唤醒闸门，未命中的只入库不处理（旧"无 @ 接话"
由 config wake.enabled / 环境变量 YHLZ_QQ_WAKE 控制，默认开启）。
无真实 QQ；不写真实日限额状态文件。
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tools import qq_bot as qq  # noqa: E402


class GroupParticipationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        for name, value in [("dev_runner", None), ("_load_state", lambda: {})]:
            p = patch.object(qq, name, value)
            p.start()
            self.addCleanup(p.stop)
        self.bridge = qq.QQBridge("unused", "900", Path("unused"), masters={"100"})
        self.bridge.log = Mock()
        self.bridge._say = AsyncMock()
        self.bridge._deliver = AsyncMock()
        self.bridge._save_group_daily = Mock()      # never touch real state file
        self.bridge._group_daily = {"date": _dt.date.today().isoformat(), "count": 0}
        self.ws = Mock(send=AsyncMock())
        self.turn = patch.object(qq, "_daemon_turn", return_value="收到")
        self.call = self.turn.start()
        self.addCleanup(self.turn.stop)

    def event(self, mid=1, group="123", sender="100", text="你好", at=False):
        msg = [{"type": "text", "data": {"text": text}}]
        if at:
            msg.append({"type": "at", "data": {"qq": "900"}})
        return {"post_type": "message",
                "message_type": "group" if group else "private",
                "user_id": sender, "group_id": group, "message_id": mid,
                "message": msg}

    async def test_master_group_chat_without_at_still_replies(self):
        # 主人消息始终唤醒（wake.master_always，默认开）。
        await self.bridge.handle(self.ws, self.event(text="晚上好", at=False))
        self.call.assert_called_once()
        self.assertIn("晚上好", self.call.call_args.args[0])

    async def test_group_daily_cap_blocks(self):
        self.bridge._group_daily = {"date": _dt.date.today().isoformat(),
                                    "count": qq.GROUP_DAILY_LIMIT}
        await self.bridge.handle(self.ws, self.event(text="还在吗"))
        self.call.assert_not_called()

    async def test_group_context_includes_recent_turns(self):
        await self.bridge.handle(self.ws, self.event(mid=1, text="第一句"))
        await self.bridge.handle(self.ws, self.event(mid=2, text="第二句"))
        self.assertEqual(self.call.call_count, 2)
        second_text = self.call.call_args.args[0]
        self.assertIn("群聊最近记录", second_text)
        self.assertIn("第一句", second_text)
        self.assertIn("第二句", second_text)

    async def test_history_bounded_to_20(self):
        for i in range(25):
            await self.bridge.handle(self.ws, self.event(mid=i, text=f"m{i}"))
        hist = self.bridge._group_history["qq_g123"]
        self.assertLessEqual(len(hist), qq.GROUP_HISTORY_TURNS)

    async def test_group_context_does_not_replay_raw_history(self):
        """ledger 0816：不再每轮重灌"最近原话"（"重复读取上下文"的根源）。

        摘要里仍要能看到上一句（她得接得上话），但同一句原文只应出现一次，
        且不再有 `最近原话：` 这个原始回放块。
        """
        await self.bridge.handle(self.ws, self.event(mid=1, text="第一句"))
        await self.bridge.handle(self.ws, self.event(mid=2, text="第二句"))
        second = self.call.call_args.args[0]
        self.assertNotIn("最近原话", second)
        self.assertLessEqual(second.count("第一句"), 1)
        self.assertIn("第二句", second)          # 本轮发言本身当然要在

    async def test_image_turn_is_marked_so_later_turns_know(self):
        """ledger 0816：图片只在本轮可见 → 会话里留痕，避免下一轮自我否认。"""
        with patch.object(qq.QQBridge, "_collect_images",
                          AsyncMock(return_value=["C:/tmp/fake.png"])):
            ev = self.event(mid=7, text="看大肥鱼")
            ev["message"].append({"type": "image",
                                  "data": {"file": "fake.png"}})
            await self.bridge.handle(self.ws, ev)
        text = self.call.call_args.args[0]
        self.assertIn("本轮收到图片 1 张", text)
        self.assertIn("仅本轮可见", text)

    def test_sticker_hint_empty_then_lists(self):
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            with patch.object(qq, "STICKER_DIR", d):
                self.assertEqual(self.bridge._sticker_hint(), "")
                (d / "开心.png").write_bytes(b"x")
                hint = self.bridge._sticker_hint()
                self.assertIn("开心", hint)
                self.assertIn("[[sticker:", hint)


class _DevStub:
    """Lite dev runner stub: no jobs waiting, no side effects."""

    def awaiting_job(self, *a, **k):
        return None

    def status_text(self):
        return ""


class _StoreStub:
    """Counts context reads without touching a real group DB."""

    def __init__(self):
        self.add_calls = 0
        self.context_calls = 0

    def add(self, **kw):
        self.add_calls += 1
        return self.add_calls

    def context_block(self, group_id, before_seq=None):
        self.context_calls += 1
        return {"summary": "（暂无可读上下文）", "recent": "",
                "source_ids": [], "senders": [],
                "completeness": "partial", "count": 0}


class WakeGateTests(unittest.IsolatedAsyncioTestCase):
    """唤醒闸门（2026-10-08）：@/名字/已知知识/主人 → 唤醒；其余只入库。"""

    def setUp(self):
        for name, value in [("dev_runner", None), ("_load_state", lambda: {})]:
            p = patch.object(qq, name, value)
            p.start()
            self.addCleanup(p.stop)
        self._env = patch.dict(os.environ, {
            "YHLZ_QQ_PROFILE": "lite",
            "YHLZ_QQ_STATE_DIR": tempfile.mkdtemp(),
        })
        self._env.start()
        self.addCleanup(self._env.stop)
        p = patch.object(qq, "_lite_dev", _DevStub())
        p.start()
        self.addCleanup(p.stop)
        self._kb = patch("backend.yuanheng_kb.kb_wake_hit", return_value=None)
        self._kb.start()
        self.addCleanup(self._kb.stop)
        self._mem = patch("backend.target_memory.memory_wake_hit",
                          return_value=None)
        self._mem.start()
        self.addCleanup(self._mem.stop)
        self.bridge = qq.QQBridge("unused", "900", Path("unused"),
                                  masters={"100"})
        self.bridge.log = Mock()
        self.bridge._say = AsyncMock()
        self.bridge._deliver = AsyncMock(return_value={"status": "confirmed"})
        self.bridge._save_group_daily = Mock()      # never touch real state file
        self.bridge._group_daily = {"date": _dt.date.today().isoformat(),
                                    "count": 0}
        self.store = _StoreStub()
        self.bridge._group_db = Mock(return_value=self.store)
        self.bridge._daemon_ok = lambda: True
        self.ws = Mock(send=AsyncMock())
        self.turn = patch.object(qq, "_daemon_turn", return_value="收到")
        self.call = self.turn.start()
        self.addCleanup(self.turn.stop)

    def event(self, mid=1, group="123", sender="888", text="你好", at=False,
              reply_to=None):
        msg = [{"type": "text", "data": {"text": text}}]
        if at:
            msg.append({"type": "at", "data": {"qq": "900"}})
        if reply_to is not None:
            msg.append({"type": "reply", "data": {"id": reply_to}})
        return {"post_type": "message",
                "message_type": "group" if group else "private",
                "user_id": sender, "group_id": group, "message_id": mid,
                "message": msg}

    def _skipped(self):
        return any("未唤醒跳过" in str(c.args[0])
                   for c in self.bridge.log.call_args_list)

    async def test_unwoken_message_is_skipped_silently(self):
        await self.bridge.handle(self.ws, self.event(text="今天天气不错"))
        self.call.assert_not_called()
        self.assertEqual(self.store.context_calls, 0)
        self.assertTrue(self._skipped())

    async def test_at_wakes_and_reads_context_once(self):
        await self.bridge.handle(self.ws, self.event(text="在吗", at=True))
        self.call.assert_called_once()
        self.assertEqual(self.store.context_calls, 1)

    async def test_mention_only_wakes_and_delivers(self):
        await self.bridge.handle(self.ws, self.event(mid=401, text="", at=True))
        self.call.assert_called_once()
        self.assertEqual(self.store.context_calls, 1)
        self.bridge._deliver.assert_awaited_once()

    async def test_mention_with_whitespace_wakes(self):
        await self.bridge.handle(self.ws, self.event(mid=402, text="  \n", at=True))
        self.call.assert_called_once()

    async def test_mention_of_someone_else_without_text_stays_quiet(self):
        event = self.event(mid=403, text="", at=True)
        event["message"][-1]["data"]["qq"] = "901"
        await self.bridge.handle(self.ws, event)
        self.call.assert_not_called()
        self.bridge._deliver.assert_not_awaited()

    async def test_mention_only_preserves_explicit_silent_mode(self):
        with patch.dict(os.environ, {"YHLZ_QQ_WAKE_MODE": "silent"}):
            await self.bridge.handle(self.ws, self.event(mid=404, text="", at=True))
        self.call.assert_not_called()
        self.bridge._deliver.assert_not_awaited()

    async def test_name_wakes(self):
        await self.bridge.handle(self.ws, self.event(text="元亨 在吗"))
        self.call.assert_called_once()
        self.assertEqual(self.store.context_calls, 1)

    async def test_known_topic_wakes(self):
        with patch("backend.yuanheng_kb.kb_wake_hit",
                   return_value={"id": "kb_x", "summary": "s"}):
            await self.bridge.handle(self.ws, self.event(text="聊聊显存优化"))
        self.call.assert_called_once()

    async def test_topic_gate_off_stays_silent(self):
        with patch.dict(os.environ, {"YHLZ_QQ_WAKE_TOPICS": "0"}), \
                patch("backend.yuanheng_kb.kb_wake_hit",
                      return_value={"id": "kb_x", "summary": "s"}):
            await self.bridge.handle(self.ws, self.event(text="聊聊显存优化"))
        self.call.assert_not_called()
        self.assertEqual(self.store.context_calls, 0)

    async def test_master_always_wakes(self):
        await self.bridge.handle(self.ws,
                                 self.event(sender="100", text="随便说说"))
        self.call.assert_called_once()

    async def test_rate_limited_after_wake_does_not_read_context(self):
        self.bridge._last_reply["888"] = qq.time.time()
        await self.bridge.handle(self.ws, self.event(text="在吗", at=True))
        self.call.assert_not_called()
        self.assertEqual(self.store.context_calls, 0)
        self.assertTrue(any("频控跳过" in str(c.args[0])
                            for c in self.bridge.log.call_args_list))

    async def test_gate_off_processes_without_wake(self):
        with patch.dict(os.environ, {"YHLZ_QQ_WAKE": "0"}):
            await self.bridge.handle(self.ws, self.event(text="今天天气不错"))
        self.call.assert_called_once()
        self.assertEqual(self.store.context_calls, 1)

    async def test_memory_hit_wakes(self):
        with patch("backend.target_memory.memory_wake_hit",
                   return_value={"id": "m1", "type": "event",
                                 "importance": 6, "summary": "s"}):
            await self.bridge.handle(self.ws, self.event(text="上次我们聊过的事"))
        self.call.assert_called_once()

    async def test_memory_gate_off_stays_silent(self):
        with patch.dict(os.environ, {"YHLZ_QQ_WAKE_MEMORY": "0"}), \
                patch("backend.target_memory.memory_wake_hit",
                      return_value={"id": "m1", "type": "event",
                                    "importance": 6, "summary": "s"}):
            await self.bridge.handle(self.ws, self.event(text="上次我们聊过的事"))
        self.call.assert_not_called()
        self.assertEqual(self.store.context_calls, 0)

    async def test_reply_to_bot_message_wakes(self):
        self.bridge._sent_msg_ids["9527"] = qq.time.time()
        await self.bridge.handle(self.ws, self.event(
            text="那这句你再说说", reply_to="9527"))
        self.call.assert_called_once()

    async def test_reply_to_foreign_message_does_not_wake(self):
        await self.bridge.handle(self.ws, self.event(
            text="那这句你再说说", reply_to="1111"))
        self.call.assert_not_called()

    # ── 对话档位（2026-10-11）：活泼 / 内敛 / 缄默 ─────────────────────
    async def test_reserved_only_at_or_name_wakes(self):
        with patch.dict(os.environ, {"YHLZ_QQ_WAKE_MODE": "reserved"}):
            with patch("backend.yuanheng_kb.kb_wake_hit",
                       return_value={"id": "kb_x", "summary": "s"}):
                await self.bridge.handle(self.ws, self.event(
                    mid=21, sender="100", text="聊聊显存优化"))
            self.call.assert_not_called()           # 知识触发关闭
            await self.bridge.handle(self.ws, self.event(
                mid=22, sender="100", text="随便说说"))
            self.call.assert_not_called()           # 主人始终关闭
            await self.bridge.handle(self.ws, self.event(
                mid=23, sender="100", text="在吗", at=True))
            self.call.assert_called_once()          # @ 唤醒
            await self.bridge.handle(self.ws, self.event(
                mid=24, sender="100", text="元亨 在吗"))
            self.assertEqual(self.call.call_count, 2)  # 名字唤醒

    async def test_reserved_private_still_replies(self):
        with patch.dict(os.environ, {"YHLZ_QQ_WAKE_MODE": "reserved"}):
            await self.bridge.handle(self.ws, self.event(
                mid=25, group=None, sender="100", text="在吗"))
        self.call.assert_called_once()

    async def test_silent_blocks_group_even_at(self):
        with patch.dict(os.environ, {"YHLZ_QQ_WAKE_MODE": "silent"}):
            await self.bridge.handle(self.ws, self.event(
                mid=26, sender="100", text="在吗", at=True))
        self.call.assert_not_called()
        self.assertTrue(self._skipped())

    async def test_silent_mutes_private(self):
        with patch.dict(os.environ, {"YHLZ_QQ_WAKE_MODE": "silent"}):
            await self.bridge.handle(self.ws, self.event(
                mid=27, group=None, sender="100", text="在吗"))
        self.call.assert_not_called()

    async def test_wake_mode_command_persists(self):
        saved = {}

        def _cap(d):
            saved.clear()
            saved.update(d)

        mid = 28
        for cmd, want in (("#内敛", "reserved"), ("#缄默", "silent"),
                          ("#活泼", "lively")):
            with patch.object(qq, "_save_state", side_effect=_cap):
                await self.bridge.handle(
                    self.ws, self.event(mid=mid, sender="100", text=cmd))
            self.assertEqual(saved.get("wake_mode"), want, cmd)
            mid += 1
        self.assertIn("内敛",
                      str(self.bridge._say.await_args_list[0].args[-1]))
        self.assertGreaterEqual(self.bridge._say.await_count, 3)

    async def test_wake_mode_unknown_falls_back_lively(self):
        with patch.dict(os.environ, {"YHLZ_QQ_WAKE_MODE": "wat"}):
            await self.bridge.handle(self.ws,
                                     self.event(sender="100", text="元亨 在吗"))
        self.call.assert_called_once()

    async def test_track_sent_records_group_send_only(self):
        self.bridge._track_sent("send_msg", {"message_type": "group"},
                                {"status": "ok", "data": {"message_id": 123}})
        self.bridge._track_sent("send_msg", {"message_type": "private"},
                                {"status": "ok", "data": {"message_id": 124}})
        self.bridge._track_sent("send_msg", {"message_type": "group"},
                                {"status": "failed"})
        self.assertIn("123", self.bridge._sent_msg_ids)
        self.assertNotIn("124", self.bridge._sent_msg_ids)

    async def test_group_whitelist_blocks_other_groups(self):
        with patch.dict(os.environ, {"YHLZ_QQ_GROUPS": "123"}):
            await self.bridge.handle(self.ws, self.event(
                group="999", text="在吗", at=True))
            self.call.assert_not_called()
            self.assertEqual(self.store.add_calls, 0)   # 连入库都不做
            await self.bridge.handle(self.ws, self.event(
                group="123", text="在吗", at=True))
        self.call.assert_called_once()
        self.assertEqual(self.store.context_calls, 1)

    async def test_silence_exit_only_for_topic_wake(self):
        with patch("backend.yuanheng_kb.kb_wake_hit",
                   return_value={"id": "kb_x", "summary": "s"}), \
                patch.object(qq, "_daemon_turn", return_value="[[silence]]"):
            await self.bridge.handle(self.ws, self.event(text="聊聊显存优化"))
        self.bridge._deliver.assert_not_awaited()
        self.assertEqual(self.store.add_calls, 1)       # 只存了用户那条
        self.assertTrue(any("选择沉默" in str(c.args[0])
                            for c in self.bridge.log.call_args_list))

    async def test_silence_marker_ignored_when_must_reply(self):
        # @/引用/主人 必回：出现沉默标记吞掉，不泄漏字面，也不记"选择沉默"。
        with patch.object(qq, "_daemon_turn", return_value="[[silence]]"):
            await self.bridge.handle(self.ws, self.event(text="在吗", at=True))
        self.bridge._deliver.assert_not_awaited()
        logs = [str(c.args[0]) for c in self.bridge.log.call_args_list]
        self.assertTrue(any("沉默标记被忽略" in s for s in logs))
        self.assertFalse(any("选择沉默" in s for s in logs))

    async def test_silence_marker_ignored_for_master(self):
        with patch.object(qq, "_daemon_turn", return_value="[[silence]]"):
            await self.bridge.handle(self.ws,
                                     self.event(sender="100", text="随便说说"))
        logs = [str(c.args[0]) for c in self.bridge.log.call_args_list]
        self.assertTrue(any("沉默标记被忽略" in s for s in logs))

    async def test_silence_hint_only_when_optional(self):
        self.bridge._rate_limited = lambda c, u: False
        await self.bridge.handle(self.ws, self.event(text="在吗", at=True))
        self.assertNotIn("[[silence]]", self.call.call_args.args[0])
        with patch("backend.yuanheng_kb.kb_wake_hit",
                   return_value={"id": "kb_x", "summary": "s"}):
            await self.bridge.handle(self.ws,
                                     self.event(mid=2, text="聊聊显存优化"))
        self.assertIn("[[silence]]", self.call.call_args.args[0])

    async def test_speaker_profile_card_injected(self):
        stub = Mock()
        stub.brief = Mock(return_value="QYFancy(335203862)｜群友｜发言107")
        self.bridge._profiles_db = Mock(return_value=stub)
        await self.bridge.handle(self.ws, self.event(text="在吗", at=True))
        text = self.call.call_args.args[0]
        self.assertIn("【当前发言人档案】", text)
        self.assertIn("QYFancy", text)

    async def test_profile_card_can_be_disabled(self):
        stub = Mock()
        stub.brief = Mock(return_value="X(1)｜群友")
        self.bridge._profiles_db = Mock(return_value=stub)
        with patch.dict(os.environ, {"YHLZ_QQ_PROFILE_INJECT": "0"}):
            await self.bridge.handle(self.ws, self.event(text="在吗", at=True))
        self.assertNotIn("【当前发言人档案】", self.call.call_args.args[0])

    async def test_at_only_group_ignores_everything_but_at(self):
        # 2026-10-10：at_only 群只在 @ 时唤醒（名字/知识/主人都静默）。
        with patch.dict(os.environ, {"YHLZ_QQ_WAKE_AT_ONLY_GROUPS": "123"}):
            await self.bridge.handle(self.ws, self.event(text="元亨 在吗"))
            self.call.assert_not_called()
            with patch("backend.yuanheng_kb.kb_wake_hit",
                       return_value={"id": "kb_x", "summary": "s"}):
                await self.bridge.handle(
                    self.ws, self.event(mid=2, text="聊聊显存优化"))
            self.call.assert_not_called()
            await self.bridge.handle(
                self.ws, self.event(mid=3, sender="100", text="随便说说"))
            self.call.assert_not_called()   # 主人不 @ 也静默
            await self.bridge.handle(
                self.ws, self.event(mid=4, text="在吗", at=True))
            self.call.assert_called_once()


class MarkerParseTests(unittest.TestCase):
    def test_extract_markers_includes_mface_and_sticker(self):
        (ans, imgs, files, faces, voice, devs, mfaces, stickers, ats,
         replies) = qq._extract_markers(
            "好 [[face: 4]] [[mface: 12345]] [[sticker: 开心]] [[img: a.png]]"
            " [[at: 200]] [[reply: m1]]")
        self.assertEqual(faces, ["4"])
        self.assertEqual(mfaces, ["12345"])
        self.assertEqual(stickers, ["开心"])
        self.assertEqual(imgs, ["a.png"])
        self.assertEqual(ats, ["200"])
        self.assertEqual(replies, ["m1"])
        self.assertEqual(ans, "好")


if __name__ == "__main__":
    unittest.main()
