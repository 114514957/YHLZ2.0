"""QQ 桥认主/聊天分界（2026-10-06 规则修订）：

只有主人 2258374446 的外层真实指令进入命令处理器；其他人的 `#` 文本只是
普通聊天，不再返回安全接管话术。未连接真实 QQ。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tools import qq_bot as qq  # noqa: E402


class OwnerRoutingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        for name, value in [("dev_runner", None), ("_load_state", lambda: {})]:
            p = patch.object(qq, name, value)
            p.start()
            self.addCleanup(p.stop)
        self.bridge = qq.QQBridge("unused", "900", Path("unused"),
                                  masters={"2258374446"})
        self.bridge.log = Mock()
        self.bridge._say = AsyncMock()
        self.bridge._deliver = AsyncMock()   # avoid ack plumbing in routing tests
        self.ws = Mock(send=AsyncMock())
        self.turn = patch.object(qq, "_daemon_turn", return_value="ok")
        self.call = self.turn.start()
        self.addCleanup(self.turn.stop)

    def event(self, mid=1, group=None, sender="555", text="#dev rm -rf /"):
        msg = [{"type": "text", "data": {"text": text}}]
        if group is not None:
            msg.append({"type": "at", "data": {"qq": "900"}})
        return {"post_type": "message",
                "message_type": "group" if group else "private",
                "user_id": sender, "group_id": group, "message_id": mid,
                "message": msg}

    async def test_nonmaster_group_command_is_plain_chat(self):
        await self.bridge.handle(self.ws, self.event(group="123"))
        self.call.assert_called_once()
        self.assertIn("#dev rm -rf /", self.call.call_args.args[0])

    async def test_nonmaster_private_command_is_plain_chat(self):
        await self.bridge.handle(self.ws, self.event(text="#img C:/x/.env"))
        self.call.assert_called_once()
        self.assertIn("#img C:/x/.env", self.call.call_args.args[0])

    async def test_nonmaster_group_chat_is_chat(self):
        await self.bridge.handle(self.ws, self.event(group="123", text="你好"))
        self.call.assert_called_once()

    async def test_master_command_skips_chat(self):
        with patch.object(qq, "_save_state", Mock()):
            await self.bridge.handle(
                self.ws, self.event(sender="2258374446", text="#voice off"))
        self.call.assert_not_called()
        self.assertTrue(any("语音回复" in str(c.args[2])
                            for c in self.bridge._say.await_args_list))

    async def test_nonmaster_group_command_without_wake_is_skipped(self):
        ev = self.event(group="123")
        ev["message"] = ev["message"][:1]        # drop the @ segment
        with patch("backend.yuanheng_kb.kb_wake_hit", return_value=None), \
                patch("backend.target_memory.memory_wake_hit",
                      return_value=None):
            await self.bridge.handle(self.ws, ev)
        self.call.assert_not_called()            # 唤醒闸门：不叫不接

    async def test_nonmaster_group_command_with_name_is_chat(self):
        ev = self.event(group="123", text="元亨 #dev rm -rf /")
        ev["message"] = ev["message"][:1]        # drop the @ segment
        await self.bridge.handle(self.ws, ev)
        self.call.assert_called_once()
        self.assertIn("#dev rm -rf /", self.call.call_args.args[0])


class PublishDirGateTests(unittest.TestCase):
    """群聊图片/文件只允许来自授权发布目录（ledger 0537）。"""

    def setUp(self):
        self.bridge = qq.QQBridge("unused", "900", Path("unused"),
                                  masters={"2258374446"})
        self.bridge.log = Mock()
        self._saved = qq.PUBLISH_DIRS

    def tearDown(self):
        qq.PUBLISH_DIRS = self._saved

    def test_publishable_only_inside_publish_dir(self):
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            pub = Path(td) / "pub"
            pub.mkdir()
            inside = pub / "cover.png"
            inside.write_bytes(b"img")
            outside = Path(td) / "elsewhere.png"
            outside.write_bytes(b"img")
            secret = pub / ".env"
            secret.write_text("KEY=1", encoding="utf-8")
            qq.PUBLISH_DIRS = (pub,)
            self.assertTrue(self.bridge._is_publishable(str(inside)))
            self.assertFalse(self.bridge._is_publishable(str(outside)))
            self.assertFalse(self.bridge._is_publishable(str(secret)))


class ForwardTests(unittest.IsolatedAsyncioTestCase):
    """能转发：OneBot 合并转发（ledger 0537）。"""

    def setUp(self):
        for name, value in [("dev_runner", Mock()), ("_load_state", lambda: {})]:
            p = patch.object(qq, name, value)
            p.start()
            self.addCleanup(p.stop)
        self.bridge = qq.QQBridge("unused", "3655185302", Path("unused"),
                                  masters={"2258374446"})
        self.bridge.log = Mock()
        self.ws = Mock(send=AsyncMock())

    async def test_send_forward_picks_group_action(self):
        self.bridge._deliver = AsyncMock(return_value={"status": "confirmed"})
        await self.bridge._send_forward(
            self.ws, {"message_type": "group", "group_id": 1}, [{"type": "node"}])
        self.assertEqual(self.bridge._deliver.await_args.kwargs["action"],
                         "send_group_forward_msg")

    async def test_send_forward_picks_private_action(self):
        self.bridge._deliver = AsyncMock(return_value={"status": "confirmed"})
        await self.bridge._send_forward(
            self.ws, {"message_type": "private", "user_id": 1}, [{"type": "node"}])
        self.assertEqual(self.bridge._deliver.await_args.kwargs["action"],
                         "send_private_forward_msg")

    async def test_master_fwd_command_routes_to_forward(self):
        self.bridge._send_forward = AsyncMock()
        ev = {"post_type": "message", "message_type": "private", "user_id": "2258374446",
              "message_id": 1, "message": [{"type": "text", "data": {"text": "#fwd 你好"}}]}
        await self.bridge._dev_cmd(self.ws, "#fwd 你好", "private", "2258374446", ev)
        self.bridge._send_forward.assert_awaited_once()


class MediaCommandDecoupleTests(unittest.IsolatedAsyncioTestCase):
    """媒体类主人指令不依赖开发运行器（ledger 0538）。"""

    def setUp(self):
        self.bridge = qq.QQBridge("unused", "3655185302", Path("unused"),
                                  masters={"2258374446"})
        self.bridge.log = Mock()
        self.bridge._say = AsyncMock()
        self.ws = Mock(send=AsyncMock())

    async def test_media_command_available_without_dev_runner(self):
        with patch.object(qq, "dev_runner", None), \
                patch.object(qq, "_load_state", lambda: {"voice": False}), \
                patch.object(qq, "_save_state", lambda st: None):
            self.bridge._send_forward = AsyncMock()
            await self.bridge._dev_cmd(self.ws, "#fwd 你好", "private",
                                       "2258374446", {})
            self.bridge._send_forward.assert_awaited_once()

    async def test_dev_command_reports_unavailable_without_runner(self):
        with patch.object(qq, "dev_runner", None):
            await self.bridge._dev_cmd(self.ws, "#devstatus", "private",
                                       "2258374446", {})
            self.assertEqual(self.bridge._say.await_args.args[2],
                             "[利贞] 运行器不可用")


if __name__ == "__main__":
    unittest.main()
