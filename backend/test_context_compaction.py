"""Tests for mid-loop context compaction."""
import asyncio
import unittest

from backend.target_orchestrator import _chars, _compact


class CompactionTest(unittest.TestCase):
    def test_compact_reduces_and_notes(self):
        msgs = [{"role": "system", "content": "sys"}]
        for _ in range(10):
            msgs.append({"role": "assistant", "content": "x" * 500})
            msgs.append({"role": "tool", "content": "y" * 500})

        async def fake(m, t):
            return {"content": "要点摘要"}

        out = asyncio.run(_compact(msgs, fake))
        self.assertLess(_chars(out), _chars(msgs))
        self.assertTrue(any("此前过程摘要" in str(m.get("content")) for m in out))

    def test_no_compact_when_short(self):
        msgs = [{"role": "system", "content": "s"},
                {"role": "user", "content": "hi"}]
        out = asyncio.run(_compact(msgs, lambda m, t: None))
        self.assertEqual(out, msgs)


if __name__ == "__main__":
    unittest.main()
