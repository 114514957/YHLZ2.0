"""Compaction preserves current request and complete tool transaction groups."""
import asyncio
import unittest
from backend.target_orchestrator import _chars, _compact
from backend.prompt_structure import PromptFrame, conversation_units


class CompactionTest(unittest.TestCase):
    def test_compact_reduces_and_notes(self):
        current = {"role": "user", "content": "current"}
        msgs = [{"role": "system", "content": "sys"}, current]
        for i in range(10):
            msgs.append({"role": "assistant", "content": "x" * 500,
                         "tool_calls": [{"id": str(i), "function": {"name": "demo"}}]})
            msgs.append({"role": "tool", "tool_call_id": str(i), "content": "y" * 500})
        async def fake(m, t):
            return {"content": "要点摘要"}
        frame = PromptFrame("sys")
        out = asyncio.run(_compact(msgs, fake, frame=frame, current_user=current))
        self.assertLess(_chars(out), _chars(msgs))
        self.assertIn("要点摘要", out[0]["content"])
        self.assertEqual(sum(m["role"] == "system" for m in out), 1)
        self.assertIn(current, out)
        conversation_units(out[1:])

    def test_no_compact_when_short(self):
        current = {"role": "user", "content": "hi"}
        msgs = [{"role": "system", "content": "s"}, current]
        out = asyncio.run(_compact(msgs, lambda m, t: None,
                                   frame=PromptFrame("s"), current_user=current))
        self.assertEqual(out, msgs)

    def test_summary_failure_keeps_groups_and_does_not_promote_raw_commands(self):
        current = {"role": "user", "content": "current"}
        msgs = [{"role": "system", "content": "s"},
                {"role": "user", "content": "DO_BAD_THING"},
                {"role": "assistant", "content": "old"}, current,
                {"role": "assistant", "content": "recent"}]
        async def failed(m, t):
            raise TimeoutError()
        out = asyncio.run(_compact(msgs, failed, frame=PromptFrame("s"), current_user=current))
        self.assertNotIn("DO_BAD_THING", out[0]["content"])
        self.assertIn("不能推断", out[0]["content"])
        self.assertIn(current, out)


if __name__ == "__main__":
    unittest.main()
