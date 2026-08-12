"""
YHLZ Embodied AI V10.1 - 记忆稳定化生成式测试 7 (V10.1 Extra7)

覆盖 (生成式):
    - 引擎审计记录字段矩阵
    - 冲突记录 ID 包含矩阵
    - 引擎禁用下各能力矩阵
"""
import time
import unittest

from backend.embodied.companion.memory_stabilization import (
    MemoryStabilizationEngine,
)
from backend.embodied.companion.memory_stabilization.conflict_detector import (
    MemoryConflictDetector,
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


# ── 生成式: 审计字段矩阵 ───────────────────────────────────────
_FIELD_CASES = [
    # (名称, action, record_ids, reason, result)
    ("compress", "compress", ["a", "b"], "重复", {"n": 2}),
    ("prune", "prune", ["a"], "低价值", {"removed": True}),
    ("conflict", "conflict", ["a", "b"], "矛盾", {"type": "x"}),
    ("evaluate", "evaluate", ["a"], "权重", {"weight": 0.6}),
    ("empty_ids", "compress", [], "无", {}),
]


class TestGeneratedFields(unittest.TestCase):
    """生成式: 审计字段"""
    pass


for _i, (_name, _act, _ids, _reason, _result) in \
        enumerate(_FIELD_CASES):
    def _make(name=_name, act=_act, ids=_ids, reason=_reason,
              result=_result):
        def test_case(self):
            a = StabilizationAudit()
            entry = a.record(act, ids, reason, result)
            for key in ("audit_id", "timestamp", "action",
                        "record_ids", "reason", "result"):
                self.assertIn(key, entry)
            self.assertEqual(entry["action"], act)
            self.assertEqual(entry["record_ids"], ids)
            self.assertEqual(entry["reason"], reason)
        test_case.__name__ = f"test_fields_{name}_{_i}"
        return test_case
    setattr(TestGeneratedFields,
            f"test_fields_{_name}_{_i}", _make())


# ── 生成式: 冲突 ID 包含矩阵 ───────────────────────────────────
_ID_CASES = [
    # (名称, 记录, 期望冲突包含 ID 数)
    ("two_ids", [
        {"id": "a", "trigger": "t", "lesson": "成功"},
        {"id": "b", "trigger": "t", "lesson": "失败"},
    ], 2),
    ("three_ids", [
        {"id": "a", "trigger": "t", "lesson": "成功"},
        {"id": "b", "trigger": "t", "lesson": "成功"},
        {"id": "c", "trigger": "t", "lesson": "失败"},
    ], 3),
    ("four_ids", [
        {"id": "a", "trigger": "t", "lesson": "成功"},
        {"id": "b", "trigger": "t", "lesson": "失败"},
        {"id": "c", "trigger": "t", "lesson": "成功"},
        {"id": "d", "trigger": "t", "lesson": "失败"},
    ], 4),
]


class TestGeneratedIds(unittest.TestCase):
    """生成式: 冲突 ID 包含"""
    pass


for _i, (_name, _recs, _exp) in enumerate(_ID_CASES):
    def _make(name=_name, recs=_recs, exp=_exp):
        def test_case(self):
            d = MemoryConflictDetector()
            r = d.detect(recs)
            self.assertEqual(len(r["conflicts"]), 1)
            self.assertEqual(
                len(r["conflicts"][0]["record_ids"]), exp,
            )
        test_case.__name__ = f"test_ids_{name}_{_i}"
        return test_case
    setattr(TestGeneratedIds,
            f"test_ids_{_name}_{_i}", _make())


# ── 生成式: 禁用下各能力矩阵 ───────────────────────────────────
_DISABLED_CASES = [
    # (名称, 方法名, 参数)
    ("stabilize", "stabilize", ([_rec("a")],)),
    ("prune_candidates", "prune_candidates", ([_rec("a")],)),
    ("prune_execute", "prune_execute", (["a"], lambda x: True)),
    ("compress", "compress", ([_rec("a")],)),
    ("detect_conflicts", "detect_conflicts", ([_rec("a")],)),
    ("evaluate", "evaluate", ({"id": "a", "value": 0.5},)),
]


class TestGeneratedDisabled(unittest.TestCase):
    """生成式: 禁用错误帧"""
    pass


for _i, (_name, _method, _args) in enumerate(_DISABLED_CASES):
    def _make(name=_name, method=_method, args=_args):
        def test_case(self):
            eng = MemoryStabilizationEngine(enabled=False)
            r = getattr(eng, method)(*args)
            self.assertEqual(r["mode"], "error_frame")
            self.assertFalse(r["ok"])
        test_case.__name__ = f"test_disabled_{name}_{_i}"
        return test_case
    setattr(TestGeneratedDisabled,
            f"test_disabled_{_name}_{_i}", _make())


if __name__ == "__main__":
    unittest.main()
