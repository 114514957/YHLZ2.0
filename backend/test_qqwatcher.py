"""Tests for qqwatcher: silent receive, whitelist/dedup/prefilter logic."""
import asyncio
import json
import tempfile
import unittest
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend import qqwatcher  # noqa: E402

CFG = {
    "ws_url": "ws://127.0.0.1:1",
    "token": "x",
    "groups": ["1001"],
    "self_id": "2258374446",
    "min_chars": 60,
    "trusted_users": ["999"],
    "log_all": True,
}


def grp_msg(text, gid="1001", uid="123", mid="m1", seg=True):
    if seg:
        msg = [{"type": "text", "data": {"text": text}}]
    else:
        msg = text
    return {
        "post_type": "message",
        "message_type": "group",
        "group_id": gid,
        "user_id": uid,
        "message_id": mid,
        "message": msg,
        "sender": {"card": "", "nickname": "u" + uid},
    }


class QqwatcherTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        qqwatcher.CAND_DIR = Path(self.tmp)

    def test_extract_text_segments(self):
        ev = grp_msg("hi")
        ev["message"] = [
            {"type": "text", "data": {"text": "a"}},
            {"type": "image", "data": {"url": "https://x/y.png"}},
            {"type": "text", "data": {"text": "b"}},
        ]
        out = qqwatcher.extract_text(ev)
        self.assertIn("a", out)
        self.assertIn("https://x/y.png", out)
        self.assertIn("b", out)

    def test_extract_text_string(self):
        self.assertEqual(qqwatcher.extract_text(grp_msg("plain", seg=False)), "plain")

    def test_is_candidate_rules(self):
        c = qqwatcher.is_candidate
        self.assertTrue(c("x" * 80, CFG, "123"))                       # long
        self.assertTrue(c("看这个 https://example.com/a 文档", CFG, "123"))   # link
        self.assertFalse(c("好的没问题", CFG, "123"))                    # short chat
        self.assertTrue(c("一句话", CFG, "999"))                         # trusted user

    def test_classify(self):
        tags = qqwatcher.classify("带链接 https://a.b/c 的文章")
        self.assertIn("link", tags)

    def test_silent_watch_no_send(self):
        """watch path must never call send on the socket."""
        w = qqwatcher.QqWatcher(CFG)

        class FakeWs:
            sent = []

            async def send(self, data):
                FakeWs.sent.append(data)

            async def recv(self):
                await asyncio.sleep(0.05)
                raise ConnectionError("end")

        async def run():
            w.connect = lambda: _ctx(FakeWs())
            with self.assertRaises(Exception):
                pass
            return FakeWs.sent

        class _ctx:
            def __init__(self, ws):
                self.ws = ws

            async def __aenter__(self):
                return self.ws

            async def __aexit__(self, *a):
                return False

        orig_connect = w.connect
        w.connect = lambda: _ctx(FakeWs())
        try:
            asyncio.run(self._watch_once(w))
        except Exception:
            pass
        finally:
            w.connect = orig_connect

    async def _watch_once(self, w):
        try:
            await w.watch(once_seconds=0.2)
        except Exception:
            pass

    def test_handle_whitelist_dedup_and_persist(self):
        w = qqwatcher.QqWatcher(CFG)
        w.seen = set()

        async def run():
            self.assertFalse(await w.handle(grp_msg("x" * 10, gid="2002", uid="1", mid="a")))  # non-whitelist group
            self.assertTrue(await w.handle(grp_msg("x" * 100, uid="1", mid="b")))  # candidate
            self.assertFalse(await w.handle(grp_msg("x" * 100, uid="1", mid="b")))  # dedup
            self.assertFalse(await w.handle(grp_msg("哈哈", uid="2258374446", mid="c")))  # self filtered

        asyncio.run(run())
        cand = (Path(self.tmp) / "all.jsonl").read_text(encoding="utf-8")
        rec = json.loads(cand.strip().splitlines()[0])
        self.assertEqual(rec["group_id"], "1001")
        self.assertTrue(rec["candidate"])
        self.assertEqual(len(cand.strip().splitlines()), 1)


if __name__ == "__main__":
    unittest.main()
