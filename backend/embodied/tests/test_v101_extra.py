"""
YHLZ Embodied AI V10.1 - 记忆稳定化生成式测试 1 (V10.1 Extra)

覆盖 (生成式):
    - 压缩相似度矩阵
    - 权重边界矩阵
    - 审计容量矩阵
"""
import unittest

from backend.embodied.companion.memory_stabilization.compressor import (
    MemoryCompressor,
    text_similarity,
)
from backend.embodied.companion.memory_stabilization.stabilization_audit import (
    StabilizationAudit,
)
from backend.embodied.companion.memory_stabilization.weighter import (
    MemoryWeighter,
)


# ── 生成式: 相似度矩阵 ─────────────────────────────────────────
_SIM_CASES = [
    # (名称, 文本a, 文本b, 期望区间 (min, max])
    ("identical", "成功完成", "成功完成", (1.0, 1.0)),
    ("norm_identical", "成功 完成", "成功完成", (1.0, 1.0)),
    ("punct_identical", "成功完成！", "成功完成。", (1.0, 1.0)),
    ("case_identical", "Success", "success", (1.0, 1.0)),
    ("totally_diff", "成功完成", "失败告终", (0.0, 0.0)),
    ("one_empty", "成功", "", (0.0, 0.0)),
    ("both_empty", "", "", (1.0, 1.0)),
    ("prefix", "成功完成任务", "成功完成", (0.5, 1.0)),
    ("suffix_added", "成功完成", "成功完成额外", (0.5, 1.0)),
    ("overlap", "成功完成拾取", "成功失败拾取", (0.5, 1.0)),
    ("single_char", "甲", "甲", (1.0, 1.0)),
    ("single_diff", "甲", "乙", (0.0, 0.0)),
]


class TestGeneratedSimilarity(unittest.TestCase):
    """生成式: 相似度区间"""
    pass


for _i, (_name, _a, _b, _rng) in enumerate(_SIM_CASES):
    def _make(name=_name, a=_a, b=_b, rng=_rng):
        def test_case(self):
            sim = text_similarity(a, b)
            self.assertGreaterEqual(sim, rng[0])
            self.assertLessEqual(sim, rng[1])
        test_case.__name__ = f"test_sim_{name}_{_i}"
        return test_case
    setattr(TestGeneratedSimilarity,
            f"test_sim_{_name}_{_i}", _make())


# ── 生成式: 压缩多触发矩阵 ─────────────────────────────────────
_COMPRESS2_CASES = [
    # (名称, 记录数, 触发词数, 每触发重复数, 期望合并总数)
    ("one_triple", 3, 1, 3, 2),
    ("two_pairs", 4, 2, 2, 2),
    ("single_all", 3, 3, 1, 0),
    ("mixed_2_1", 3, 2, 2, 1),
    ("five_dup", 5, 1, 5, 4),
    ("no_dup", 1, 1, 1, 0),
]


class TestGeneratedCompress2(unittest.TestCase):
    """生成式: 多触发压缩"""
    pass


for _i, (_name, _n, _trig, _dup, _exp) in \
        enumerate(_COMPRESS2_CASES):
    def _make(name=_name, n=_n, trig=_trig, dup=_dup, exp=_exp):
        def test_case(self):
            c = MemoryCompressor(similarity_threshold=0.9)
            recs = []
            for t in range(trig):
                for d in range(dup):
                    recs.append({
                        "id": f"r{t}_{d}", "trigger": f"t{t}",
                        "lesson": "完全相同内容",
                    })
            r = c.compress(recs[:n])
            self.assertEqual(len(r["merged_from"]), exp)
        test_case.__name__ = f"test_compress2_{name}_{_i}"
        return test_case
    setattr(TestGeneratedCompress2,
            f"test_compress2_{_name}_{_i}", _make())


# ── 生成式: 权重边界矩阵 ───────────────────────────────────────
_WEIGHT2_CASES = [
    # (名称, 基础值, 频率, 确认, 引用, 期望权重上限)
    ("low_base_freq_cap", 0.1, 100, True, True, 0.65),
    ("zero_base_all", 0.0, 10, True, True, 0.45),
    ("mid_base_freq", 0.4, 5, False, False, 0.6),
    ("high_base_cap", 0.95, 1, False, False, 0.95),
    ("neg_freq", 0.5, -5, False, False, 0.5),
    ("freq_1_confirmed", 0.5, 1, True, False, 0.65),
    ("freq_2_referenced", 0.5, 2, False, True, 0.65),
    ("full_boost", 0.7, 4, True, True, 1.0),
]


class TestGeneratedWeight2(unittest.TestCase):
    """生成式: 权重边界"""
    pass


for _i, (_name, _base, _freq, _conf, _ref, _cap) in \
        enumerate(_WEIGHT2_CASES):
    def _make(name=_name, base=_base, freq=_freq, conf=_conf,
              ref=_ref, cap=_cap):
        def test_case(self):
            w = MemoryWeighter()
            r = w.evaluate(
                {"id": "a", "value": base},
                {"frequency": freq, "confirmed": conf,
                 "referenced": ref},
            )
            self.assertLessEqual(r["weight"], cap)
            self.assertGreaterEqual(r["weight"], 0.0)
        test_case.__name__ = f"test_weight2_{name}_{_i}"
        return test_case
    setattr(TestGeneratedWeight2,
            f"test_weight2_{_name}_{_i}", _make())


# ── 生成式: 审计容量矩阵 ───────────────────────────────────────
_AUDIT_CASES = [
    # (名称, max_records, 写入数, 期望保留数)
    ("cap_5_write_3", 5, 3, 3),
    ("cap_5_write_10", 5, 10, 5),
    ("cap_100_write_50", 100, 50, 50),
    ("cap_100_write_200", 100, 200, 100),
    ("cap_1_write_1", 1, 1, 1),
    ("cap_10_write_0", 10, 0, 0),
]


class TestGeneratedAudit(unittest.TestCase):
    """生成式: 审计容量"""
    pass


for _i, (_name, _max, _n, _exp) in enumerate(_AUDIT_CASES):
    def _make(name=_name, maxr=_max, n=_n, exp=_exp):
        def test_case(self):
            a = StabilizationAudit(max_records=maxr)
            for j in range(n):
                a.record("compress", [f"r{j}"])
            self.assertEqual(a.stats()["total"], exp)
        test_case.__name__ = f"test_audit_{name}_{_i}"
        return test_case
    setattr(TestGeneratedAudit,
            f"test_audit_{_name}_{_i}", _make())


if __name__ == "__main__":
    unittest.main()
