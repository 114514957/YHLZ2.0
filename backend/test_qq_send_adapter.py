"""T3 统一发送适配器测试（ledger 0629）。假传输，无真实 QQ/网络。"""
from __future__ import annotations

import asyncio
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, ".")

import backend.qq_delivery_store as ds  # noqa: E402
import backend.qq_send_adapter as ad  # noqa: E402
from backend.qq_delivery import DeliveryTransportError  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


class AdapterTest(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="t3_ad_"))
        self.con = ds.connect(self.tmp / "d.db")

    def tearDown(self):
        self.con.close()

    def _send(self, transport, **kw):
        base = dict(source_event_id="e1", channel="qq_p1", target_type="private",
                    target_id="2258374446", params={"message": "hi"}, transport=transport)
        base.update(kw)
        return _run(ad.send(self.con, **base))

    def test_ack_ok_confirmed(self):
        async def t(action, params):
            return {"status": "ok", "retcode": 0}
        r = self._send(t)
        self.assertEqual(r["state"], "confirmed")
        self.assertEqual(ds.status_summary(self.con), {"confirmed": 1})

    def test_rejected_not_retried(self):
        async def t(action, params):
            return {"status": "failed", "retcode": 1, "message": "param error"}
        r = self._send(t)
        self.assertEqual(r["state"], "rejected")

    def test_before_send_retries_then_retryable(self):
        n = {"c": 0}

        async def t(action, params):
            n["c"] += 1
            raise DeliveryTransportError("connect refused", stage="before_send")
        r = self._send(t, max_retries=2)
        self.assertEqual(r["state"], "retryable")
        self.assertEqual(n["c"], 3)

    def test_after_send_unknown_no_resend(self):
        async def t(action, params):
            raise DeliveryTransportError("timeout after send", stage="after_send")
        r = self._send(t)
        self.assertEqual(r["state"], "unknown")
        # 再发同事件：幂等返回 unknown，不重发
        r2 = self._send(t)
        self.assertTrue(r2["idempotent"])
        self.assertEqual(r2["state"], "unknown")

    def test_duplicate_same_event_idempotent(self):
        async def t(action, params):
            return {"status": "ok", "retcode": 0}
        r1 = self._send(t)
        r2 = self._send(t)
        self.assertTrue(r2["idempotent"])
        self.assertEqual(r1["delivery_id"], r2["delivery_id"])
        self.assertEqual(ds.status_summary(self.con), {"confirmed": 1})


if __name__ == "__main__":
    unittest.main()
