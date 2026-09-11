"""Tests for the conflict-resolution judge (P5b)."""
import asyncio
import unittest

from backend import memory_judge as mj


class JudgeTest(unittest.TestCase):
    def test_new(self):
        async def llm(m, t):
            return {"content": '{"more_credible":"new","reason":"更具体"}'}

        self.assertEqual(asyncio.run(mj.judge("新", "旧", llm)), "new")

    def test_old(self):
        async def llm(m, t):
            return {"content": '{"more_credible":"old","reason":"有依据"}'}

        self.assertEqual(asyncio.run(mj.judge("新", "旧", llm)), "old")

    def test_uncertain_on_garbage(self):
        async def llm(m, t):
            return {"content": "我看不出来"}

        self.assertEqual(asyncio.run(mj.judge("新", "旧", llm)), "uncertain")


if __name__ == "__main__":
    unittest.main()
