"""
YHLZ Embodied AI V7.0 - 存在表达状态单元测试 (Presence State)

覆盖:
    - 状态定义 (表情/姿态/强度/互动模式)
    - 更新/钳制/校验
    - 快照恢复/重置
"""
import unittest

from backend.embodied.companion.embodied_presence import (
    DEFAULT_PRESENCE,
    EXPRESSIONS,
    INTERACTION_MODES,
    POSTURES,
    PresenceState,
    PresenceStateError,
)


class TestPresenceState(unittest.TestCase):
    """表达状态"""

    def setUp(self):
        self.state = PresenceState()

    def test_default_state(self):
        s = self.state.to_dict()
        self.assertEqual(s["expression"], "平静")
        self.assertEqual(s["posture"], "待机")
        self.assertEqual(s["intensity"], 0.3)
        self.assertEqual(s["interaction_mode"], "neutral")
        self.assertIn("timestamp", s)
        self.assertIn("last_reason", s)

    def test_update_expression(self):
        self.state.update(expression="高兴",
                          reason="任务成功")
        self.assertEqual(self.state.get("expression"), "高兴")

    def test_update_posture(self):
        self.state.update(posture="聆听")
        self.assertEqual(self.state.get("posture"), "聆听")

    def test_update_intensity(self):
        self.state.update(intensity=0.8)
        self.assertEqual(self.state.get("intensity"), 0.8)

    def test_update_mode(self):
        self.state.update(interaction_mode="supportive")
        self.assertEqual(self.state.get("interaction_mode"),
                         "supportive")

    def test_partial_update_keeps_others(self):
        before = self.state.to_dict()
        self.state.update(expression="思考")
        after = self.state.to_dict()
        self.assertEqual(after["posture"], before["posture"])
        self.assertEqual(after["intensity"],
                         before["intensity"])

    def test_intensity_clamp_high(self):
        self.state.update(intensity=2.0)
        self.assertEqual(self.state.get("intensity"), 1.0)

    def test_intensity_clamp_low(self):
        self.state.update(intensity=-1.0)
        self.assertEqual(self.state.get("intensity"), 0.0)

    def test_intensity_floor(self):
        state = PresenceState(floor=0.2)
        state.update(intensity=0.05)
        self.assertEqual(state.get("intensity"), 0.2)

    def test_invalid_expression(self):
        with self.assertRaises(PresenceStateError):
            self.state.update(expression="愤怒")

    def test_invalid_posture(self):
        with self.assertRaises(PresenceStateError):
            self.state.update(posture="跳舞")

    def test_invalid_mode(self):
        with self.assertRaises(PresenceStateError):
            self.state.update(interaction_mode="aggressive")

    def test_invalid_intensity_type(self):
        with self.assertRaises(PresenceStateError):
            self.state.update(intensity="high")

    def test_invalid_expression_constructor(self):
        with self.assertRaises(PresenceStateError):
            PresenceState(expression="愤怒")

    def test_last_reason_recorded(self):
        self.state.update(expression="高兴",
                          reason="创造完成")
        self.assertEqual(self.state.to_dict()["last_reason"],
                         "创造完成")

    def test_timestamp_updated(self):
        t1 = self.state.to_dict()["timestamp"]
        self.state.update(expression="高兴")
        t2 = self.state.to_dict()["timestamp"]
        self.assertGreaterEqual(t2, t1)

    def test_baseline(self):
        b = self.state.baseline()
        self.assertEqual(b, DEFAULT_PRESENCE)

    def test_restore(self):
        self.state.update(expression="思考", posture="专注",
                          intensity=0.9,
                          interaction_mode="focused")
        restored = self.state.restore(
            {"expression": "平静", "posture": "待机",
             "intensity": 0.3, "interaction_mode": "neutral"},
        )
        self.assertEqual(restored["expression"], "平静")
        self.assertEqual(restored["intensity"], 0.3)

    def test_restore_reason(self):
        self.state.restore(DEFAULT_PRESENCE, reason="快照恢复")
        self.assertEqual(self.state.to_dict()["last_reason"],
                         "快照恢复")

    def test_reset(self):
        self.state.update(expression="高兴", intensity=0.9)
        r = self.state.reset()
        self.assertEqual(r["expression"], "平静")
        self.assertEqual(r["intensity"], 0.3)

    def test_constants_expressions(self):
        self.assertEqual(EXPRESSIONS,
                         ["平静", "高兴", "关切", "思考", "疲惫"])

    def test_constants_postures(self):
        self.assertEqual(POSTURES,
                         ["待机", "聆听", "回应", "专注"])

    def test_constants_modes(self):
        self.assertEqual(INTERACTION_MODES,
                         ["neutral", "supportive", "playful",
                          "focused"])

    def test_state_dict_keys(self):
        s = self.state.to_dict()
        for key in ("expression", "posture", "intensity",
                    "interaction_mode", "timestamp",
                    "last_reason"):
            self.assertIn(key, s)


if __name__ == "__main__":
    unittest.main()
