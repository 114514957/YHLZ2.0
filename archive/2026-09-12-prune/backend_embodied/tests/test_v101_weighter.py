"""
YHLZ Embodied AI V10.1 - 记忆权重评估模块测试 (Memory Weighter)

覆盖:
    - 基础价值 + 频率/确认/引用加成
    - 上限保护 (1.0)
    - 批量评估
    - 容错 / 停用错误帧
"""
import unittest

from backend.embodied.companion.memory_stabilization.weighter import (
    MemoryWeighter,
)


class TestWeighterBasic(unittest.TestCase):
    """权重评估基础"""

    def setUp(self):
        self.w = MemoryWeighter()

    def _rec(self, rid="a", value=0.5):
        return {"id": rid, "trigger": "t", "value": value}

    def test_base_only(self):
        r = self.w.evaluate(self._rec(value=0.5), {})
        self.assertEqual(r["weight"], 0.5)
        self.assertEqual(r["base_value"], 0.5)

    def test_confirmed_bonus(self):
        r = self.w.evaluate(
            self._rec(value=0.5), {"confirmed": True},
        )
        self.assertEqual(r["weight"], 0.65)
        self.assertEqual(r["confirmed_bonus"], 0.15)

    def test_referenced_bonus(self):
        r = self.w.evaluate(
            self._rec(value=0.5), {"referenced": True},
        )
        self.assertEqual(r["weight"], 0.6)

    def test_frequency_bonus(self):
        r = self.w.evaluate(
            self._rec(value=0.5), {"frequency": 3},
        )
        # 3 次 → 2 次额外 → 0.1 加成
        self.assertEqual(r["weight"], 0.6)

    def test_frequency_cap(self):
        r = self.w.evaluate(
            self._rec(value=0.5), {"frequency": 100},
        )
        self.assertEqual(r["frequency_bonus"], 0.2)
        self.assertEqual(r["weight"], 0.7)

    def test_all_bonuses(self):
        r = self.w.evaluate(
            self._rec(value=0.5),
            {"frequency": 5, "confirmed": True,
             "referenced": True},
        )
        # 0.5 + 0.2 + 0.15 + 0.1 = 0.95
        self.assertEqual(r["weight"], 0.95)

    def test_value_ceiling(self):
        r = self.w.evaluate(
            self._rec(value=0.9),
            {"frequency": 10, "confirmed": True,
             "referenced": True},
        )
        self.assertLessEqual(r["weight"], 1.0)

    def test_rule_field(self):
        r = self.w.evaluate(self._rec())
        self.assertIn("base", r["rule"])
        self.assertIn("weight", r["rule"])

    def test_reason_explainable(self):
        r = self.w.evaluate(
            self._rec(), {"confirmed": True},
        )
        self.assertIn("CONFIRMED", r["reason"])

    def test_record_id(self):
        r = self.w.evaluate(self._rec(rid="x1"))
        self.assertEqual(r["record_id"], "x1")

    def test_trigger_field(self):
        r = self.w.evaluate(self._rec())
        self.assertEqual(r["trigger"], "t")

    def test_missing_value_default(self):
        r = self.w.evaluate({"id": "a"})
        self.assertEqual(r["base_value"], 0.5)

    def test_bad_value_default(self):
        r = self.w.evaluate({"id": "a", "value": "x"})
        self.assertEqual(r["base_value"], 0.5)

    def test_none_value_default(self):
        r = self.w.evaluate({"id": "a", "value": None})
        self.assertEqual(r["base_value"], 0.5)


class TestWeighterFrequency(unittest.TestCase):
    """频率加成细则"""

    def setUp(self):
        self.w = MemoryWeighter()

    def test_freq_one_no_bonus(self):
        r = self.w.evaluate(
            {"id": "a", "value": 0.5}, {"frequency": 1},
        )
        self.assertEqual(r["frequency_bonus"], 0.0)

    def test_freq_zero_no_bonus(self):
        r = self.w.evaluate(
            {"id": "a", "value": 0.5}, {"frequency": 0},
        )
        self.assertEqual(r["frequency_bonus"], 0.0)

    def test_freq_two(self):
        r = self.w.evaluate(
            {"id": "a", "value": 0.5}, {"frequency": 2},
        )
        self.assertEqual(r["frequency_bonus"], 0.05)

    def test_freq_four(self):
        r = self.w.evaluate(
            {"id": "a", "value": 0.5}, {"frequency": 4},
        )
        self.assertEqual(r["frequency_bonus"], 0.15)

    def test_freq_negative(self):
        r = self.w.evaluate(
            {"id": "a", "value": 0.5}, {"frequency": -3},
        )
        self.assertEqual(r["frequency_bonus"], 0.0)

    def test_freq_str(self):
        r = self.w.evaluate(
            {"id": "a", "value": 0.5}, {"frequency": "3"},
        )
        self.assertEqual(r["frequency_bonus"], 0.1)


