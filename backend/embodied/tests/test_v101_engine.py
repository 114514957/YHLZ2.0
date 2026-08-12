"""
YHLZ Embodied AI V10.1 - 记忆稳定化引擎与审计测试
(Memory Stabilization Engine & Audit)

覆盖:
    - 稳定化总报告 (压缩+权重+冲突+淘汰候选)
    - 淘汰执行 (回调 + 审计)
    - 审计 (记录/查询/回放/统计/落盘)
    - 停用错误帧
"""
import json
import os
import tempfile
import time
import unittest

from backend.embodied.companion.memory_stabilization import (
    MemoryStabilizationEngine,
)
from backend.embodied.companion.memory_stabilization.stabilization_audit import (
    STABILIZE_ACTIONS,
    StabilizationAudit,
    StabilizationAuditError,
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


class TestEngineStabilize(unittest.TestCase):
    """稳定化总报告"""

    def setUp(self):
        self.eng = MemoryStabilizationEngine(enabled=True)

    def test_empty_report(self):
        r = self.eng.stabilize([])
        self.assertEqual(r["mode"], "rule_based")
        self.assertEqual(r["total"], 0)
        self.assertIn("compression", r)
        self.assertIn("prune_candidates", r)
        self.assertIn("evaluation", r)
        self.assertIn("conflicts", r)

    def test_report_structure(self):
        recs = [_rec("a"), _rec("b")]
        r = self.eng.stabilize(recs)
        self.assertEqual(r["total"], 2)
        self.assertEqual(len(r["evaluation"]), 2)

    def test_compression_in_report(self):
        recs = [
            _rec("a", lesson="成功完成"),
            _rec("b", lesson="成功完成"),
        ]
        r = self.eng.stabilize(recs)
        self.assertEqual(len(r["compression"]["merged"]), 1)

    def test_conflicts_in_report(self):
        recs = [
            _rec("a", lesson="成功完成"),
            _rec("b", lesson="失败告终"),
        ]
        r = self.eng.stabilize(recs)
        self.assertEqual(len(r["conflicts"]["conflicts"]), 1)

    def test_confirmed_weight_in_report(self):
        recs = [_rec("a", value=0.5)]
        r = self.eng.stabilize(recs, confirmed_ids=["a"])
        self.assertEqual(r["evaluation"][0]["weight"], 0.65)

    def test_referenced_weight_in_report(self):
        recs = [_rec("a", value=0.5)]
        r = self.eng.stabilize(recs, referenced_ids=["a"])
        self.assertEqual(r["evaluation"][0]["weight"], 0.6)

    def test_prune_candidates_in_report(self):
        recs = [_rec("a", value=0.2, age_days=200)]
        r = self.eng.stabilize(recs)
        self.assertEqual(len(r["prune_candidates"]["candidates"]), 1)

    def test_confirmed_protected_in_report(self):
        recs = [_rec("a", value=0.2, age_days=200)]
        r = self.eng.stabilize(recs, confirmed_ids=["a"])
        self.assertEqual(r["prune_candidates"]["candidates"], [])

    def test_audit_written_on_stabilize(self):
        recs = [
            _rec("a", lesson="成功完成"),
            _rec("b", lesson="成功完成"),
            _rec("c", lesson="失败告终"),
        ]
        self.eng.stabilize(recs)
        stats = self.eng.audit_report()["stats"]
        self.assertEqual(stats["by_action"].get("compress", 0), 1)
        self.assertEqual(stats["by_action"].get("conflict", 0), 1)

    def test_audit_replay(self):
        recs = [
            _rec("a", lesson="成功完成"),
            _rec("b", lesson="成功完成"),
        ]
        self.eng.stabilize(recs)
        report = self.eng.audit_report(limit=50)
        self.assertGreaterEqual(len(report["recent"]), 1)


class TestEnginePrune(unittest.TestCase):
    """淘汰执行"""

    def setUp(self):
        self.eng = MemoryStabilizationEngine(enabled=True)

    def test_prune_candidates_api(self):
        recs = [_rec("a", value=0.2, age_days=200)]
        r = self.eng.prune_candidates(recs)
        self.assertEqual(len(r["candidates"]), 1)

    def test_prune_execute_forget(self):
        removed = []

        def forget(rid):
            removed.append(rid)
            return True

        recs = [_rec("a", value=0.2, age_days=200)]
        r = self.eng.prune_execute(["a"], forget, records=recs)
        self.assertEqual(r["removed"], 1)
        self.assertEqual(removed, ["a"])

    def test_prune_execute_audited(self):
        def forget(rid):
            return True

        recs = [_rec("a")]
        self.eng.prune_execute(["a"], forget, records=recs)
        stats = self.eng.audit_report()["stats"]
        self.assertEqual(stats["by_action"].get("prune", 0), 1)

    def test_prune_execute_not_found(self):
        def forget(rid):
            return False

        recs = [_rec("a")]
        r = self.eng.prune_execute(["zzz"], forget, records=recs)
        self.assertEqual(r["removed"], 0)
        self.assertEqual(r["not_found"], 1)

    def test_prune_execute_empty(self):
        def forget(rid):
            return True

        r = self.eng.prune_execute([], forget)
        self.assertEqual(r["requested"], 0)

    def test_prune_candidates_no_execution(self):
        recs = [_rec("a", value=0.2, age_days=200)]
        self.eng.prune_candidates(recs)
        stats = self.eng.audit_report()["stats"]
        self.assertEqual(stats["by_action"].get("prune", 0), 0)


class TestEngineEvaluate(unittest.TestCase):
    """权重评估"""

    def setUp(self):
        self.eng = MemoryStabilizationEngine(enabled=True)

    def test_evaluate(self):
        r = self.eng.evaluate(
            {"id": "a", "value": 0.5},
            {"confirmed": True},
        )
        self.assertEqual(r["weight"], 0.65)

    def test_evaluate_audited(self):
        self.eng.evaluate({"id": "a", "value": 0.5})
        stats = self.eng.audit_report()["stats"]
        self.assertEqual(stats["by_action"].get("evaluate", 0), 1)

    def test_evaluate_conflicts(self):
        r = self.eng.evaluate({"id": "a", "value": 0.5})
        self.assertIn("rule", r)


class TestEngineDisabled(unittest.TestCase):
    """停用"""

    def test_disabled_stabilize(self):
        eng = MemoryStabilizationEngine(enabled=False)
        r = eng.stabilize([])
        self.assertEqual(r["mode"], "error_frame")
        self.assertFalse(r["ok"])

    def test_disabled_prune(self):
        eng = MemoryStabilizationEngine(enabled=False)
        r = eng.prune_execute(["a"], lambda rid: True)
        self.assertEqual(r["mode"], "error_frame")

    def test_disabled_stats_still_ok(self):
        eng = MemoryStabilizationEngine(enabled=False)
        s = eng.stats()
        self.assertEqual(s["mode"], "rule_based")
        self.assertFalse(s["enabled"])

    def test_clear(self):
        eng = MemoryStabilizationEngine(enabled=True)
        recs = [_rec("a", value=0.2, age_days=200)]
        eng.stabilize(recs)
        n = eng.clear()
        self.assertGreaterEqual(n, 0)
        self.assertEqual(eng.audit_report()["stats"]["total"], 0)


class TestAudit(unittest.TestCase):
    """审计独立测试"""

    def test_record_basic(self):
        a = StabilizationAudit()
        entry = a.record("compress", ["a", "b"], "重复", {"ok": True})
        self.assertEqual(entry["action"], "compress")
        self.assertEqual(entry["record_ids"], ["a", "b"])
        self.assertIn("audit_id", entry)
        self.assertIn("timestamp", entry)

    def test_invalid_action_raises(self):
        a = StabilizationAudit()
        with self.assertRaises(StabilizationAuditError):
            a.record("bad_action")

    def test_query_by_action(self):
        a = StabilizationAudit()
        a.record("compress", ["a"])
        a.record("prune", ["b"])
        hits = a.query(action="compress")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["action"], "compress")

    def test_query_all(self):
        a = StabilizationAudit()
        a.record("compress", ["a"])
        a.record("prune", ["b"])
        self.assertEqual(len(a.query()), 2)

    def test_query_limit(self):
        a = StabilizationAudit()
        for i in range(10):
            a.record("compress", [f"r{i}"])
        self.assertEqual(len(a.query(limit=3)), 3)

    def test_replay(self):
        a = StabilizationAudit()
        a.record("conflict", ["a", "b"])
        self.assertEqual(len(a.replay()), 1)

    def test_stats(self):
        a = StabilizationAudit()
        a.record("compress", ["a"])
        a.record("prune", ["b"])
        s = a.stats()
        self.assertEqual(s["total"], 2)
        self.assertEqual(s["by_action"]["compress"], 1)
        self.assertEqual(s["by_action"]["prune"], 1)

    def test_max_records(self):
        a = StabilizationAudit(max_records=5)
        for i in range(10):
            a.record("compress", [f"r{i}"])
        self.assertEqual(a.stats()["total"], 5)

    def test_clear(self):
        a = StabilizationAudit()
        a.record("compress", ["a"])
        self.assertEqual(a.clear(), 1)
        self.assertEqual(a.stats()["total"], 0)

    def test_save_to_file(self):
        a = StabilizationAudit()
        a.record("compress", ["a"], "重复", {"n": 1})
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "audit.jsonl")
            n = a.save_to_file(path)
            self.assertEqual(n, 1)
            with open(path, "r", encoding="utf-8") as f:
                data = json.loads(f.readline())
            self.assertEqual(data["action"], "compress")

    def test_invalid_max_raises(self):
        with self.assertRaises(StabilizationAuditError):
            StabilizationAudit(max_records=0)

    def test_actions_list(self):
        self.assertEqual(
            STABILIZE_ACTIONS,
            ["compress", "prune", "conflict", "evaluate"],
        )


