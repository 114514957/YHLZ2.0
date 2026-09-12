"""
YHLZ Embodied AI V10.1 - 记忆淘汰模块测试 (Memory Pruner)

覆盖:
    - 候选生成规则 (低价值 + 超龄 + 未确认, 严格 AND)
    - CONFIRMED 保护
    - 显式执行 / 回调
    - 停用错误帧 / 参数校验
"""
import time
import unittest

from backend.embodied.companion.memory_stabilization.pruner import (
    MemoryPruner,
    PrunerError,
)

NOW = time.time()
DAY = 86400


def _rec(rid, value=0.5, age_days=10, confirmed=False):
    return {
        "id": rid,
        "trigger": f"t_{rid}",
        "value": value,
        "timestamp": NOW - age_days * DAY,
        "lesson": "l",
    }


class TestPrunerCandidates(unittest.TestCase):
    """候选生成"""

    def setUp(self):
        self.p = MemoryPruner(value_threshold=0.3, age_days=90)

    def test_empty(self):
        r = self.p.candidates([])
        self.assertEqual(r["total"], 0)
        self.assertEqual(r["candidates"], [])

    def test_low_value_stale_unconfirmed(self):
        r = self.p.candidates([_rec("a", value=0.2, age_days=200)])
        self.assertEqual(
            [c["record_id"] for c in r["candidates"]], ["a"],
        )

    def test_high_value_stale_protected(self):
        r = self.p.candidates([_rec("a", value=0.8, age_days=200)])
        self.assertEqual(r["candidates"], [])
        self.assertEqual(r["protected"], ["a"])

    def test_low_value_fresh_protected(self):
        r = self.p.candidates([_rec("a", value=0.2, age_days=10)])
        self.assertEqual(r["candidates"], [])

    def test_low_value_stale_confirmed_protected(self):
        r = self.p.candidates(
            [_rec("a", value=0.2, age_days=200)],
            confirmed_ids=["a"],
        )
        self.assertEqual(r["candidates"], [])
        self.assertIn("a", r["protected"])

    def test_high_value_fresh_protected(self):
        r = self.p.candidates([_rec("a", value=0.8, age_days=10)])
        self.assertEqual(r["candidates"], [])
        self.assertEqual(r["protected"], ["a"])

    def test_multiple_candidates(self):
        recs = [
            _rec("a", value=0.2, age_days=200),
            _rec("b", value=0.1, age_days=300),
            _rec("c", value=0.9, age_days=100),
        ]
        r = self.p.candidates(recs)
        got = sorted(c["record_id"] for c in r["candidates"])
        self.assertEqual(got, ["a", "b"])

    def test_candidate_fields(self):
        r = self.p.candidates([_rec("a", value=0.2, age_days=200)])
        c = r["candidates"][0]
        self.assertEqual(c["record_id"], "a")
        self.assertEqual(c["value"], 0.2)
        self.assertEqual(c["age_days"], 200.0)
        self.assertFalse(c["confirmed"])
        self.assertGreaterEqual(len(c["reasons"]), 3)

    def test_reasons_explainable(self):
        r = self.p.candidates([_rec("a", value=0.2, age_days=200)])
        reasons = " ".join(r["candidates"][0]["reasons"])
        self.assertIn("低价值", reasons)
        self.assertIn("超龄", reasons)
        self.assertIn("未确认", reasons)

    def test_inject_now(self):
        r = self.p.candidates(
            [_rec("a", value=0.2, age_days=200)],
            now=NOW - 100 * DAY,
        )
        # 注入 now 使年龄变为 100 天, 仍超龄
        self.assertEqual(len(r["candidates"]), 1)

    def test_inject_now_fresh(self):
        r = self.p.candidates(
            [_rec("a", value=0.2, age_days=200)],
            now=NOW - 199 * DAY,
        )
        # 注入 now 使年龄变为 1 天 → 不超龄 → 保护
        self.assertEqual(r["candidates"], [])

    def test_bad_value_type(self):
        rec = {"id": "a", "trigger": "t", "value": "x",
               "timestamp": NOW - 200 * DAY}
        r = self.p.candidates([rec])
        # 非法 value 降级默认 0.5 → 高价值 → 保护
        self.assertEqual(r["candidates"], [])

    def test_missing_timestamp(self):
        rec = {"id": "a", "trigger": "t", "value": 0.2}
        r = self.p.candidates([rec])
        # 无时间戳 → 年龄 0 → 不超龄 → 保护
        self.assertEqual(r["candidates"], [])


