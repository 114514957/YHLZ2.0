"""Tests for backend/qq_delivery.py — Phase 2 (plan §6.1).

Covers the delivery state machine, ack classification, bounded retry, reply
TTL, ordering, id uniqueness and redaction.  The outbox confirm-before-ack
boundary is also checked here (plan §6.1 items 9–11).  No real QQ is used.
"""

from __future__ import annotations

import asyncio
import json
import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from backend.qq_delivery import (  # noqa: E402
    DeliveryManager,
    DeliveryTransportError,
    classify_response,
)


class _Clock:
    def __init__(self, start: float = 1000.0) -> None:
        self.now = float(start)

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += float(seconds)


class _Transport:
    """Scripted transport: each call pops the next item (dict or exception)."""

    def __init__(self, script) -> None:
        self.script = list(script)
        self.calls: list[dict] = []

    async def __call__(self, action: str, params: dict) -> dict:
        self.calls.append({"action": action, "params": dict(params)})
        if not self.script:
            raise AssertionError("transport script exhausted")
        item = self.script.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


_OK = {"status": "ok", "retcode": 0}


class DeliveryManagerTests(unittest.IsolatedAsyncioTestCase):
    def _manager(self, transport, *, clock=None, sleeps=None, **kw):
        clock = clock or _Clock()
        recorded = sleeps if sleeps is not None else []

        async def _sleep(seconds: float) -> None:
            recorded.append(seconds)
            clock.advance(seconds)

        return DeliveryManager(transport, clock=clock, sleep=_sleep,
                               status_path=None, **kw), recorded

    async def _send(self, mgr, *, kind="reply", params=None, ttl_s=None):
        return await mgr.send(kind=kind, target={"message_type": "private",
                                                 "user_id": 1},
                              params=params or {"message": "hi"}, ttl_s=ttl_s)

    # 1. status=ok -> confirmed
    async def test_confirmed(self):
        t = _Transport([_OK])
        mgr, _ = self._manager(t)
        rec = await self._send(mgr)
        self.assertEqual(rec["status"], "confirmed")
        self.assertEqual(len(t.calls), 1)
        self.assertEqual(mgr.counters()["qq_delivery_confirmed"], 1)

    # 2. param error -> rejected, no retry
    async def test_rejected_param_error_no_retry(self):
        t = _Transport([{"status": "failed", "retcode": 100}])
        mgr, sleeps = self._manager(t)
        rec = await self._send(mgr)
        self.assertEqual(rec["status"], "rejected")
        self.assertEqual(len(t.calls), 1)
        self.assertEqual(sleeps, [])
        self.assertEqual(mgr.counters()["qq_delivery_rejected"], 1)

    # 3. before_send failure -> retryable; 6. retries capped at 2; 7. backoff 1s/3s
    async def test_before_send_retryable_and_capped(self):
        t = _Transport([DeliveryTransportError(stage="before_send")] * 5)
        mgr, sleeps = self._manager(t)
        rec = await self._send(mgr)
        self.assertEqual(rec["status"], "retryable")
        self.assertEqual(rec["attempt"], 3)          # 1 initial + 2 retries
        self.assertEqual(sleeps, [1.0, 3.0])
        self.assertEqual(len(t.calls), 3)

    # 3b. before_send then success
    async def test_before_send_recovers(self):
        t = _Transport([DeliveryTransportError(stage="before_send"),
                        DeliveryTransportError(stage="before_send"), _OK])
        mgr, sleeps = self._manager(t)
        rec = await self._send(mgr)
        self.assertEqual(rec["status"], "confirmed")
        self.assertEqual(sleeps, [1.0, 3.0])
        self.assertEqual(len(t.calls), 3)

    # 4. after_send disconnect -> unknown, no resend
    async def test_after_send_unknown_no_resend(self):
        t = _Transport([DeliveryTransportError(stage="after_send")] * 3)
        mgr, sleeps = self._manager(t)
        rec = await self._send(mgr)
        self.assertEqual(rec["status"], "unknown")
        self.assertEqual(len(t.calls), 1)
        self.assertEqual(sleeps, [])
        self.assertEqual(mgr.counters()["qq_delivery_unknown"], 1)

    # 5. ack timeout -> unknown
    async def test_timeout_unknown(self):
        t = _Transport([asyncio.TimeoutError()] * 2)
        mgr, _ = self._manager(t)
        rec = await self._send(mgr)
        self.assertEqual(rec["status"], "unknown")
        self.assertEqual(len(t.calls), 1)

    # 8. reply past its TTL is not resent (expires during backoff)
    async def test_reply_ttl_expires(self):
        t = _Transport([DeliveryTransportError(stage="before_send")] * 5)
        clock = _Clock()
        # 2s ttl: 1s backoff ok, then 3s backoff pushes past expiry
        mgr, sleeps = self._manager(t, clock=clock, reply_ttl_s=2.0)
        rec = await self._send(mgr, ttl_s=2.0)
        self.assertEqual(rec["status"], "expired")
        self.assertEqual(mgr.counters()["qq_delivery_expired"], 1)
        self.assertLessEqual(len(t.calls), 3)

    # 12. two same-target messages keep enqueue order (global concurrency 1)
    async def test_order_and_single_flight(self):
        order: list[str] = []

        async def slow(action: str, params: dict) -> dict:
            order.append(params["message"])
            await asyncio.sleep(0.01)
            return _OK

        mgr = DeliveryManager(slow, status_path=None)
        results = await asyncio.gather(
            mgr.send(kind="reply", target={"message_type": "private", "user_id": 1},
                     params={"message": "first"}),
            mgr.send(kind="reply", target={"message_type": "private", "user_id": 1},
                     params={"message": "second"}),
        )
        self.assertEqual(order, ["first", "second"])
        self.assertTrue(all(r["status"] == "confirmed" for r in results))

    # 15. delivery_id is unique
    async def test_delivery_id_unique(self):
        t = _Transport([_OK] * 5)
        mgr, _ = self._manager(t)
        ids = [(await self._send(mgr, params={"message": f"m{i}"}))["delivery_id"]
               for i in range(5)]
        self.assertEqual(len(set(ids)), 5)

    # 16. records never contain the message body
    async def test_redacted_records(self):
        t = _Transport([_OK])
        mgr, _ = self._manager(t)
        secret = "super-secret-qq-text"
        await self._send(mgr, params={"message": secret})
        blob = repr(mgr.recent())
        self.assertNotIn(secret, blob)
        self.assertIn("payload_hash", mgr.recent()[0])


