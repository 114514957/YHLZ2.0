"""
YHLZ Embodied AI V5.6 - 人格稳定系统单元测试 (Personality Decay)

覆盖 (personality_decay.py):
    - PersonalityDecayPolicy: 时间衰减 → 基础值平滑回归
    - 衰减公式: offset × rate × elapsed_days (上限 = 偏移量)
    - 平滑变化: 不突变 (短时间几乎不变)
    - stability: 当前/基础/偏移量/回归次数/稳定判断
    - 参数校验: rate < 0 → DecayError
    - 开关: enabled
"""
import time
import unittest

from backend.embodied.companion import (
    BASE_DIMENSIONS,
    DecayError,
    PersonalityDecayPolicy,
)


class TestDecayApply(unittest.TestCase):
    """衰减应用"""

    def setUp(self):
        self.decay = PersonalityDecayPolicy(rate=0.05)
        # 初始化 last_decay (首次 apply 视为无历史)
        self.base_dims = dict(BASE_DIMENSIONS)
        self.decay.apply(self.base_dims, now=time.time())

    def test_no_elapsed_no_decay(self):
        """无时间流逝 → 不变"""
        dims = {"warmth": 0.9, "patience": 0.7,
                "humor": 0.6, "serious": 0.4}
        now = time.time()
        self.decay.apply(dims, now=now)  # 初始化
        r = self.decay.apply(dims, now=now)
        self.assertEqual(r["dimensions"]["warmth"], 0.9)
        self.assertFalse(r["applied"])

    def test_decay_toward_base(self):
        """长时间 → 向基础值回归"""
        dims = {"warmth": 1.0, "patience": 0.7,
                "humor": 0.6, "serious": 0.4}
        now = time.time()
        self.decay.apply(dims, now=now)  # 初始化 last
        # 10 天: 偏移 0.2 × 0.05 × 10 = 0.1 → 0.9
        r = self.decay.apply(dims, now=now + 10 * 86400)
        self.assertAlmostEqual(r["dimensions"]["warmth"], 0.9, places=2)

    def test_decay_full_regression(self):
        """足够长时间 → 完全回归基础值"""
        dims = {"warmth": 0.9, "patience": 0.7,
                "humor": 0.6, "serious": 0.4}
        now = time.time()
        self.decay.apply(dims, now=now)  # 初始化 last
        # 100 天: 偏移 0.1 × 0.05 × 100 = 0.5 > 0.1 → 完全回归 0.8
        r = self.decay.apply(dims, now=now + 100 * 86400)
        self.assertEqual(r["dimensions"]["warmth"], 0.8)

    def test_decay_smooth(self):
        """平滑: 短时间小变化 (不突变)"""
        dims = {"warmth": 0.9, "patience": 0.7,
                "humor": 0.6, "serious": 0.4}
        now = time.time()
        self.decay.apply(dims, now=now)  # 初始化 last
        r = self.decay.apply(dims, now=now + 1 * 86400)  # 1 天
        self.assertLess(r["dimensions"]["warmth"], 0.9)
        self.assertGreater(r["dimensions"]["warmth"], 0.85)

    def test_decay_returns_reasons(self):
        """衰减原因可解释"""
        dims = {"warmth": 0.9, "patience": 0.7,
                "humor": 0.6, "serious": 0.4}
        now = time.time()
        self.decay.apply(dims, now=now)  # 初始化 last
        r = self.decay.apply(dims, now=now + 10 * 86400)
        self.assertTrue(r["reasons"])
        self.assertIn("回归", r["reasons"][0])

    def test_decay_disabled(self):
        """停用不衰减"""
        decay = PersonalityDecayPolicy(rate=0.05, enabled=False)
        dims = {"warmth": 1.0, "patience": 0.7,
                "humor": 0.6, "serious": 0.4}
        r = decay.apply(dims, now=time.time() + 100 * 86400)
        self.assertFalse(r["applied"])
        self.assertEqual(r["dimensions"]["warmth"], 1.0)

    def test_decay_no_mutate(self):
        """不修改原对象"""
        dims = {"warmth": 1.0, "patience": 0.7,
                "humor": 0.6, "serious": 0.4}
        self.decay.apply(dims, now=time.time())  # 初始化
        self.decay.apply(dims, now=time.time() + 100 * 86400)
        self.assertEqual(dims["warmth"], 1.0)


class TestStability(unittest.TestCase):
    """稳定状态"""

    def setUp(self):
        self.decay = PersonalityDecayPolicy(rate=0.05)

    def test_stability_structure(self):
        """稳定状态结构"""
        st = self.decay.stability(dict(BASE_DIMENSIONS))
        for key in ("mode", "enabled", "decay_rate", "base",
                    "current", "total_offset", "per_dimension",
                    "stable"):
            self.assertIn(key, st)

    def test_stable_at_base(self):
        """基础值 → 稳定"""
        st = self.decay.stability(dict(BASE_DIMENSIONS))
        self.assertTrue(st["stable"])
        self.assertEqual(st["total_offset"], 0.0)

    def test_unstable_when_offset(self):
        """有偏移 → 不稳定"""
        dims = dict(BASE_DIMENSIONS)
        dims["warmth"] = 1.0
        st = self.decay.stability(dims)
        self.assertFalse(st["stable"])
        self.assertGreater(st["total_offset"], 0)

    def test_per_dimension_fields(self):
        """每维度字段"""
        st = self.decay.stability(dict(BASE_DIMENSIONS))
        entry = st["per_dimension"][0]
        for key in ("dimension", "base_value", "current_value", "offset"):
            self.assertIn(key, entry)

    def test_offset_calc(self):
        """偏移量计算"""
        dims = dict(BASE_DIMENSIONS)
        dims["warmth"] = 0.9
        st = self.decay.stability(dims)
        self.assertAlmostEqual(st["total_offset"], 0.1)

    def test_rate_exposed(self):
        """衰减率暴露"""
        st = self.decay.stability(dict(BASE_DIMENSIONS))
        self.assertEqual(st["decay_rate"], 0.05)


class TestValidation(unittest.TestCase):
    """参数校验"""

    def setUp(self):
        self.decay = PersonalityDecayPolicy(rate=0.05)

    def test_invalid_rate(self):
        """rate < 0 → DecayError"""
        with self.assertRaises(DecayError):
            PersonalityDecayPolicy(rate=-0.1)

    def test_zero_rate_ok(self):
        """rate=0 允许 (无衰减)"""
        decay = PersonalityDecayPolicy(rate=0.0)
        dims = {"warmth": 1.0, "patience": 0.7,
                "humor": 0.6, "serious": 0.4}
        r = decay.apply(dims, now=time.time() + 100 * 86400)
        self.assertEqual(r["dimensions"]["warmth"], 1.0)

    def test_rate_property(self):
        """rate 属性"""
        self.assertEqual(self.decay.rate, 0.05)

    def test_enabled_property(self):
        """enabled 属性"""
        self.assertTrue(self.decay.enabled)
        self.decay.set_enabled(False)
        self.assertFalse(self.decay.enabled)

    def test_reset(self):
        """重置 (后续衰减从头算)"""
        self.decay.reset()
        dims = dict(BASE_DIMENSIONS)
        dims["warmth"] = 0.9
        r = self.decay.apply(dims, now=time.time())
        self.assertEqual(r["dimensions"]["warmth"], 0.9)


if __name__ == "__main__":
    unittest.main()