class TestPrunerExecute(unittest.TestCase):
    """显式执行"""

    def setUp(self):
        self.p = MemoryPruner()

    def test_execute_removes(self):
        removed = []

        def forget(rid):
            removed.append(rid)
            return True

        r = self.p.execute(["a", "b"], forget)
        self.assertEqual(r["removed"], 2)
        self.assertEqual(r["removed_ids"], ["a", "b"])
        self.assertEqual(removed, ["a", "b"])

    def test_execute_not_found(self):
        def forget(rid):
            return False

        r = self.p.execute(["a"], forget)
        self.assertEqual(r["removed"], 0)
        self.assertEqual(r["not_found"], 1)

    def test_execute_partial(self):
        def forget(rid):
            return rid != "b"

        r = self.p.execute(["a", "b"], forget)
        self.assertEqual(r["removed"], 1)
        self.assertEqual(r["removed_ids"], ["a"])

    def test_execute_empty(self):
        def forget(rid):
            return True

        r = self.p.execute([], forget)
        self.assertEqual(r["requested"], 0)
        self.assertEqual(r["removed"], 0)

    def test_execute_with_records(self):
        recs = [_rec("a", value=0.2, age_days=200)]
        removed = []

        def forget(rid):
            removed.append(rid)
            return True

        r = self.p.execute(["a"], forget, records=recs)
        self.assertEqual(r["removed"], 1)

    def test_requested_count(self):
        def forget(rid):
            return True

        r = self.p.execute(["a", "b", "c"], forget)
        self.assertEqual(r["requested"], 3)


class TestPrunerConfig(unittest.TestCase):
    """参数校验"""

    def test_invalid_threshold_raises(self):
        with self.assertRaises(PrunerError):
            MemoryPruner(value_threshold=1.5)

    def test_negative_threshold_raises(self):
        with self.assertRaises(PrunerError):
            MemoryPruner(value_threshold=-0.1)

    def test_zero_age_raises(self):
        with self.assertRaises(PrunerError):
            MemoryPruner(age_days=0)

    def test_negative_age_raises(self):
        with self.assertRaises(PrunerError):
            MemoryPruner(age_days=-5)

    def test_custom_threshold(self):
        p = MemoryPruner(value_threshold=0.5, age_days=90)
        r = p.candidates([_rec("a", value=0.4, age_days=200)])
        self.assertEqual(len(r["candidates"]), 1)

    def test_custom_age(self):
        p = MemoryPruner(value_threshold=0.3, age_days=30)
        r = p.candidates([_rec("a", value=0.2, age_days=50)])
        self.assertEqual(len(r["candidates"]), 1)

    def test_strict_age(self):
        p = MemoryPruner(value_threshold=0.3, age_days=365)
        r = p.candidates([_rec("a", value=0.2, age_days=200)])
        self.assertEqual(r["candidates"], [])


class TestPrunerDisabled(unittest.TestCase):
    """停用"""

    def test_candidates_disabled(self):
        p = MemoryPruner(enabled=False)
        r = p.candidates([])
        self.assertEqual(r["mode"], "error_frame")
        self.assertFalse(r["ok"])

    def test_execute_disabled(self):
        p = MemoryPruner(enabled=False)
        r = p.execute(["a"], lambda rid: True)
        self.assertEqual(r["mode"], "error_frame")

    def test_stats(self):
        p = MemoryPruner()
        s = p.stats()
        self.assertEqual(s["value_threshold"], 0.3)
        self.assertEqual(s["age_days"], 90)

    def test_clear(self):
        p = MemoryPruner()
        p.candidates([_rec("a", value=0.2, age_days=200)])
        self.assertEqual(p.clear(), 1)
        self.assertEqual(p.stats()["candidate_runs"], 0)


# ── 生成式: 淘汰矩阵 ───────────────────────────────────────────
_PRUNE_CASES = [
    # (名称, value, age_days, confirmed, 期望是否候选)
    ("low_stale_unconfirmed", 0.2, 200, False, True),
    ("high_stale_unconfirmed", 0.8, 200, False, False),
    ("low_fresh_unconfirmed", 0.2, 10, False, False),
    ("low_stale_confirmed", 0.2, 200, True, False),
    ("high_fresh_unconfirmed", 0.8, 10, False, False),
    ("boundary_value", 0.3, 200, False, False),
    ("boundary_age", 0.2, 90, False, False),
    ("way_low_way_stale", 0.05, 1000, False, True),
]


class TestGeneratedPrune(unittest.TestCase):
    """生成式: 淘汰矩阵"""
    pass


for _i, (_name, _val, _age, _conf, _expect) in \
        enumerate(_PRUNE_CASES):
    def _make(name=_name, val=_val, age=_age, conf=_conf,
              expect=_expect):
        def test_case(self):
            p = MemoryPruner(value_threshold=0.3, age_days=90)
            confirmed = ["a"] if conf else []
            r = p.candidates(
                [_rec("a", value=val, age_days=age)],
                confirmed_ids=confirmed,
            )
            self.assertEqual(
                len(r["candidates"]) == 1, expect,
            )
        test_case.__name__ = f"test_prune_{name}_{_i}"
        return test_case
    setattr(TestGeneratedPrune,
            f"test_prune_{_name}_{_i}", _make())


if __name__ == "__main__":
    unittest.main()