class ClassifyTests(unittest.TestCase):
    def test_ok_is_confirmed(self):
        self.assertEqual(classify_response({"status": "ok", "retcode": 0})[0],
                         "confirmed")

    def test_failed_is_rejected(self):
        self.assertEqual(classify_response({"status": "failed", "retcode": 100})[0],
                         "rejected")

    def test_malformed_is_rejected(self):
        self.assertEqual(classify_response(None)[0], "rejected")


class BridgeDeliveryIntegrationTests(unittest.IsolatedAsyncioTestCase):
    """The real bridge's send path is wired through the delivery manager."""

    def _bridge(self):
        from tools.qq_bot import QQBridge
        return QQBridge("ws://x", "1", Path("cfg.json"), masters={"1"})

    async def test_request_labels_before_send(self):
        bridge = self._bridge()

        class BadWS:
            async def send(self, *_a):
                raise RuntimeError("socket gone")

        with self.assertRaises(Exception) as ctx:
            await bridge._request(BadWS(), "send_msg", {"message": "hi"})
        self.assertEqual(getattr(ctx.exception, "stage", None), "before_send")

    async def test_say_goes_through_delivery_and_confirms(self):
        bridge = self._bridge()
        sent: list[dict] = []

        class EchoWS:
            async def send(self, raw):
                msg = json.loads(raw)
                sent.append(msg)
                fut = bridge._pending.get(msg["echo"])
                if fut is not None and not fut.done():
                    fut.set_result({"status": "ok", "retcode": 0})

        ws = EchoWS()
        bridge._transport.ws = ws
        await bridge._say(ws, {"message_type": "private", "user_id": 7}, "你好")
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]["action"], "send_msg")
        self.assertEqual(sent[0]["params"]["message"], "你好")
        self.assertEqual(bridge.delivery.counters()["qq_delivery_confirmed"], 1)


class OutboxBoundaryTests(unittest.TestCase):
    """Plan §6.1 items 9–11: confirm-before-ack + legacy read."""

    def setUp(self):
        import tempfile
        from backend import qq_outbox
        self._qq_outbox = qq_outbox
        self._tmp = tempfile.TemporaryDirectory()
        self._orig = qq_outbox.OUTBOX
        qq_outbox.OUTBOX = Path(self._tmp.name) / "qq_outbox.jsonl"

    def tearDown(self):
        self._qq_outbox.OUTBOX = self._orig
        self._tmp.cleanup()

    def test_peek_does_not_remove_and_ack_only_after_ok(self):
        ob = self._qq_outbox
        ob.push("一条主动消息")
        items = ob.peek(5)
        self.assertEqual(len(items), 1)
        self.assertEqual(len(ob.peek(5)), 1)   # peek is non-destructive
        removed = ob.ack(items)                # ack only after status=ok
        self.assertEqual(removed, 1)
        self.assertEqual(ob.peek(5), [])

    def test_legacy_item_without_id_readable(self):
        ob = self._qq_outbox
        import json
        ob.OUTBOX.write_text(json.dumps({"text": "旧消息", "kind": "proactive"},
                                        ensure_ascii=False) + "\n", encoding="utf-8")
        items = ob.peek(5)
        self.assertEqual(len(items), 1)
        self.assertTrue(items[0].get("id"))
        self.assertEqual(ob.ack(items), 1)


if __name__ == "__main__":
    unittest.main()
