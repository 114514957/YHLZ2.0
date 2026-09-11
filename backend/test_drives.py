"""Tests for intrinsic drives (P2a)."""
import tempfile
import time
import unittest
from pathlib import Path

from backend import intrinsic_drives as drv


class DrivesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self._f = drv.DRIVES_FILE
        drv.DRIVES_FILE = self.tmp / "drives.json"

    def tearDown(self):
        drv.DRIVES_FILE = self._f

    def test_seed_and_priority(self):
        drv.seed_defaults()
        ds = drv.load()
        self.assertEqual(len(ds), 2)
        top = drv.active(1)[0]
        self.assertEqual(top["name"], "老爹的期待")  # 最高优先级
        self.assertIn("内在因", drv.inject_block())
        self.assertIn("老爹的期待", drv.inject_block())

    def test_observe_adds_curiosity_and_want(self):
        drv.seed_defaults()
        n = drv.observe("我想知道这是为什么？")
        self.assertGreaterEqual(n, 1)
        names = {d["name"] for d in drv.load()}
        self.assertTrue({"对未知的好奇", "想达成的渴望"} & names)

    def test_decay_and_fade(self):
        d = drv.add("临时渴望", "渴望", strength=0.06)
        drv.decay(now=time.time() + 90 * 86400)  # ~90 天后
        got = [x for x in drv.load() if x["id"] == d["id"]][0]
        self.assertEqual(got["status"], "faded")  # 非永久：未强化则淡出

    def test_expand_and_satisfy(self):
        d = drv.add("想读更多书", "渴望", strength=0.5)
        drv.expand(d["id"], note="顺着这个方向继续")
        s = [x for x in drv.load() if x["id"] == d["id"]][0]["strength"]
        self.assertGreater(s, 0.5)
        drv.satisfy(d["id"], 0.4)
        s2 = [x for x in drv.load() if x["id"] == d["id"]][0]["strength"]
        self.assertLess(s2, s)


if __name__ == "__main__":
    unittest.main()
