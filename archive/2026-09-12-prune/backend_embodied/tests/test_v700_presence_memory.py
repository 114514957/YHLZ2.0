"""
YHLZ Embodied AI V7.0 - 存在连续性记忆单元测试 (Presence Memory)

覆盖:
    - 记录/统计
    - 连续性分析 (节奏/偏好)
    - 上限/清空
"""
import time
import unittest

from backend.embodied.companion.embodied_presence import (
    PresenceMemory,
    PresenceMemoryError,
)


class TestPresenceMemory(unittest.TestCase):
    """存在连续性记忆"""

    def setUp(self):
        self.memory = PresenceMemory()

    def test_record_structure(self):
        entry = self.memory.record(
            context="success", expression="高兴",
            interaction_mode="playful", intensity=0.7,
        )
        for key in ("memory_id", "time", "context",
                    "expression", "interaction_mode",
                    "intensity"):
            self.assertIn(key, entry)
        self.assertTrue(entry["memory_id"].startswith("pm_"))

    def test_record_count(self):
        self.memory.record(context="success",
                           interaction_mode="playful")
        self.memory.record(context="failure",
                           interaction_mode="supportive")
        self.assertEqual(self.memory.stats()["record_count"], 2)

    def test_mode_distribution(self):
        self.memory.record(context="success",
                           interaction_mode="playful")
        self.memory.record(context="success",
                           interaction_mode="playful")
        self.memory.record(context="failure",
                           interaction_mode="supportive")
        stats = self.memory.stats()
        self.assertEqual(stats["mode_distribution"][
            "playful"], 2)
        self.assertEqual(stats["mode_distribution"][
            "supportive"], 1)

    def test_expression_distribution(self):
        self.memory.record(expression="高兴")
        self.memory.record(expression="高兴")
        self.memory.record(expression="关切")
        stats = self.memory.stats()
        self.assertEqual(stats["expression_distribution"][
            "高兴"], 2)

    def test_context_distribution(self):
        self.memory.record(context="success")
        self.memory.record(context="failure")
        stats = self.memory.stats()
        self.assertEqual(stats["context_distribution"][
            "success"], 1)

    def test_history_order(self):
        self.memory.record(context="first")
        self.memory.record(context="second")
        history = self.memory.history()
        self.assertEqual(history[0]["context"], "second")

    def test_history_limit(self):
        for i in range(10):
            self.memory.record(context=f"t{i}")
        self.assertEqual(len(self.memory.history(limit=3)), 3)

    def test_continuity_empty(self):
        c = self.memory.continuity()
        self.assertEqual(c["total"], 0)
        self.assertEqual(c["rhythm_stability"], 1.0)
        self.assertEqual(c["preferred_mode"], "neutral")

    def test_continuity_preferred_mode(self):
        self.memory.record(context="a",
                           interaction_mode="playful")
        self.memory.record(context="b",
                           interaction_mode="playful")
        c = self.memory.continuity()
        self.assertEqual(c["preferred_mode"], "playful")

    def test_continuity_preferred_expression(self):
        self.memory.record(expression="高兴")
        self.memory.record(expression="高兴")
        self.memory.record(expression="关切")
        c = self.memory.continuity()
        self.assertEqual(c["preferred_expression"], "高兴")

    def test_continuity_window_filter(self):
        now = time.time()
        self.memory.record(context="old",
                           now=now - 40 * 86400)
        self.memory.record(context="new", now=now)
        c = self.memory.continuity(window_days=30, now=now)
        self.assertEqual(c["total"], 1)

    def test_continuity_daily_avg(self):
        now = time.time()
        for i in range(30):
            self.memory.record(context=f"t{i}", now=now)
        c = self.memory.continuity(window_days=30, now=now)
        self.assertAlmostEqual(c["daily_avg"], 1.0, places=3)

    def test_continuity_reason(self):
        self.memory.record(context="a",
                           interaction_mode="supportive")
        c = self.memory.continuity()
        self.assertIn("supportive", c["reason"])

    def test_rhythm_stability_with_gaps(self):
        now = time.time()
        self.memory.record(context="a", now=now)
        self.memory.record(context="b", now=now + 3600)
        self.memory.record(context="c", now=now + 7200)
        c = self.memory.continuity(window_days=30, now=now)
        self.assertGreaterEqual(c["rhythm_stability"], 0.0)
        self.assertLessEqual(c["rhythm_stability"], 1.0)

    def test_max_records_cap(self):
        memory = PresenceMemory(max_records=5)
        for i in range(20):
            memory.record(context=f"t{i}")
        self.assertEqual(memory.stats()["record_count"], 5)

    def test_invalid_max_records(self):
        with self.assertRaises(PresenceMemoryError):
            PresenceMemory(max_records=0)

    def test_clear(self):
        self.memory.record(context="a")
        n = self.memory.clear()
        self.assertEqual(n, 1)
        self.assertEqual(self.memory.stats()["record_count"], 0)
        self.assertEqual(self.memory.stats()[
            "mode_distribution"], {})

    def test_mode(self):
        self.assertEqual(self.memory.stats()["mode"],
                         "rule_based")


if __name__ == "__main__":
    unittest.main()
