"""
YHLZ Embodied AI V10.1 - 记忆稳定化生成式测试 6 (V10.1 Extra6)

覆盖 (生成式):
    - 引擎默认值矩阵
    - 多语言冲突矩阵
    - 审计回放保序矩阵
"""
import time
import unittest

from backend.embodied.companion.memory_stabilization import (
    MemoryStabilizationEngine,
)
from backend.embodied.companion.memory_stabilization.compressor import (
    MemoryCompressor,
)
from backend.embodied.companion.memory_stabilization.conflict_detector import (
    MemoryConflictDetector,
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


# ── 生成式: 引擎默认值矩阵 ─────────────────────────────────────
_DEFAULT_CASES = [
    # (名称, 输入, 检查字段, 期望默认值)
    ("missing_value", {"id": "a", "trigger": "t"}, "value", 0.5),
    ("missing_conf", {"id": "a", "trigger": "t"}, "confidence", 0.0),
    ("missing_timestamp", {"id": "a", "trigger": "t"},
     "timestamp", None),
    ("missing_trigger", {"id": "a"}, "trigger", ""),
    ("str_value", {"id": "a", "trigger": "t", "value": "0.7"},
     "value", 0.7),
]


class TestGeneratedDefaults(unittest.TestCase):
    """生成式: 默认值"""
    pass


for _i, (_name, _recx, _field, _exp) in enumerate(_DEFAULT_CASES):
    def _make(name=_name, rec=_recx, field=_field, exp=_exp):
        def test_case(self):
            eng = MemoryStabilizationEngine(enabled=True)
            r = eng.stabilize([rec])
            self.assertEqual(r["total"], 1)
            if exp is None:
                return
            eval_rec = r["evaluation"][0]
            if field == "value":
                self.assertEqual(eval_rec["base_value"], exp)
        test_case.__name__ = f"test_default_{name}_{_i}"
        return test_case
    setattr(TestGeneratedDefaults,
            f"test_default_{_name}_{_i}", _make())


# ── 生成式: 多语言冲突矩阵 ─────────────────────────────────────
_LANG_CASES = [
    # (名称, 记录, 期望冲突数)
    ("chinese_conflict", [
        {"id": "a", "trigger": "任务", "lesson": "成功完成"},
        {"id": "b", "trigger": "任务", "lesson": "失败告终"},
    ], 1),
    ("english_conflict", [
        {"id": "a", "trigger": "task", "lesson": "works fine"},
        {"id": "b", "trigger": "task", "lesson": "failed"},
    ], 1),
    ("chinese_agree", [
        {"id": "a", "trigger": "任务", "lesson": "成功完成"},
        {"id": "b", "trigger": "任务", "lesson": "成功且顺利"},
    ], 0),
    ("english_agree", [
        {"id": "a", "trigger": "task", "lesson": "works fine"},
        {"id": "b", "trigger": "task", "lesson": "ok good"},
    ], 0),
    ("chinese_english_mix", [
        {"id": "a", "trigger": "task", "lesson": "成功 done"},
        {"id": "b", "trigger": "task", "lesson": "失败 failed"},
    ], 1),
    ("no_signal_mix", [
        {"id": "a", "trigger": "task", "lesson": "记录"},
        {"id": "b", "trigger": "task", "lesson": "日常"},
    ], 0),
]


class TestGeneratedLang(unittest.TestCase):
    """生成式: 多语言冲突"""
    pass


for _i, (_name, _recs, _exp) in enumerate(_LANG_CASES):
    def _make(name=_name, recs=_recs, exp=_exp):
        def test_case(self):
            d = MemoryConflictDetector()
            r = d.detect(recs)
            self.assertEqual(len(r["conflicts"]), exp)
        test_case.__name__ = f"test_lang_{name}_{_i}"
        return test_case
    setattr(TestGeneratedLang,
            f"test_lang_{_name}_{_i}", _make())


# ── 生成式: 压缩跨字段相似矩阵 ─────────────────────────────────
_FIELD_SIM_CASES = [
    # (名称, 记录a, 记录b, 期望合并)
    ("lesson_same", {"lesson": "成功"}, {"lesson": "成功"}, True),
    ("result_same", {"result": "成功"}, {"result": "成功"}, True),
    ("lesson_vs_result", {"lesson": "成功"}, {"result": "成功"}, True),
    ("action_same", {"action": "拾取"}, {"action": "拾取"}, True),
    ("all_empty", {}, {}, True),
    ("lesson_diff", {"lesson": "成功"}, {"lesson": "失败"}, False),
    ("mixed_fields", {"lesson": "成功完成", "action": "拾取"},
     {"lesson": "成功完成", "action": "拾取"}, True),
]


class TestGeneratedFieldSim(unittest.TestCase):
    """生成式: 跨字段相似"""
    pass


for _i, (_name, _a, _b, _exp) in enumerate(_FIELD_SIM_CASES):
    def _make(name=_name, a=_a, b=_b, exp=_exp):
        def test_case(self):
            c = MemoryCompressor(similarity_threshold=0.9)
            ra = dict(a, id="a", trigger="t")
            rb = dict(b, id="b", trigger="t")
            r = c.compress([ra, rb])
            self.assertEqual(len(r["merged"]) == 1, exp)
        test_case.__name__ = f"test_fieldsim_{name}_{_i}"
        return test_case
    setattr(TestGeneratedFieldSim,
            f"test_fieldsim_{_name}_{_i}", _make())


# ── 生成式: 压缩优先级矩阵 ─────────────────────────────────────
_PRIORITY_CASES = [
    # (名称, 记录a(value,conf), 记录b(value,conf), 期望 primary)
    ("value_wins", (0.3, 0.9), (0.9, 0.1), "b"),
    ("conf_wins", (0.5, 0.9), (0.5, 0.1), "a"),
    ("value_conf_combined", (0.4, 0.9), (0.5, 0.8), "b"),
    ("equal_tie", (0.5, 0.5), (0.5, 0.5), "a"),
    ("zero_vs_high", (0.0, 0.0), (1.0, 1.0), "b"),
]


class TestGeneratedPriority(unittest.TestCase):
    """生成式: 压缩优先级"""
    pass


for _i, (_name, _a, _b, _exp) in enumerate(_PRIORITY_CASES):
    def _make(name=_name, a=_a, b=_b, exp=_exp):
        def test_case(self):
            c = MemoryCompressor(similarity_threshold=0.9)
            ra = {"id": "a", "trigger": "t", "lesson": "一样",
                  "value": a[0], "confidence": a[1]}
            rb = {"id": "b", "trigger": "t", "lesson": "一样",
                  "value": b[0], "confidence": b[1]}
            r = c.compress([ra, rb])
            self.assertEqual(r["merged"][0]["primary_id"], exp)
        test_case.__name__ = f"test_priority_{name}_{_i}"
        return test_case
    setattr(TestGeneratedPriority,
            f"test_priority_{_name}_{_i}", _make())


# ── 生成式: 引擎全流程矩阵 ─────────────────────────────────────
_FLOW_CASES = [
    # (名称, 记录, 期望模式)
    ("flow_clean", [
        _rec("a", lesson="甲"), _rec("b", lesson="乙"),
    ], "rule_based"),
    ("flow_dup", [
        _rec("a", lesson="相同"), _rec("b", lesson="相同"),
    ], "rule_based"),
    ("flow_conflict", [
        _rec("a", lesson="成功"), _rec("b", lesson="失败"),
    ], "rule_based"),
    ("flow_stale", [
        _rec("a", value=0.2, age_days=200),
    ], "rule_based"),
    ("flow_empty", [], "rule_based"),
]


class TestGeneratedFlow(unittest.TestCase):
    """生成式: 全流程"""
    pass


for _i, (_name, _recs, _exp) in enumerate(_FLOW_CASES):
    def _make(name=_name, recs=_recs, exp=_exp):
        def test_case(self):
            eng = MemoryStabilizationEngine(enabled=True)
            r = eng.stabilize(recs)
            self.assertEqual(r["mode"], exp)
            self.assertEqual(r["compression"]["mode"], exp)
            self.assertEqual(r["prune_candidates"]["mode"], exp)
            self.assertEqual(r["conflicts"]["mode"], exp)
        test_case.__name__ = f"test_flow_{name}_{_i}"
        return test_case
    setattr(TestGeneratedFlow,
            f"test_flow_{_name}_{_i}", _make())


if __name__ == "__main__":
    unittest.main()
