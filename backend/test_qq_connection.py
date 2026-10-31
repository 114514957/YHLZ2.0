"""Offline tests for QQ protocol keepalive and retry-safe outbox boundaries."""
import asyncio
import tempfile
import unittest
from pathlib import Path

from backend import qq_connection, qq_outbox


class _GoodWs:
    def __init__(self):
        self.loop = asyncio.get_running_loop()
        self.pings = 0

    def ping(self):
        self.pings += 1
        fut = self.loop.create_future()
        fut.set_result(None)
        return fut


class _DeadWs:
    def ping(self):
        return asyncio.get_running_loop().create_future()


class QqConnectionTest(unittest.TestCase):
    def test_ping_updates_snapshot(self):
        async def run():
            state = qq_connection.ConnectionSnapshot(state="connected")
            ws = _GoodWs()
            await qq_connection.ping_once(ws, state, 0.05)
            self.assertEqual(ws.pings, 1)
            self.assertGreater(state.last_ping_at, 0)
            self.assertGreater(state.last_pong_at, 0)
            self.assertEqual(state.heartbeat_failures, 0)

        asyncio.run(run())

    def test_ping_timeout_is_failure(self):
        async def run():
            state = qq_connection.ConnectionSnapshot(state="connected")
            with self.assertRaises(asyncio.TimeoutError):
                await qq_connection.ping_once(_DeadWs(), state, 0.01)

        asyncio.run(run())


class QqOutboxRetryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.old = qq_outbox.OUTBOX
        qq_outbox.OUTBOX = self.tmp / "outbox.jsonl"

    def tearDown(self):
        qq_outbox.OUTBOX = self.old

    def test_peek_keeps_item_until_ack(self):
        qq_outbox.push("keep me")
        item = qq_outbox.peek(1)[0]
        self.assertEqual(qq_outbox.peek(1)[0]["id"], item["id"])
        self.assertEqual(qq_outbox.ack(item), 1)
        self.assertEqual(qq_outbox.peek(1), [])

    def test_failed_send_boundary_does_not_drop_item(self):
        qq_outbox.push("retry me")
        item = qq_outbox.peek(1)[0]
        # Simulate a failed transport: no ack call is made.
        self.assertEqual(qq_outbox.peek(1)[0]["text"], item["text"])


if __name__ == "__main__":
    unittest.main()
