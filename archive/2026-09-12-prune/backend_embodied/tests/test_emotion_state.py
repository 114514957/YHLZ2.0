"""
YHLZ Embodied AI V9.5.0 - 情绪状态与规则单元测试 (Emotion State & Rules)

覆盖 (emotion/emotion_state.py, emotion/emotion_rules.py):
    - 3 维状态: positivity/energy/warmth (0.0~1.0)
    - 基线 / 钳制 / 原因 / 时间戳
    - 规则表: 8 情境白名单 / 维度方向 / 可解释原因
"""
import unittest

from backend.embodied.companion.emotion import (
    EMOTION_BASELINE,
    EMOTION_CONTEXTS,
    EMOTION_DIMENSIONS,
    EMOTION_RULES,
    EmotionError,
    EmotionState,
    RulesError,
    rule_for,
)


class TestEmotionState(unittest.TestCase):
    """情绪状态"""

    def test_default_init(self):
        st = EmotionState()
        self.assertEqual(st.get("positivity"), 0.6)
        self.assertEqual(st.get("energy"), 0.5)
        self.assertEqual(st.get("warmth"), 0.6)

    def test_dimensions_whitelist(self):
        self.assertEqual(set(EMOTION_DIMENSIONS),
                         {"positivity", "energy", "warmth"})

    def test_baseline_values(self):
        self.assertEqual(EMOTION_BASELINE["positivity"], 0.6)
        self.assertEqual(EMOTION_BASELINE["energy"], 0.5)
        self.assertEqual(EMOTION_BASELINE["warmth"], 0.6)

    def test_get_invalid_dim(self):
        st = EmotionState()
        with self.assertRaises(EmotionError):
            st.get("bogus")

    def test_custom_init(self):
        st = EmotionState(positivity=0.2, energy=0.9, warmth=0.3)
        self.assertEqual(st.get("positivity"), 0.2)
        self.assertEqual(st.get("energy"), 0.9)

    def test_to_dict_structure(self):
        st = EmotionState()
        d = st.to_dict()
        for key in ("positivity", "energy", "warmth",
                    "last_reason", "timestamp"):
            self.assertIn(key, d)

    def test_to_dict_values_range(self):
        st = EmotionState()
        st.apply({"positivity": 0.5}, reason="测试")
        d = st.to_dict()
        for dim in EMOTION_DIMENSIONS:
            self.assertGreaterEqual(d[dim], 0.0)
            self.assertLessEqual(d[dim], 1.0)

    def test_apply_positive(self):
        st = EmotionState()
        st.apply({"positivity": 0.1}, reason="成功")
        self.assertAlmostEqual(st.get("positivity"), 0.7, places=4)

    def test_apply_clamp_high(self):
        st = EmotionState(positivity=0.95)
        st.apply({"positivity": 1.0}, reason="x")
        self.assertEqual(st.get("positivity"), 1.0)

    def test_apply_clamp_low(self):
        st = EmotionState(positivity=0.05)
        st.apply({"positivity": -1.0}, reason="x")
        self.assertEqual(st.get("positivity"), 0.0)

    def test_apply_invalid_dim(self):
        st = EmotionState()
        with self.assertRaises(EmotionError):
            st.apply({"bogus": 0.1}, reason="x")

    def test_apply_sets_reason(self):
        st = EmotionState()
        st.apply({"positivity": 0.1}, reason="任务成功")
        self.assertIn("任务成功", st.to_dict()["last_reason"])

    def test_set_state(self):
        st = EmotionState()
        st.set_state({"positivity": 0.9, "energy": 0.8})
        self.assertEqual(st.get("positivity"), 0.9)
        self.assertEqual(st.get("energy"), 0.8)
        self.assertEqual(st.get("warmth"), 0.6)

    def test_set_state_reason(self):
        st = EmotionState()
        st.set_state({"positivity": 0.9}, reason="快照恢复")
        self.assertIn("快照恢复", st.to_dict()["last_reason"])

    def test_baseline(self):
        st = EmotionState()
        base = st.baseline()
        self.assertEqual(base["positivity"], 0.6)

    def test_distance_from_baseline_zero(self):
        st = EmotionState()
        self.assertEqual(st.distance_from_baseline(), 0.0)

    def test_distance_from_baseline_positive(self):
        st = EmotionState(positivity=0.8)
        self.assertGreater(st.distance_from_baseline(), 0.0)

    def test_timestamp_set(self):
        st = EmotionState()
        self.assertGreater(st.to_dict()["timestamp"], 0.0)


class TestEmotionRules(unittest.TestCase):
    """情绪规则表"""

    def test_contexts_whitelist(self):
        for c in ("success", "failure", "consecutive_fail",
                  "creative_done", "creative_rejected",
                  "relationship_up", "relationship_down", "idle"):
            self.assertIn(c, EMOTION_CONTEXTS)

    def test_contexts_count(self):
        self.assertEqual(len(EMOTION_CONTEXTS), 8)

    def test_all_contexts_have_rules(self):
        for c in EMOTION_CONTEXTS:
            self.assertIn(c, EMOTION_RULES)

    def test_rule_for(self):
        r = rule_for("success")
        self.assertEqual(r["context"], "success")
        self.assertIn("positivity", r["deltas"])
        self.assertTrue(r["reason"])

    def test_success_direction(self):
        r = rule_for("success")
        self.assertGreater(r["deltas"]["positivity"], 0)
        self.assertGreater(r["deltas"]["energy"], 0)

    def test_failure_direction(self):
        r = rule_for("failure")
        self.assertLess(r["deltas"]["positivity"], 0)
        self.assertLess(r["deltas"]["energy"], 0)

    def test_relationship_up_warmth(self):
        r = rule_for("relationship_up")
        self.assertGreater(r["deltas"]["warmth"], 0)

    def test_relationship_down_warmth(self):
        r = rule_for("relationship_down")
        self.assertLess(r["deltas"]["warmth"], 0)

    def test_idle_zero(self):
        r = rule_for("idle")
        self.assertEqual(r["deltas"]["positivity"], 0.0)

    def test_consecutive_fail_limited(self):
        r = rule_for("consecutive_fail")
        # 幅度减半 (防无限跌落)
        normal = rule_for("failure")["deltas"]["positivity"]
        self.assertGreater(abs(r["deltas"]["positivity"]),
                           abs(normal) * 0.4)
        self.assertLess(abs(r["deltas"]["positivity"]),
                        abs(normal) + 1e-9)

    def test_rule_for_invalid(self):
        with self.assertRaises(RulesError):
            rule_for("bogus")

    def test_rules_reason_explainable(self):
        for c in EMOTION_CONTEXTS:
            self.assertTrue(EMOTION_RULES[c]["reason"])


if __name__ == "__main__":
    unittest.main()
