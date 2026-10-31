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
        block = drv.inject_block()
        self.assertIn("内在倾向", block)
        self.assertIn("老爹的期待", block)

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

    def test_dad_direction_and_constitutional_no_decay(self):
        drv.seed_defaults()
        self.assertEqual(drv.dad_direction("我希望你去多学点哲学"), 1)
        self.assertIn("老爹的方向期待", {d["name"] for d in drv.load()})
        # 期待 category 不衰减（宪法式）
        ds = drv.load()
        for d in ds:
            if d["category"] == "期待":
                d["strength"] = 0.06
        drv.save(ds)
        drv.decay(now=time.time() + 365 * 86400)
        for d in drv.load():
            if d["category"] == "期待":
                self.assertEqual(d["status"], "active")
        # 冲突时老爹优先：注入里点明
        self.assertIn("以老爹的期待为先", drv.inject_block())


class DrivesUrgeTest(unittest.TestCase):
    """0501：内在因要能影响**行为何时发生**，不只是注入文本。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self._f = drv.DRIVES_FILE
        drv.DRIVES_FILE = self.tmp / "drives.json"

    def tearDown(self):
        drv.DRIVES_FILE = self._f

    def test_urge_excludes_expectation(self):
        """期待是恒定 1.0 的持续授权，若参与比较阈值就永远形同虚设。"""
        drv.seed_defaults()          # 老爹的期待 1.0 + 好奇 0.6
        u = drv.urge()
        self.assertNotEqual(u["name"], "老爹的期待")
        self.assertEqual(u["name"], "对未知的好奇")
        self.assertAlmostEqual(u["strength"], 0.6, places=3)

    def test_urge_picks_strongest_non_expectation(self):
        drv.seed_defaults()
        drv.add("想读更多书", "渴望", strength=0.9)
        self.assertEqual(drv.urge()["name"], "想读更多书")
        self.assertEqual(drv.urge()["category"], "渴望")

    def test_urge_zero_when_only_expectation_left(self):
        drv.add("老爹的期待", "期待", strength=1.0)
        u = drv.urge()
        self.assertEqual(u["strength"], 0.0)
        self.assertEqual(u["name"], "")

    def test_urge_ignores_faded(self):
        d = drv.add("临时渴望", "渴望", strength=0.06)
        drv.decay(now=time.time() + 90 * 86400)   # 淡出
        self.assertEqual(drv.urge()["name"], "")
        self.assertIsNotNone(d["id"])

    def test_urge_never_raises_on_broken_file(self):
        drv.DRIVES_FILE.write_text("{ not json", encoding="utf-8")
        self.assertEqual(drv.urge()["strength"], 0.0)


class AutonomyDueTest(unittest.TestCase):
    """触发判定（纯函数）：到点 OR 内因顶高且过冷却。"""

    def setUp(self):
        from backend.target_daemon import autonomy_due

        self.due = autonomy_due

    def test_timer_fires(self):
        ok, why = self.due(last_tick=0.0, now=3 * 3600.0, timer_seconds=3 * 3600,
                           urge_strength=0.0)
        self.assertTrue(ok)
        self.assertEqual(why, "timer")

    def test_below_threshold_waits(self):
        ok, why = self.due(last_tick=3 * 3600.0, now=3 * 3600.0 + 60,
                           timer_seconds=3 * 3600, urge_strength=0.74)
        self.assertFalse(ok)
        self.assertEqual(why, "wait")

    def test_urge_fires_before_timer(self):
        T = 1_700_000_000.0   # 真实时间戳：冷却按秒算，别用 0 当"已过冷却"
        ok, why = self.due(last_tick=T, now=T + 600, timer_seconds=3 * 3600,
                           urge_strength=0.8, last_urge=T - 4000,
                           urge_cooldown=3600)
        self.assertTrue(ok)
        self.assertEqual(why, "urge")

    def test_urge_respects_cooldown(self):
        T = 1_700_000_000.0
        ok, why = self.due(last_tick=T, now=T + 1000, timer_seconds=3 * 3600,
                           urge_strength=0.99, last_urge=T - 900,
                           urge_cooldown=3600)
        self.assertFalse(ok)
        self.assertEqual(why, "wait")

    def test_timer_wins_over_urge_label(self):
        """同时满足时按到点记账，避免内因通道的冷却被例行 tick 反复刷新。"""
        ok, why = self.due(last_tick=0.0, now=3 * 3600.0, timer_seconds=3 * 3600,
                           urge_strength=1.0, last_urge=0.0)
        self.assertTrue(ok)
        self.assertEqual(why, "timer")


if __name__ == "__main__":
    unittest.main()
