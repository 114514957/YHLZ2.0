"""Tests for proactive reflection (P5c)."""
import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from backend import reflection


class ReflectionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_reflect_appends_pending(self):
        pf = self.tmp / "pending.json"

        async def fake(m, t):
            return {"content": json.dumps([
                {"claim": "应更主动追问细节", "kind": "refine",
                 "tier": "method", "reason": "贴合期待"}])}

        n = asyncio.run(reflection.reflect(llm_turn=fake, pending_file=pf))
        self.assertEqual(n, 1)
        data = json.loads(pf.read_text(encoding="utf-8"))
        self.assertEqual(data[0]["claim"], "应更主动追问细节")
        self.assertEqual(data[0]["tier"], "method")
        # 去重：再跑一次不重复
        n2 = asyncio.run(reflection.reflect(llm_turn=fake, pending_file=pf))
        self.assertEqual(n2, 0)

    def test_reflect_empty_on_garbage(self):
        pf = self.tmp / "p2.json"

        async def fake(m, t):
            return {"content": "我没什么好反思的"}

        self.assertEqual(
            asyncio.run(reflection.reflect(llm_turn=fake, pending_file=pf)), 0)


if __name__ == "__main__":
    unittest.main()
