"""
YHLZ Embodied AI V9.5.0 - 情绪衰减与记忆单元测试 (Emotion Decay & Memory)

覆盖 (emotion/emotion_decay.py, emotion/emotion_memory.py):
    - 自然衰减公式: Current = Previous + Event Impact - Natural Decay
    - 回归基线 / 时间因子 / 防止永久高情绪
    - 情绪历史记录 {event, emotion_before, emotion_after, reason, impact}
"""
import time
import unittest

from backend.embodied.companion.emotion import (
    DecayError,
    EmotionDecay,
    EmotionMemory,
    EmotionState,
    MemoryError,
)


class TestDecayInit(unittest.TestCase):
    """衰减初始化"""

    def test_default_init(self):
        d = EmotionDecay()
        self.assertIsNotNone(d)

    def test_rate_validation_high(self):
        with self.assertRaises(DecayError):
            EmotionDecay(rate=1.5)

    def test_rate_validation_low(self):
        with self.assertRaises(DecayError):
            EmotionDecay(rate=-0.1)

    def test_window_validation(self):
        with self.assertRaises(DecayError):
            EmotionDecay(window_days=0)

    def test_stats(self):
        d = EmotionDecay()
        st = d.stats()
        self.assertEqual(st["mode"], "rule_based")
        self.assertIn("formula", st)


class TestDecay(unittest.TestCase):
    """衰减行为"""

    def test_no_elapsed_no_change(self):
        d = EmotionDecay(rate=0.05)
        st = EmotionState()
        before = st.to_dict()
        after = d.decay(st, now=time.time())
        self.assertEqual(before["positivity"], after["positivity"])

    def test_decay_toward_baseline_high(self):
        """高于基线 → 衰减下降"""
        d = EmotionDecay(rate=0.05, window_days=1)
        st = EmotionState(positivity=0.9)
        after = d.decay(st, now=time.time() + 86400)
        self.assertLess(after["positivity"], 0.9)
        self.assertGreater(after["positivity"], 0.6)

    def test_decay_toward_baseline_low(self):
        """低于基线 → 衰减回升"""
        d = EmotionDecay(rate=0.05, window_days=1)
        st = EmotionState(positivity=0.2)
        after = d.decay(st, now=time.time() + 86400)
        self.assertGreater(after["positivity"], 0.2)
        self.assertLess(after["positivity"], 0.6)

    def test_long_time_approaches_baseline(self):
        """多次衰减调用后接近基线 (长期无事件逐渐恢复)"""
        d = EmotionDecay(rate=0.5, window_days=1)
        st = EmotionState(positivity=0.95)
        now = time.time()
        for _ in range(20):
            now += 86400
            st._timestamp = now - 86400  # 模拟每日一次衰减
            d.decay(st, now=now)
        self.assertAlmostEqual(st.get("positivity"), 0.6, delta=0.01)

    def test_time_factor_cap(self):
        """时间因子 max 1.0"""
        d = EmotionDecay(rate=0.5, window_days=7)
        st = EmotionState(positivity=1.0)
        after = d.decay(st, now=time.time() + 365 * 86400)
        self.assertAlmostEqual(after["positivity"], 0.8, delta=0.02)

    def test_reason_set(self):
        d = EmotionDecay(rate=0.05, window_days=1)
        st = EmotionState(positivity=0.9)
        after = d.decay(st, now=time.time() + 86400)
        self.assertIn("衰减", after["last_reason"])

    def test_prevent_permanent_high(self):
        """多次事件后回归基线 (防永久高情绪)"""
        d = EmotionDecay(rate=0.5, window_days=1)
        st = EmotionState(positivity=1.0)
        after = d.decay(st, now=time.time() + 86400)
        self.assertLessEqual(after["positivity"], 1.0)
        self.assertGreater(after["positivity"], 0.5)


class TestEmotionMemory(unittest.TestCase):
    """情绪记忆"""

    def test_record(self):
        m = EmotionMemory()
        e = m.record(event="success",
                     before={"positivity": 0.5},
                     after={"positivity": 0.6},
                     reason="任务成功")
        self.assertTrue(e["memory_id"].startswith("em_"))
        self.assertEqual(e["event"], "success")
        self.assertEqual(e["emotion_before"]["positivity"], 0.5)

    def test_record_structure(self):
        m = EmotionMemory()
        e = m.record("failure", {"p": 1}, {"p": 2}, "原因",
                     impact={"p": -0.1})
        for key in ("memory_id", "event", "emotion_before",
                    "emotion_after", "reason", "impact", "timestamp"):
            self.assertIn(key, e)

    def test_history_latest_first(self):
        m = EmotionMemory()
        m.record("success", {"p": 1}, {"p": 2}, "first")
        m.record("success", {"p": 2}, {"p": 3}, "second")
        h = m.history()
        self.assertEqual(h[0]["reason"], "second")

    def test_history_by_event(self):
        m = EmotionMemory()
        m.record("success", {}, {}, "")
        m.record("failure", {}, {}, "")
        self.assertEqual(len(m.history(event="success")), 1)

    def test_history_limit(self):
        m = EmotionMemory()
        for i in range(5):
            m.record("success", {}, {}, f"e{i}")
        self.assertEqual(len(m.history(limit=2)), 2)

    def test_by_event(self):
        m = EmotionMemory()
        m.record("creative_done", {}, {}, "")
        self.assertEqual(len(m.by_event("creative_done")), 1)

    def test_stats(self):
        m = EmotionMemory()
        m.record("success", {}, {}, "")
        m.record("failure", {}, {}, "")
        st = m.stats()
        self.assertEqual(st["total"], 2)
        self.assertEqual(st["by_event"]["success"], 1)

    def test_max_records(self):
        m = EmotionMemory(max_records=3)
        for i in range(5):
            m.record("success", {}, {}, "")
        self.assertEqual(m.stats()["total"], 3)

    def test_max_records_validation(self):
        with self.assertRaises(MemoryError):
            EmotionMemory(max_records=0)

    def test_clear(self):
        m = EmotionMemory()
        m.record("success", {}, {}, "")
        self.assertEqual(m.clear(), 1)
        self.assertEqual(m.stats()["total"], 0)


if __name__ == "__main__":
    unittest.main()
