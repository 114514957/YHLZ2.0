"""
YHLZ Embodied AI V10.1 - 记忆稳定化最终验收测试 (V10.1 Final)

覆盖:
    - 引擎四能力完整矩阵
    - 审计全程追踪
    - 健康联动端到端
    - 兼容 V10.0 及以前
"""
import time
import unittest

from backend.embodied.companion.memory_stabilization import (
    MemoryStabilizationEngine,
)
from backend.embodied.companion.memory_stabilization.stabilization_audit import (
    StabilizationAudit,
)
from backend.embodied.service import EmbodiedService

NOW = time.time()
DAY = 86400


def _rec(rid, trigger="t", lesson="普通", value=0.5,
         age_days=10, conf=0.5):
    return {
        "id": rid, "trigger": trigger, "lesson": lesson,
        "value": value, "confidence": conf,
        "timestamp": NOW - age_days * DAY,
    }


class TestFinalEngine(unittest.TestCase):
    """四能力完整"""

    def test_four_capabilities(self):
        eng = MemoryStabilizationEngine(enabled=True)
        recs = [
            _rec("a", lesson="成功完成"),
            _rec("b", lesson="成功完成"),
            _rec("c", lesson="失败告终"),
            _rec("d", value=0.2, age_days=200),
        ]
        r = eng.stabilize(recs)
        self.assertGreaterEqual(
            len(r["compression"]["merged"]), 1,
        )
        self.assertGreaterEqual(
            len(r["conflicts"]["conflicts"]), 1,
        )
        self.assertGreaterEqual(
            len(r["prune_candidates"]["candidates"]), 1,
        )
        self.assertEqual(len(r["evaluation"]), 4)

    def test_audit_full_trace(self):
        eng = MemoryStabilizationEngine(enabled=True)
        recs = [
            _rec("a", lesson="成功完成"),
            _rec("b", lesson="成功完成"),
        ]
        eng.stabilize(recs)
        report = eng.audit_report()
        by = report["stats"]["by_action"]
        self.assertGreaterEqual(by.get("compress", 0), 1)
        for entry in report["recent"]:
            self.assertIn("reason", entry)
            self.assertIn("record_ids", entry)

    def test_prune_execute_trace(self):
        eng = MemoryStabilizationEngine(enabled=True)
        removed = []

        def forget(rid):
            removed.append(rid)
            return True

        recs = [_rec("a", value=0.2, age_days=200)]
        eng.prune_execute(["a"], forget, records=recs)
        report = eng.audit_report()
        self.assertGreaterEqual(
            report["stats"]["by_action"].get("prune", 0), 1,
        )

    def test_conflict_trace(self):
        eng = MemoryStabilizationEngine(enabled=True)
        recs = [
            _rec("a", lesson="成功"),
            _rec("b", lesson="失败"),
        ]
        eng.detect_conflicts(recs)
        report = eng.audit_report()
        self.assertGreaterEqual(
            report["stats"]["by_action"].get("conflict", 0), 1,
        )

    def test_evaluate_trace(self):
        eng = MemoryStabilizationEngine(enabled=True)
        eng.evaluate(_rec("a", value=0.5))
        report = eng.audit_report()
        self.assertGreaterEqual(
            report["stats"]["by_action"].get("evaluate", 0), 1,
        )


class TestFinalAudit(unittest.TestCase):
    """审计查询细节"""

    def test_replay_order_newest_first(self):
        a = StabilizationAudit()
        a.record("compress", ["r1"], "第一")
        a.record("prune", ["r2"], "第二")
        replay = a.replay()
        self.assertEqual(replay[0]["action"], "prune")
        self.assertEqual(replay[1]["action"], "compress")

    def test_query_action_filter(self):
        a = StabilizationAudit()
        a.record("compress", ["r1"])
        a.record("prune", ["r2"])
        a.record("compress", ["r3"])
        hits = a.query(action="compress")
        self.assertEqual(len(hits), 2)

    def test_audit_id_unique(self):
        a = StabilizationAudit()
        a.record("compress", ["r1"])
        a.record("compress", ["r2"])
        ids = [e["audit_id"] for e in a.replay()]
        self.assertEqual(len(set(ids)), 2)

    def test_timestamp_present(self):
        a = StabilizationAudit()
        entry = a.record("compress", ["r1"])
        self.assertGreater(entry["timestamp"], 0)


class TestFinalService(unittest.TestCase):
    """Service 端到端"""

    def _svc(self):
        svc = EmbodiedService()
        svc.load_config({
            "embodied_enabled": True,
            "companion_enabled": True,
        })
        return svc

    def test_full_flow(self):
        svc = self._svc()
        store = svc.companion._experience._store
        for i, spec in enumerate([
            {"trigger": "拾取", "lesson": "成功完成拾取",
             "value": 0.8, "timestamp": NOW},
            {"trigger": "拾取", "lesson": "成功完成拾取",
             "value": 0.8, "timestamp": NOW},
            {"trigger": "拾取", "lesson": "失败无法拾取",
             "value": 0.8, "timestamp": NOW},
            {"trigger": "杂项", "lesson": "低价值琐事",
             "value": 0.2, "timestamp": NOW - 200 * DAY},
        ]):
            from backend.embodied.companion.experience import (
                ExperienceRecord,
            )
            store.store(ExperienceRecord(
                type="interaction", trigger=spec["trigger"],
                lesson=spec["lesson"], value=spec["value"],
                timestamp=spec["timestamp"],
            ))
        r = svc.companion_memory_stabilize()
        self.assertEqual(r["total"], 4)
        self.assertGreaterEqual(
            len(r["compression"]["merged_from"]), 1,
        )
        self.assertGreaterEqual(
            len(r["conflicts"]["conflicts"]), 1,
        )
        # 显式淘汰低价值
        ids = [c["record_id"]
               for c in r["prune_candidates"]["candidates"]]
        if ids:
            ex = svc.companion_memory_prune_execute(ids)
            self.assertGreaterEqual(ex["removed"], 1)
        # 健康联动
        health = svc.companion_health()
        self.assertGreaterEqual(
            health["memory"]["stabilization"]["audit_total"], 1,
        )

    def test_stabilize_stats(self):
        svc = self._svc()
        r = svc.companion_memory_stabilization_stats()
        self.assertEqual(r["mode"], "rule_based")
        self.assertIn("audit", r)

    def test_health_compat(self):
        svc = self._svc()
        r = svc.companion_health()
        self.assertEqual(r["mode"], "rule_based")
        for dim in ("cognitive", "memory", "growth", "safety"):
            self.assertIn(dim, r)


if __name__ == "__main__":
    unittest.main()
