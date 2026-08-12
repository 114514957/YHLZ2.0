"""
YHLZ Embodied AI V10.1 - 记忆稳定化生成式测试 3 (V10.1 Extra3)

覆盖 (生成式):
    - 引擎操作稳定性矩阵 (重复调用不变)
    - 压缩保序矩阵
    - 审计查询矩阵
"""
import time
import unittest

from backend.embodied.companion.memory_stabilization import (
    MemoryStabilizationEngine,
)
from backend.embodied.companion.memory_stabilization.compressor import (
    MemoryCompressor,
)
from backend.embodied.companion.memory_stabilization.stabilization_audit import (
    StabilizationAudit,
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


# ── 生成式: 引擎稳定性矩阵 ─────────────────────────────────────
_STABILITY_CASES = [
    # (名称, 记录列表, 运行次数, 期望稳定)
    ("stable_clean", [
        _rec("a", lesson="甲"), _rec("b", lesson="乙"),
    ], 3),
    ("stable_dup", [
        _rec("a", lesson="相同"), _rec("b", lesson="相同"),
    ], 3),
    ("stable_conflict", [
        _rec("a", lesson="成功"), _rec("b", lesson="失败"),
    ], 3),
    ("stable_stale", [
        _rec("a", value=0.2, age_days=200),
    ], 3),
    ("stable_mixed", [
        _rec("a", lesson="成功"), _rec("b", lesson="成功"),
        _rec("c", lesson="失败"),
        _rec("d", value=0.2, age_days=200),
    ], 3),
]


class TestGeneratedStability(unittest.TestCase):
    """生成式: 引擎稳定性"""
    pass


for _i, (_name, _recs, _runs) in enumerate(_STABILITY_CASES):
    def _make(name=_name, recs=_recs, runs=_runs):
        def test_case(self):
            eng = MemoryStabilizationEngine(enabled=True)
            first = eng.stabilize(recs)
            for _ in range(runs - 1):
                again = eng.stabilize(recs)
                self.assertEqual(
                    len(again["compression"]["merged"]),
                    len(first["compression"]["merged"]),
                )
                self.assertEqual(
                    len(again["conflicts"]["conflicts"]),
                    len(first["conflicts"]["conflicts"]),
                )
                self.assertEqual(
                    len(again["prune_candidates"]["candidates"]),
                    len(first["prune_candidates"]["candidates"]),
                )
        test_case.__name__ = f"test_stability_{name}_{_i}"
        return test_case
    setattr(TestGeneratedStability,
            f"test_stability_{_name}_{_i}", _make())


# ── 生成式: 压缩保序矩阵 ───────────────────────────────────────
_KEEP_CASES = [
    # (名称, 记录, 期望保留 ID 集合)
    ("keep_all_distinct", [
        _rec("a", trigger="t1", lesson="甲"),
        _rec("b", trigger="t2", lesson="乙"),
    ], {"a", "b"}),
    ("keep_primary_only", [
        _rec("a", trigger="t", lesson="一样", value=0.9),
        _rec("b", trigger="t", lesson="一样", value=0.3),
    ], {"a"}),
    ("keep_primary_high_conf", [
        _rec("a", trigger="t", lesson="一样", value=0.5, conf=0.9),
        _rec("b", trigger="t", lesson="一样", value=0.9, conf=0.1),
    ], {"b"}),
    ("keep_two_groups", [
        _rec("a", trigger="t1", lesson="一样"),
        _rec("b", trigger="t1", lesson="一样"),
        _rec("c", trigger="t2", lesson="不同"),
    ], {"a", "c"}),
    ("keep_all_single", [
        _rec("a", trigger="t1", lesson="甲"),
    ], {"a"}),
    ("keep_after_merge", [
        _rec("a", trigger="t", lesson="一样"),
        _rec("b", trigger="t", lesson="一样"),
        _rec("c", trigger="t", lesson="一样"),
    ], {"a"}),
]


class TestGeneratedKeep(unittest.TestCase):
    """生成式: 压缩保留集合"""
    pass


for _i, (_name, _recs, _exp) in enumerate(_KEEP_CASES):
    def _make(name=_name, recs=_recs, exp=_exp):
        def test_case(self):
            c = MemoryCompressor(similarity_threshold=0.9)
            r = c.compress(recs)
            self.assertEqual(set(r["kept"]), exp)
        test_case.__name__ = f"test_keep_{name}_{_i}"
        return test_case
    setattr(TestGeneratedKeep,
            f"test_keep_{_name}_{_i}", _make())


# ── 生成式: 审计查询矩阵 ───────────────────────────────────────
_QUERY_CASES = [
    # (名称, 写入动作序列, 查询动作, 期望命中数)
    ("all_compress", ["compress", "compress", "compress"],
     "compress", 3),
    ("all_prune", ["prune", "prune"], "prune", 2),
    ("mixed_compress", ["compress", "prune", "compress"],
     "compress", 2),
    ("mixed_prune", ["compress", "prune", "conflict"],
     "prune", 1),
    ("conflict_only", ["conflict", "conflict", "conflict"],
     "conflict", 3),
    ("evaluate_only", ["evaluate", "evaluate"], "evaluate", 2),
    ("none_match", ["compress"], "prune", 0),
    ("empty_query", [], "compress", 0),
]


class TestGeneratedQuery(unittest.TestCase):
    """生成式: 审计查询"""
    pass


for _i, (_name, _actions, _query, _exp) in \
        enumerate(_QUERY_CASES):
    def _make(name=_name, actions=_actions, q=_query, exp=_exp):
        def test_case(self):
            a = StabilizationAudit()
            for j, act in enumerate(actions):
                a.record(act, [f"r{j}"])
            self.assertEqual(len(a.query(action=q)), exp)
        test_case.__name__ = f"test_query_{name}_{_i}"
        return test_case
    setattr(TestGeneratedQuery,
            f"test_query_{_name}_{_i}", _make())


# ── 生成式: 引擎统计字段矩阵 ───────────────────────────────────
_STATS_CASES = [
    # (名称, 操作序列, 期望字段存在)
    ("empty", [], True),
    ("after_stabilize", [("stabilize", [
        _rec("a", lesson="成功"), _rec("b", lesson="失败"),
    ])], True),
    ("after_prune", [("prune", [
        _rec("a", value=0.2, age_days=200),
    ])], True),
    ("after_evaluate", [("evaluate", [
        {"id": "a", "value": 0.5},
    ])], True),
]


class TestGeneratedStats(unittest.TestCase):
    """生成式: 引擎统计"""
    pass


for _i, (_name, _ops, _expect) in enumerate(_STATS_CASES):
    def _make(name=_name, ops=_ops, expect=_expect):
        def test_case(self):
            eng = MemoryStabilizationEngine(enabled=True)
            for op, arg in ops:
                if op == "stabilize":
                    eng.stabilize(arg)
                elif op == "prune":
                    eng.prune_candidates(arg)
                elif op == "evaluate":
                    eng.evaluate(arg[0] if isinstance(arg, list)
                                  else arg)
            s = eng.stats()
            self.assertEqual(s["mode"], "rule_based")
            for key in ("compressor", "pruner", "weighter",
                        "conflict_detector", "audit"):
                self.assertIn(key, s)
        test_case.__name__ = f"test_stats_{name}_{_i}"
        return test_case
    setattr(TestGeneratedStats,
            f"test_stats_{_name}_{_i}", _make())


if __name__ == "__main__":
    unittest.main()
