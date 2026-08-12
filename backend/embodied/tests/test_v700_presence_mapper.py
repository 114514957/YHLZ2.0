"""
YHLZ Embodied AI V7.0 - 存在表达映射器单元测试 (Presence Mapper)

覆盖:
    - 上下文 → 表达映射
    - 情绪维度调整
    - 人格维度调整
    - 强度钳制/置信度
"""
import unittest

from backend.embodied.companion.embodied_presence import (
    CONTEXT_EXPRESSIONS,
    PresenceMapper,
)


def emotion(positivity=0.5, energy=0.5, warmth=0.5):
    return {
        "positivity": positivity,
        "energy": energy,
        "warmth": warmth,
    }


def personality(humor=0.3, patience=0.5):
    return {"humor": humor, "patience": patience}


class TestContextMapping(unittest.TestCase):
    """上下文映射"""

    def setUp(self):
        self.mapper = PresenceMapper()

    def test_success_mapping(self):
        r = self.mapper.map(emotion(), None, "success")
        self.assertEqual(r["expression"], "高兴")
        self.assertEqual(r["posture"], "回应")
        self.assertEqual(r["interaction_mode"], "playful")
        self.assertGreaterEqual(r["intensity"], 0.6)

    def test_failure_mapping(self):
        r = self.mapper.map(emotion(), None, "failure")
        self.assertEqual(r["expression"], "关切")
        self.assertEqual(r["posture"], "聆听")
        self.assertEqual(r["interaction_mode"], "supportive")

    def test_creative_done_mapping(self):
        r = self.mapper.map(emotion(), None, "creative_done")
        self.assertEqual(r["expression"], "高兴")
        self.assertEqual(r["interaction_mode"], "playful")

    def test_creative_rejected_mapping(self):
        r = self.mapper.map(emotion(), None,
                            "creative_rejected")
        self.assertEqual(r["expression"], "关切")
        self.assertEqual(r["interaction_mode"], "supportive")

    def test_relationship_up_mapping(self):
        r = self.mapper.map(emotion(), None, "relationship_up")
        self.assertEqual(r["expression"], "高兴")

    def test_deep_task_mapping(self):
        r = self.mapper.map(emotion(), None, "deep_task")
        self.assertEqual(r["expression"], "思考")
        self.assertEqual(r["posture"], "专注")
        self.assertEqual(r["interaction_mode"], "focused")

    def test_idle_mapping(self):
        r = self.mapper.map(emotion(), None, "idle")
        self.assertEqual(r["expression"], "平静")
        self.assertEqual(r["posture"], "待机")
        self.assertEqual(r["interaction_mode"], "neutral")

    def test_unknown_context_default_idle(self):
        r = self.mapper.map(emotion(), None, "bogus")
        self.assertEqual(r["expression"], "平静")

    def test_context_reason(self):
        r = self.mapper.map(emotion(), None, "success")
        self.assertIn("任务成功", r["reason"])

    def test_contexts_constant(self):
        self.assertIn("success", CONTEXT_EXPRESSIONS)
        self.assertIn("failure", CONTEXT_EXPRESSIONS)
        self.assertIn("deep_task", CONTEXT_EXPRESSIONS)


