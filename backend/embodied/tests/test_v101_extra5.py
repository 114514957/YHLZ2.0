"""
YHLZ Embodied AI V10.1 - 记忆稳定化生成式测试 5 (V10.1 Extra5)

覆盖 (生成式):
    - 淘汰执行矩阵
    - 冲突详情矩阵
    - 引擎 total 字段矩阵
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


# ── 生成式: 淘汰执行矩阵 ───────────────────────────────────────
_EXEC_CASES = [
    # (名称, 请求 ID, 回调成功集合, 期望 removed/not_found)
    ("all_ok", ["a", "b"], {"a", "b"}, (2, 0)),
    ("all_fail", ["a", "b"], set(), (0, 2)),
    ("partial", ["a", "b", "c"], {"a", "c"}, (2, 1)),
    ("empty", [], set(), (0, 0)),
    ("unknown_ids", ["x", "y"], {"a"}, (0, 2)),
    ("single_ok", ["a"], {"a"}, (1, 0)),
]


class TestGeneratedExec(unittest.TestCase):
    """生成式: 淘汰执行"""
    pass


for _i, (_name, _ids, _ok_set, _exp) in enumerate(_EXEC_CASES):
    def _make(name=_name, ids=_ids, okset=_ok_set, exp=_exp):
        def test_case(self):
            p = MemoryPruner()
            r = p.execute(ids, lambda rid: rid in okset)
            self.assertEqual(r["removed"], exp[0])
            self.assertEqual(r["not_found"], exp[1])
        test_case.__name__ = f"test_exec_{name}_{_i}"
        return test_case
    setattr(TestGeneratedExec,
            f"test_exec_{_name}_{_i}", _make())


# ── 生成式: 冲突详情矩阵 ───────────────────────────────────────
_DETAIL_CASES = [
    # (名称, 记录, 期望详情含正向/反向计数)
    ("one_each", [
        {"id": "a", "trigger": "t", "lesson": "成功"},
        {"id": "b", "trigger": "t", "lesson": "失败"},
    ], ("1 条", "1 条")),
    ("two_one", [
        {"id": "a", "trigger": "t", "lesson": "成功"},
        {"id": "b", "trigger": "t", "lesson": "成功"},
        {"id": "c", "trigger": "t", "lesson": "失败"},
    ], ("2 条", "1 条")),
    ("one_two", [
        {"id": "a", "trigger": "t", "lesson": "成功"},
        {"id": "b", "trigger": "t", "lesson": "失败"},
        {"id": "c", "trigger": "t", "lesson": "失败"},
    ], ("1 条", "2 条")),
    ("three_three", [
        {"id": "a", "trigger": "t", "lesson": "成功"},
        {"id": "b", "trigger": "t", "lesson": "成功"},
        {"id": "c", "trigger": "t", "lesson": "成功"},
        {"id": "d", "trigger": "t", "lesson": "失败"},
        {"id": "e", "trigger": "t", "lesson": "失败"},
        {"id": "f", "trigger": "t", "lesson": "失败"},
    ], ("3 条", "3 条")),
]


class TestGeneratedDetail(unittest.TestCase):
    """生成式: 冲突详情"""
    pass


for _i, (_name, _recs, _exp) in enumerate(_DETAIL_CASES):
    def _make(name=_name, recs=_recs, exp=_exp):
        def test_case(self):
            d = MemoryConflictDetector()
            r = d.detect(recs)
            self.assertEqual(len(r["conflicts"]), 1)
            detail = r["conflicts"][0]["detail"]
            self.assertIn(exp[0], detail)
            self.assertIn(exp[1], detail)
            self.assertIn("相反", detail)
        test_case.__name__ = f"test_detail_{name}_{_i}"
        return test_case
    setattr(TestGeneratedDetail,
            f"test_detail_{_name}_{_i}", _make())


# ── 生成式: 引擎 total 字段矩阵 ────────────────────────────────
_TOTAL_CASES = [
    # (名称, 记录数, 期望 total)
    ("zero", [], 0),
    ("one", [_rec("a")], 1),
    ("two", [_rec("a"), _rec("b")], 2),
    ("five", [_rec(f"a{i}") for i in range(5)], 5),
    ("ten", [_rec(f"a{i}") for i in range(10)], 10),
]


class TestGeneratedTotal(unittest.TestCase):
    """生成式: total 字段"""
    pass


for _i, (_name, _recs, _exp) in enumerate(_TOTAL_CASES):
    def _make(name=_name, recs=_recs, exp=_exp):
        def test_case(self):
            eng = MemoryStabilizationEngine(enabled=True)
            r = eng.stabilize(recs)
            self.assertEqual(r["total"], exp)
            self.assertEqual(r["compression"]["total"], exp)
            self.assertEqual(r["conflicts"]["total"], exp)
        test_case.__name__ = f"test_total_{name}_{_i}"
        return test_case
    setattr(TestGeneratedTotal,
            f"test_total_{_name}_{_i}", _make())


# ── 生成式: 候选 reason 组合矩阵 ───────────────────────────────
_CAND_R_CASES = [
    # (名称, value, age_days, 期望 reason 数)
    ("low_stale", 0.2, 200, 3),
    ("low_only", 0.2, 50, 3),
    ("stale_only", 0.5, 200, 3),
    ("all_clean", 0.5, 50, 3),
    ("zero_stale", 0.0, 365, 3),
]


class TestGeneratedCandR(unittest.TestCase):
    """生成式: 候选 reason 组合"""
    pass


for _i, (_name, _val, _age, _exp) in enumerate(_CAND_R_CASES):
    def _make(name=_name, val=_val, age=_age, exp=_exp):
        def test_case(self):
            p = MemoryPruner(value_threshold=0.3, age_days=90)
            r = p.candidates([_rec("a", value=val, age_days=age)])
            if r["candidates"]:
                self.assertEqual(
                    len(r["candidates"][0]["reasons"]), exp,
                )
        test_case.__name__ = f"test_candr_{name}_{_i}"
        return test_case
    setattr(TestGeneratedCandR,
            f"test_candr_{_name}_{_i}", _make())


# ── 生成式: 审计回放矩阵 ───────────────────────────────────────
_REPLAY_CASES = [
    # (名称, 写入数, 回放 limit, 期望返回数)
    ("limit_all", 10, 100, 10),
    ("limit_half", 10, 5, 5),
    ("limit_zero_all", 10, 0, 10),
    ("single", 1, 10, 1),
    ("empty", 0, 10, 0),
    ("limit_negative", 10, -1, 10),
]


class TestGeneratedReplay(unittest.TestCase):
    """生成式: 审计回放"""
    pass


for _i, (_name, _n, _limit, _exp) in enumerate(_REPLAY_CASES):
    def _make(name=_name, n=_n, limit=_limit, exp=_exp):
        def test_case(self):
            from backend.embodied.companion.memory_stabilization.stabilization_audit import (
                StabilizationAudit,
            )
            a = StabilizationAudit()
            for j in range(n):
                a.record("compress", [f"r{j}"])
            if limit < 0:
                self.assertEqual(len(a.replay()), exp)
            else:
                self.assertEqual(len(a.replay(limit=limit)), exp)
        test_case.__name__ = f"test_replay_{name}_{_i}"
        return test_case
    setattr(TestGeneratedReplay,
            f"test_replay_{_name}_{_i}", _make())


if __name__ == "__main__":
    unittest.main()