class TestWeighterMany(unittest.TestCase):
    """批量评估"""

    def setUp(self):
        self.w = MemoryWeighter()

    def test_evaluate_many(self):
        recs = [
            {"id": "a", "trigger": "t1", "value": 0.5},
            {"id": "b", "trigger": "t2", "value": 0.7},
        ]
        out = self.w.evaluate_many(recs, {})
        self.assertEqual(len(out), 2)

    def test_evaluate_many_with_context(self):
        recs = [
            {"id": "a", "trigger": "t1", "value": 0.5},
            {"id": "b", "trigger": "t2", "value": 0.5},
        ]
        out = self.w.evaluate_many(recs, {
            "a": {"confirmed": True},
        })
        self.assertEqual(out[0]["weight"], 0.65)
        self.assertEqual(out[1]["weight"], 0.5)

    def test_evaluate_many_empty(self):
        self.assertEqual(self.w.evaluate_many([]), [])

    def test_evaluate_many_unknown_context(self):
        recs = [{"id": "a", "value": 0.5}]
        out = self.w.evaluate_many(recs, {"zzz": {}})
        self.assertEqual(out[0]["weight"], 0.5)


class TestWeighterDisabled(unittest.TestCase):
    """停用与统计"""

    def test_disabled(self):
        w = MemoryWeighter(enabled=False)
        r = w.evaluate({"id": "a"})
        self.assertEqual(r["mode"], "error_frame")
        self.assertFalse(r["ok"])

    def test_stats(self):
        w = MemoryWeighter()
        s = w.stats()
        self.assertEqual(s["mode"], "rule_based")
        self.assertEqual(s["evaluate_count"], 0)

    def test_stats_after_eval(self):
        w = MemoryWeighter()
        w.evaluate({"id": "a"})
        self.assertEqual(w.stats()["evaluate_count"], 1)

    def test_clear(self):
        w = MemoryWeighter()
        w.evaluate({"id": "a"})
        w.evaluate({"id": "b"})
        self.assertEqual(w.clear(), 2)


# ── 生成式: 权重矩阵 ───────────────────────────────────────────
_WEIGHT_CASES = [
    # (名称, 基础值, frequency, confirmed, referenced, 期望权重)
    ("base_only", 0.5, 1, False, False, 0.5),
    ("confirmed", 0.5, 1, True, False, 0.65),
    ("referenced", 0.5, 1, False, True, 0.6),
    ("freq_3", 0.5, 3, False, False, 0.6),
    ("freq_cap", 0.5, 50, False, False, 0.7),
    ("all_high", 0.5, 6, True, True, 0.95),
    ("zero_base", 0.0, 1, False, False, 0.0),
    ("max_base", 1.0, 1, False, False, 1.0),
    ("max_base_all", 1.0, 10, True, True, 1.0),
]


class TestGeneratedWeights(unittest.TestCase):
    """生成式: 权重矩阵"""
    pass


for _i, (_name, _base, _freq, _conf, _ref, _exp) in \
        enumerate(_WEIGHT_CASES):
    def _make(name=_name, base=_base, freq=_freq, conf=_conf,
              ref=_ref, exp=_exp):
        def test_case(self):
            w = MemoryWeighter()
            r = w.evaluate(
                {"id": "a", "value": base},
                {"frequency": freq, "confirmed": conf,
                 "referenced": ref},
            )
            self.assertEqual(r["weight"], exp)
        test_case.__name__ = f"test_weight_{name}_{_i}"
        return test_case
    setattr(TestGeneratedWeights,
            f"test_weight_{_name}_{_i}", _make())


if __name__ == "__main__":
    unittest.main()