class TestEngineConfig(unittest.TestCase):
    """配置驱动"""

    def test_config_prune_threshold(self):
        eng = MemoryStabilizationEngine(config={
            "companion_memory_stabilize_prune_value_threshold": 0.6,
            "companion_memory_stabilize_prune_age_days": 90,
        })
        recs = [_rec("a", value=0.4, age_days=200)]
        r = eng.stabilize(recs)
        self.assertEqual(len(r["prune_candidates"]["candidates"]), 1)

    def test_config_similarity(self):
        eng = MemoryStabilizationEngine(config={
            "companion_memory_stabilize_compress_similarity": 1.0,
        })
        recs = [
            _rec("a", lesson="成功完成任务"),
            _rec("b", lesson="成功完成任务再"),
        ]
        r = eng.stabilize(recs)
        self.assertEqual(len(r["compression"]["merged"]), 0)

    def test_config_audit_max(self):
        eng = MemoryStabilizationEngine(config={
            "companion_memory_stabilize_audit_max": 3,
        })
        for i in range(5):
            eng.evaluate({"id": f"a{i}", "value": 0.5})
        self.assertEqual(eng.audit_report()["stats"]["total"], 3)


# ── 生成式: 引擎操作矩阵 ───────────────────────────────────────
_ENGINE_CASES = [
    # (名称, 记录列表, confirmed, 期望压缩组, 期望冲突组, 期望候选)
    ("normal", [
        _rec("a", lesson="成功完成"),
        _rec("b", lesson="成功完成"),
        _rec("c", lesson="失败告终"),
    ], [], 1, 1, 0),
    ("clean", [
        _rec("a", lesson="甲"),
        _rec("b", lesson="乙"),
    ], [], 0, 0, 0),
    ("stale_low", [
        _rec("a", value=0.2, age_days=200),
    ], [], 0, 0, 1),
    ("confirmed_protect", [
        _rec("a", value=0.2, age_days=200),
    ], ["a"], 0, 0, 0),
    ("all_dupes", [
        _rec("a", lesson="一样"),
        _rec("b", lesson="一样"),
        _rec("c", lesson="一样"),
    ], [], 2, 0, 0),
]


class TestGeneratedEngine(unittest.TestCase):
    """生成式: 引擎操作矩阵"""
    pass


for _i, (_name, _recs, _conf, _exp_cmp, _exp_cfl, _exp_prn) in \
        enumerate(_ENGINE_CASES):
    def _make(name=_name, recs=_recs, conf=_conf,
              ec=_exp_cmp, ex=_exp_cfl, ep=_exp_prn):
        def test_case(self):
            eng = MemoryStabilizationEngine(enabled=True)
            r = eng.stabilize(recs, confirmed_ids=conf)
            self.assertEqual(
                len(r["compression"]["merged"]), ec,
            )
            self.assertEqual(
                len(r["conflicts"]["conflicts"]), ex,
            )
            self.assertEqual(
                len(r["prune_candidates"]["candidates"]), ep,
            )
        test_case.__name__ = f"test_engine_{name}_{_i}"
        return test_case
    setattr(TestGeneratedEngine,
            f"test_engine_{_name}_{_i}", _make())


if __name__ == "__main__":
    unittest.main()
