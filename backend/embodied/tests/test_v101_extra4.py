"""
YHLZ Embodied AI V10.1 - 记忆稳定化生成式测试 4 (V10.1 Extra4)

覆盖 (生成式):
    - 权重评估 reason 矩阵
    - 压缩 reason 矩阵
    - 引擎 clear/重置矩阵
"""
import time
import unittest

from backend.embodied.companion.memory_stabilization import (
    MemoryStabilizationEngine,
)
from backend.embodied.companion.memory_stabilization.compressor import (
    MemoryCompressor,
)
from backend.embodied.companion.memory_stabilization.weighter import (
    MemoryWeighter,
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


# ── 生成式: 权重 reason 矩阵 ───────────────────────────────────
_REASON_CASES = [
    # (名称, context, 期望 reason 关键词)
    ("plain", {}, "基础价值"),
    ("confirmed", {"confirmed": True}, "CONFIRMED"),
    ("referenced", {"referenced": True}, "被引用"),
    ("freq_multi", {"frequency": 5}, "频率"),
    ("freq_conf", {"frequency": 3, "confirmed": True}, "频率"),
    ("freq_conf_ref", {"frequency": 3, "confirmed": True,
                        "referenced": True}, "被引用"),
    ("freq_one", {"frequency": 1}, "基础价值"),
    ("none_extra", {"frequency": 0}, "基础价值"),
]


class TestGeneratedReason(unittest.TestCase):
    """生成式: 权重 reason"""
    pass


for _i, (_name, _ctx, _kw) in enumerate(_REASON_CASES):
    def _make(name=_name, ctx=_ctx, kw=_kw):
        def test_case(self):
            w = MemoryWeighter()
            r = w.evaluate({"id": "a", "value": 0.5}, ctx)
            self.assertIn(kw, r["reason"])
            self.assertIn("rule", r)
        test_case.__name__ = f"test_reason_{name}_{_i}"
        return test_case
    setattr(TestGeneratedReason,
            f"test_reason_{_name}_{_i}", _make())


# ── 生成式: 压缩 reason 矩阵 ───────────────────────────────────
_COMPRESS_R_CASES = [
    # (名称, 记录, 期望 reason 关键词)
    ("dup_same_trigger", [
        {"id": "a", "trigger": "拾取", "lesson": "成功"},
        {"id": "b", "trigger": "拾取", "lesson": "成功"},
    ], "同触发"),
    ("dup_similar", [
        {"id": "a", "trigger": "拾取", "lesson": "成功完成拾取"},
        {"id": "b", "trigger": "拾取", "lesson": "成功完成拾取"},
    ], "相似"),
    ("dup_punct", [
        {"id": "a", "trigger": "拾取", "lesson": "成功完成。"},
        {"id": "b", "trigger": "拾取", "lesson": "成功完成!"},
    ], "同触发"),
    ("dup_english", [
        {"id": "a", "trigger": "pick", "lesson": "success"},
        {"id": "b", "trigger": "pick", "lesson": "success"},
    ], "同触发"),
]


class TestGeneratedCompressR(unittest.TestCase):
    """生成式: 压缩 reason"""
    pass


for _i, (_name, _recs, _kw) in enumerate(_COMPRESS_R_CASES):
    def _make(name=_name, recs=_recs, kw=_kw):
        def test_case(self):
            c = MemoryCompressor(similarity_threshold=0.9)
            r = c.compress(recs)
            self.assertGreaterEqual(len(r["merged"]), 1)
            self.assertIn(kw, r["merged"][0]["reason"])
        test_case.__name__ = f"test_compressr_{name}_{_i}"
        return test_case
    setattr(TestGeneratedCompressR,
            f"test_compressr_{_name}_{_i}", _make())


# ── 生成式: 引擎重置矩阵 ───────────────────────────────────────
_CLEAR_CASES = [
    # (名称, 操作序列, 期望 clear 后审计为空)
    ("clear_after_stabilize", "stabilize"),
    ("clear_after_prune", "prune"),
    ("clear_after_evaluate", "evaluate"),
    ("clear_after_compress", "compress"),
    ("clear_after_conflict", "conflict"),
    ("clear_twice", "double"),
]


class TestGeneratedClear(unittest.TestCase):
    """生成式: 引擎重置"""
    pass


for _i, (_name, _op) in enumerate(_CLEAR_CASES):
    def _make(name=_name, op=_op):
        def test_case(self):
            eng = MemoryStabilizationEngine(enabled=True)
            recs = [
                {"id": "a", "trigger": "t", "lesson": "成功",
                 "value": 0.5, "confidence": 0.5,
                 "timestamp": NOW},
                {"id": "b", "trigger": "t", "lesson": "成功",
                 "value": 0.5, "confidence": 0.5,
                 "timestamp": NOW},
            ]
            if op == "stabilize":
                eng.stabilize(recs)
            elif op == "prune":
                eng.prune_candidates(recs)
            elif op == "evaluate":
                eng.evaluate(recs[0])
            elif op == "compress":
                eng.compress(recs)
            elif op == "conflict":
                eng.detect_conflicts(recs)
            eng.clear()
            self.assertEqual(
                eng.audit_report()["stats"]["total"], 0,
            )
        test_case.__name__ = f"test_clear_{name}_{_i}"
        return test_case
    setattr(TestGeneratedClear,
            f"test_clear_{_name}_{_i}", _make())


# ── 生成式: 权重与压缩联动矩阵 ─────────────────────────────────
_LINK_CASES = [
    # (名称, 记录, 期望评估权重 = 基础值)
    ("eval_plain", [
        _rec("a", value=0.6), _rec("b", value=0.4),
    ], [0.6, 0.4]),
    ("eval_dup", [
        _rec("a", value=0.6), _rec("b", value=0.6),
    ], [0.6, 0.6]),
    ("eval_conflict", [
        _rec("a", value=0.7, lesson="成功"),
        _rec("b", value=0.7, lesson="失败"),
    ], [0.7, 0.7]),
    ("eval_stale", [
        _rec("a", value=0.3, age_days=200),
    ], [0.3]),
    ("eval_empty", [], []),
]


class TestGeneratedLink(unittest.TestCase):
    """生成式: 权重联动"""
    pass


for _i, (_name, _recs, _exp) in enumerate(_LINK_CASES):
    def _make(name=_name, recs=_recs, exp=_exp):
        def test_case(self):
            eng = MemoryStabilizationEngine(enabled=True)
            r = eng.stabilize(recs)
            weights = [e["weight"] for e in r["evaluation"]]
            self.assertEqual(weights, exp)
        test_case.__name__ = f"test_link_{name}_{_i}"
        return test_case
    setattr(TestGeneratedLink,
            f"test_link_{_name}_{_i}", _make())


if __name__ == "__main__":
    unittest.main()
