"""Tests for the QQ outbox (P2e)."""
import tempfile
import unittest
from pathlib import Path

from backend import qq_outbox


class OutboxTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self._f = qq_outbox.OUTBOX
        qq_outbox.OUTBOX = self.tmp / "outbox.jsonl"

    def tearDown(self):
        qq_outbox.OUTBOX = self._f

    def test_push_and_drain(self):
        qq_outbox.push("hello")
        qq_outbox.push("world")
        items = qq_outbox.drain()
        self.assertEqual([i["text"] for i in items], ["hello", "world"])
        self.assertEqual(qq_outbox.drain(), [])  # cleared
        self.assertFalse(qq_outbox.OUTBOX.read_text(encoding="utf-8").strip())

    def test_empty_push_ignored(self):
        qq_outbox.push("   ")
        self.assertEqual(qq_outbox.drain(), [])


if __name__ == "__main__":
    unittest.main()
