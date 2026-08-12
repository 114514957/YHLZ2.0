"""
YHLZ Embodied AI V10.1 - 记忆稳定化生成式测试 2 (V10.1 Extra2)

覆盖 (生成式):
    - 冲突检测多组合矩阵
    - 引擎报告字段矩阵
    - 淘汰边界矩阵
"""
import time
import unittest

from backend.embodied.companion.memory_stabilization import (
    MemoryStabilizationEngine,
)
from backend.embodied.companion.memory_stabilization.conflict_detector import (
    MemoryConflictDetector,
)
from backend.embodied.companion.memory_stabilization.pruner import (
    MemoryPruner,
)

NOW = time.time()
DAY = 86400


def _rec(rid, trigger="t", lesson="普通", value=0.5,
         age_days=10, conf=0.5):
    return {
        "id": rid, "trigger": trigger, "lesson": lesson,
        "value": value, "confidence": conf,
        "timestamp": NOW - age_days * DAY,
    }


# ── 生成式: 冲突多组合矩阵 ─────────────────────────────────────
_CONFLICT2_CASES = [
    # (名称, 记录列表, 期望冲突组数)
    ("pair_conflict", [
        {"id": "a", "trigger": "t", "lesson": "成功"},
        {"id": "b", "trigger": "t", "lesson": "失败"},
    ], 1),
    ("no_conflict_same", [
        {"id": "a", "trigger": "t", "lesson": "成功"},
        {"id": "b", "trigger": "t", "lesson": "顺利"},
    ], 0),
    ("diff_trigger", [
        {"id": "a", "trigger": "t1", "lesson": "成功"},
        {"id": "b", "trigger": "t2", "lesson": "失败"},
    ], 0),
    ("two_groups", [
        {"id": "a", "trigger": "t1", "lesson": "成功"},
        {"id": "b", "trigger": "t1", "lesson": "失败"},
        {"id": "c", "trigger": "t2", "lesson": "有效"},
        {"id": "d", "trigger": "t2", "lesson": "无效"},
    ], 2),
    ("triple_conflict", [
        {"id": "a", "trigger": "t", "lesson": "成功"},
        {"id": "b", "trigger": "t", "lesson": "失败"},
        {"id": "c", "trigger": "t", "lesson": "失败"},
    ], 1),
    ("mixed_stance_single", [
        {"id": "a", "trigger": "t", "lesson": "成功"},
        {"id": "b", "trigger": "t", "lesson": "日常"},
    ], 0),
    ("empty", [], 0),
    ("single_pos", [
        {"id": "a", "trigger": "t", "lesson": "成功"},
    ], 0),
]


class TestGeneratedConflict2(unittest.TestCase):
    """生成式: 冲突多组合"""
    pass


for _i, (_name, _recs, _exp) in enumerate(_CONFLICT2_CASES):
    def _make(name=_name, recs=_recs, exp=_exp):
        def test_case(self):
            d = MemoryConflictDetector()
            r = d.detect(recs)
            self.assertEqual(len(r["conflicts"]), exp)
        test_case.__name__ = f"test_conflict2_{name}_{_i}"
        return test_case
    setattr(TestGeneratedConflict2,
            f"test_conflict2_{_name}_{_i}", _make())


# ── 生成式: 引擎报告字段矩阵 ───────────────────────────────────
_ENGINE2_CASES = [
    # (名称, 记录, 期望压缩/冲突/候选 三元组)
    ("all_clean", [
        _rec("a", lesson="甲"), _rec("b", lesson="乙"),
    ], (0, 0, 0)),
    ("dup_clean", [
        _rec("a", lesson="相同"), _rec("b", lesson="相同"),
    ], (1, 0, 0)),
    ("conflict_only", [
        _rec("a", lesson="成功"), _rec("b", lesson="失败"),
    ], (0, 1, 0)),
    ("stale_low_only", [
        _rec("a", value=0.2, age_days=200),
    ], (0, 0, 1)),
    ("dup_and_conflict", [
        _rec("a", lesson="成功"), _rec("b", lesson="成功"),
        _rec("c", lesson="失败"),
    ], (1, 1, 0)),
    ("all_three", [
        _rec("a", lesson="成功"), _rec("b", lesson="成功"),
        _rec("c", lesson="失败"),
        _rec("d", value=0.2, age_days=200),
    ], (1, 1, 1)),
    ("mixed_clean", [
        _rec("a", lesson="成功"), _rec("b", lesson="日常"),
        _rec("c", lesson="相同"), _rec("d", lesson="相同"),
    ], (1, 0, 0)),
]


class TestGeneratedEngine2(unittest.TestCase):
    """生成式: 引擎报告三元组"""
    pass


for _i, (_name, _recs, _triple) in enumerate(_ENGINE2_CASES):
    def _make(name=_name, recs=_recs, trip=_triple):
        def test_case(self):
            eng = MemoryStabilizationEngine(enabled=True)
            r = eng.stabilize(recs)
            self.assertEqual(
                len(r["compression"]["merged"]), trip[0],
            )
            self.assertEqual(
                len(r["conflicts"]["conflicts"]), trip[1],
            )
            self.assertEqual(
                len(r["prune_candidates"]["candidates"]), trip[2],
            )
        test_case.__name__ = f"test_engine2_{name}_{_i}"
        return test_case
    setattr(TestGeneratedEngine2,
            f"test_engine2_{_name}_{_i}", _make())


# ── 生成式: 淘汰边界矩阵 ───────────────────────────────────────
_PRUNE2_CASES = [
    # (名称, value, age_days, confirmed, 期望候选)
    ("below_all", 0.29, 91, False, True),
    ("above_value", 0.31, 91, False, False),
    ("below_age", 0.29, 89, False, False),
    ("confirmed_always_protect", 0.29, 91, True, False),
    ("very_low_very_old", 0.01, 3650, False, True),
    ("zero_value_old", 0.0, 100, False, True),
    ("fresh_high", 0.9, 1, False, False),
    ("old_high_confirmed", 0.9, 300, True, False),
    ("old_high_unconfirmed", 0.9, 300, False, False),
    ("missing_ts_low", 0.1, None, False, False),
]


class TestGeneratedPrune2(unittest.TestCase):
    """生成式: 淘汰边界"""
    pass


for _i, (_name, _val, _age, _conf, _exp) in \
        enumerate(_PRUNE2_CASES):
    def _make(name=_name, val=_val, age=_age, conf=_conf,
              exp=_exp):
        def test_case(self):
            p = MemoryPruner(value_threshold=0.3, age_days=90)
            rec = {
                "id": "a", "trigger": "t", "value": val,
                "lesson": "l",
            }
            if age is not None:
                rec["timestamp"] = NOW - age * DAY
            confirmed = ["a"] if conf else []
            r = p.candidates([rec], confirmed_ids=confirmed)
            self.assertEqual(len(r["candidates"]) == 1, exp)
        test_case.__name__ = f"test_prune2_{name}_{_i}"
        return test_case
    setattr(TestGeneratedPrune2,
            f"test_prune2_{_name}_{_i}", _make())


if __name__ == "__main__":
    unittest.main()
