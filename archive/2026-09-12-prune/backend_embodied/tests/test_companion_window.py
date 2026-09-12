"""
YHLZ Embodied AI V5.6 - 时间窗口统计单元测试 (Interaction Window)

覆盖 (interaction_window.py):
    - 窗口统计: recent_success_rate / failure_rate / interaction_count
    - 7 天 / 30 天窗口
    - 只存统计数字 (禁止保存聊天)
    - 窗口过滤 (旧记录不计入)
    - 参数校验: days <= 0 / max_records <= 0
"""
import time
import unittest

from backend.embodied.companion import (
    DEFAULT_WINDOW_DAYS,
    InteractionWindow,
    WindowError,
)


class TestWindowRecord(unittest.TestCase):
    """记录"""

    def setUp(self):
        self.window = InteractionWindow()

    def test_record_success(self):
        """记录成功"""
        r = self.window.record(success=True)
        self.assertTrue(r["recorded"])
        self.assertTrue(r["success"])
        self.assertEqual(self.window.count, 1)

    def test_record_failure(self):
        """记录失败"""
        self.window.record(success=False)
        self.assertEqual(self.window.count, 1)

    def test_record_timestamp(self):
        """自定义时间戳"""
        self.window.record(success=True, timestamp=100.0)
        st = self.window.stats(now=200.0)
        self.assertEqual(st["recent_interaction_count"], 1)

    def test_clear(self):
        """清空"""
        self.window.record(success=True)
        self.assertEqual(self.window.clear(), 1)
        self.assertEqual(self.window.count, 0)

    def test_max_records(self):
        """记录上限"""
        window = InteractionWindow(max_records=3)
        for _ in range(5):
            window.record(success=True)
        self.assertEqual(window.count, 3)


class TestWindowStats(unittest.TestCase):
    """窗口统计"""

    def setUp(self):
        self.window = InteractionWindow()

    def test_stats_structure(self):
        """统计结构"""
        self.window.record(success=True)
        st = self.window.stats(days=7)
        for key in ("window_days", "recent_interaction_count",
                    "recent_success_count", "recent_failure_count",
                    "recent_success_rate", "recent_failure_rate",
                    "mode"):
            self.assertIn(key, st)
        self.assertEqual(st["mode"], "rule_based")

    def test_success_rate(self):
        """成功率"""
        self.window.record(success=True)
        self.window.record(success=True)
        self.window.record(success=False)
        st = self.window.stats(days=7)
        self.assertEqual(st["recent_interaction_count"], 3)
        self.assertEqual(st["recent_success_count"], 2)
        self.assertEqual(st["recent_failure_count"], 1)
        self.assertAlmostEqual(st["recent_success_rate"], 0.6667, places=2)

    def test_failure_rate(self):
        """失败率"""
        self.window.record(success=False)
        self.window.record(success=False)
        st = self.window.stats(days=7)
        self.assertEqual(st["recent_failure_rate"], 1.0)

    def test_empty_stats(self):
        """空统计"""
        st = self.window.stats(days=7)
        self.assertEqual(st["recent_interaction_count"], 0)
        self.assertEqual(st["recent_success_rate"], 0.0)

    def test_window_7_days(self):
        """7 天窗口"""
        now = time.time()
        self.window.record(success=True, timestamp=now - 3 * 86400)  # 3 天前
        self.window.record(success=True, timestamp=now - 10 * 86400)  # 10 天前
        st = self.window.stats(days=7, now=now)
        self.assertEqual(st["recent_interaction_count"], 1)

    def test_window_30_days(self):
        """30 天窗口"""
        now = time.time()
        self.window.record(success=True, timestamp=now - 3 * 86400)
        self.window.record(success=True, timestamp=now - 10 * 86400)
        self.window.record(success=False, timestamp=now - 40 * 86400)
        st = self.window.stats(days=30, now=now)
        self.assertEqual(st["recent_interaction_count"], 2)

    def test_default_window(self):
        """默认窗口 30 天"""
        self.assertEqual(DEFAULT_WINDOW_DAYS, 30)
        self.window.record(success=True)
        st = self.window.stats()
        self.assertEqual(st["window_days"], 30)

    def test_stats_only_numbers(self):
        """统计只含数字"""
        self.window.record(success=True)
        st = self.window.stats(days=7)
        self.assertTrue(all(isinstance(v, (int, float))
                            for k, v in st.items()
                            if k != "mode"))


class TestValidation(unittest.TestCase):
    """参数校验"""

    def setUp(self):
        self.window = InteractionWindow()

    def test_invalid_days(self):
        """days <= 0 → WindowError"""
        with self.assertRaises(WindowError):
            self.window.stats(days=0)

    def test_invalid_max_records(self):
        """max_records <= 0 → WindowError"""
        with self.assertRaises(WindowError):
            InteractionWindow(max_records=0)

    def test_window_specific_days(self):
        """任意窗口天数"""
        self.window.record(success=True)
        st = self.window.stats(days=1)
        self.assertEqual(st["window_days"], 1)


if __name__ == "__main__":
    unittest.main()