class TestEmotionAdjustment(unittest.TestCase):
    """情绪维度调整"""

    def setUp(self):
        self.mapper = PresenceMapper()

    def test_high_positivity_idle_happy(self):
        r = self.mapper.map(emotion(positivity=0.8), None,
                            "idle")
        self.assertEqual(r["expression"], "高兴")

    def test_low_positivity_idle_care(self):
        r = self.mapper.map(emotion(positivity=0.2), None,
                            "idle")
        self.assertEqual(r["expression"], "关切")
        self.assertEqual(r["interaction_mode"], "supportive")

    def test_high_energy_focus(self):
        r = self.mapper.map(emotion(energy=0.8), None, "idle")
        self.assertEqual(r["posture"], "专注")

    def test_high_warmth_supportive(self):
        r = self.mapper.map(emotion(warmth=0.8), None, "idle")
        self.assertEqual(r["interaction_mode"], "supportive")

    def test_high_warmth_keeps_focused(self):
        r = self.mapper.map(emotion(warmth=0.8), None,
                            "deep_task")
        self.assertEqual(r["interaction_mode"], "focused")

    def test_invalid_emotion_values_tolerated(self):
        r = self.mapper.map(
            {"positivity": "high", "energy": None,
             "warmth": "x"},
            None, "idle",
        )
        self.assertEqual(r["expression"], "平静")

    def test_none_emotion(self):
        r = self.mapper.map(None, None, "idle")
        self.assertIn("expression", r)

    def test_positive_success_keeps_context(self):
        # 上下文优先: success 恒为高兴
        r = self.mapper.map(emotion(positivity=0.1), None,
                            "success")
        self.assertEqual(r["expression"], "高兴")


class TestPersonalityAdjustment(unittest.TestCase):
    """人格维度调整"""

    def setUp(self):
        self.mapper = PresenceMapper()

    def test_high_humor_playful(self):
        r = self.mapper.map(emotion(),
                            personality(humor=0.8), "idle")
        self.assertEqual(r["expression"], "高兴")
        self.assertEqual(r["interaction_mode"], "playful")

    def test_low_humor_neutral(self):
        r = self.mapper.map(emotion(),
                            personality(humor=0.2), "idle")
        self.assertEqual(r["expression"], "平静")

    def test_high_humor_increases_intensity(self):
        r1 = self.mapper.map(emotion(), personality(humor=0.1),
                             "idle")
        r2 = self.mapper.map(emotion(), personality(humor=0.8),
                             "idle")
        self.assertGreaterEqual(r2["intensity"], r1["intensity"])

    def test_invalid_personality_tolerated(self):
        r = self.mapper.map(emotion(), {"humor": "high"},
                            "idle")
        self.assertIn("expression", r)

    def test_none_personality(self):
        r = self.mapper.map(emotion(), None, "idle")
        self.assertIn("expression", r)


class TestOutputBoundary(unittest.TestCase):
    """输出边界"""

    def setUp(self):
        self.mapper = PresenceMapper()

    def test_intensity_range(self):
        for ctx in ("success", "failure", "idle", "deep_task"):
            r = self.mapper.map(emotion(), None, ctx)
            self.assertGreaterEqual(r["intensity"], 0.0)
            self.assertLessEqual(r["intensity"], 1.0)

    def test_confidence_range(self):
        r = self.mapper.map(emotion(), None, "idle")
        self.assertGreaterEqual(r["confidence"], 0.0)
        self.assertLessEqual(r["confidence"], 1.0)

    def test_output_structure(self):
        r = self.mapper.map(emotion(), None, "idle")
        for key in ("expression", "posture", "intensity",
                    "interaction_mode", "reason", "confidence",
                    "mode"):
            self.assertIn(key, r)
        self.assertEqual(r["mode"], "rule_based")

    def test_high_confidence(self):
        r = self.mapper.map(
            emotion(positivity=1.0, energy=1.0), None, "idle",
        )
        self.assertGreaterEqual(r["confidence"], 0.8)

    def test_disabled(self):
        mapper = PresenceMapper(enabled=False)
        r = mapper.map(emotion(), None, "success")
        self.assertEqual(r["expression"], "平静")
        self.assertIn("停用", r["reason"])

    def test_stats(self):
        self.mapper.map(emotion(), None, "idle")
        self.mapper.map(emotion(), None, "success")
        self.assertEqual(self.mapper.stats()["map_count"], 2)

    def test_clear(self):
        self.mapper.map(emotion(), None, "idle")
        self.mapper.clear()
        self.assertEqual(self.mapper.stats()["map_count"], 0)


if __name__ == "__main__":
    unittest.main()
