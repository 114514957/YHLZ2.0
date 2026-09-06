"""Style-signal rule tests (0167)."""

import unittest

from backend.target_style import detect_style_signals


class TestStyleSignals(unittest.TestCase):
    def test_casual(self):
        self.assertIn("casual", detect_style_signals("别那么严肃，说人话就行"))

    def test_concise(self):
        self.assertIn("concise", detect_style_signals("太长了，简短一点"))

    def test_detailed(self):
        self.assertIn("detailed", detect_style_signals("能不能详细点展开说"))

    def test_multiple(self):
        s = detect_style_signals("太严肃又太长，活泼点说重点")
        self.assertIn("casual", s)
        self.assertIn("concise", s)
        self.assertIn("warm", s)

    def test_normal_speech_no_signal(self):
        self.assertEqual(detect_style_signals("帮我查一下台账里麦克风的记录"), [])

    def test_empty(self):
        self.assertEqual(detect_style_signals(""), [])


class TestStyleEma(unittest.TestCase):
    def test_ema_aggregates(self):
        from backend.target_style import active_style_lines, style_ema

        items = [{"summary": f"风格偏好：老爹希望更casual{i}，语气纠偏"}
                 for i in range(3)]
        # note: real tags are casual/concise...; use captured tags directly
        items2 = [{"summary": "风格偏好：老爹希望更casual（纠偏信号）"},
                  {"summary": "风格偏好：老爹希望更casual（纠偏信号）"},
                  {"summary": "风格偏好：老爹希望更warm（纠偏信号）"}]
        t = style_ema(items2)
        self.assertGreater(t["casual"], 0)
        self.assertGreater(t["warm"], 0)
        self.assertAlmostEqual(t["poetic"], 0.0)
        lines = active_style_lines(t)
        self.assertTrue(lines)
        self.assertTrue(any("口语" in l for l in lines))

    def test_threshold_blocks_weak(self):
        from backend.target_style import active_style_lines

        self.assertEqual(active_style_lines({"casual": 0.1}), [])


if __name__ == "__main__":
    unittest.main()
