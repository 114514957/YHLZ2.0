"""F5 notify dedupe/rate-limit tests (ledger 0436)."""
import tempfile
import unittest
from pathlib import Path

from backend import notify_guard as ng


class NotifyGuardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def _allow(self, kind, text, now, cooldown=3600, max_per_day=4):
        return ng.allow(kind, text, cooldown=cooldown, max_per_day=max_per_day,
                        now=now, state_file=self.tmp / "g.json")

    def test_duplicate_within_cooldown_blocked(self):
        t = 1_700_000_000.0
        self.assertTrue(self._allow("task", "完成：导出 QQ", t))
        self.assertFalse(self._allow("task", "完成：导出 QQ", t + 60))
        # whitespace-normalized near-duplicates count as the same notice
        self.assertFalse(self._allow("task", "完成： 导出　QQ", t + 60))
        self.assertTrue(self._allow("task", "另一件事", t + 61))

    def test_cooldown_expiry(self):
        t = 1_700_000_000.0
        self.assertTrue(self._allow("task", "X", t))
        self.assertFalse(self._allow("task", "X", t + 3599))
        self.assertTrue(self._allow("task", "X", t + 3601))

    def test_daily_cap(self):
        t = 1_700_000_000.0
        for i in range(3):
            self.assertTrue(self._allow("autonomy", f"想法{i}", t + i))
        self.assertFalse(self._allow("autonomy", "第四", t + 4, max_per_day=3))
        self.assertTrue(self._allow("autonomy", "明天", t + 86400))

    def test_fail_open_on_bad_state_path(self):
        # a directory as state path -> writing fails -> allow (fail open)
        self.assertTrue(ng.allow("x", "y", now=1.0, state_file=self.tmp))


if __name__ == "__main__":
    unittest.main()
