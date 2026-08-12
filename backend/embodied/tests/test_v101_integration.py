"""
YHLZ Embodied AI V10.1 - 记忆稳定化集成测试 (Service Integration)

覆盖:
    - Service API: companion_memory_stabilize / prune_candidates /
      prune_execute / stats / audit
    - 热机健康指标联动 (Memory 维度 stabilization 统计)
    - 兼容性 (既有 API 不受影响)
"""
import time
import unittest

from backend.embodied.companion.experience import ExperienceRecord
from backend.embodied.service import EmbodiedService

NOW = time.time()
DAY = 86400


def setup_service(**extra):
    cfg = {
        "embodied_enabled": True,
        "companion_enabled": True,
    }
    cfg.update(extra)
    svc = EmbodiedService()
    svc.load_config(cfg)
    return svc


def seed_records(svc, specs):
    """向经历存储注入记录"""
    store = svc.companion._experience._store
    for spec in specs:
        store.store(ExperienceRecord(
            type=spec.get("type", "interaction"),
            source=spec.get("source", "test"),
            trigger=spec.get("trigger", "t"),
            lesson=spec.get("lesson", ""),
            value=spec.get("value", 0.5),
            confidence=spec.get("confidence", 0.5),
            timestamp=spec.get("timestamp", NOW),
        ))
    return store


class TestServiceStabilize(unittest.TestCase):
    """Service 稳定化 API"""

    def test_stabilize_empty(self):
        svc = setup_service()
        r = svc.companion_memory_stabilize()
        self.assertEqual(r["mode"], "rule_based")
        self.assertIn("compression", r)
        self.assertIn("conflicts", r)

    def test_stabilize_with_duplicates(self):
        svc = setup_service()
        seed_records(svc, [
            {"trigger": "拾取", "lesson": "成功完成拾取"},
            {"trigger": "拾取", "lesson": "成功完成拾取"},
        ])
        r = svc.companion_memory_stabilize()
        self.assertEqual(len(r["compression"]["merged_from"]), 1)

    def test_stabilize_with_conflict(self):
        svc = setup_service()
        seed_records(svc, [
            {"trigger": "拾取", "lesson": "成功完成"},
            {"trigger": "拾取", "lesson": "失败告终"},
        ])
        r = svc.companion_memory_stabilize()
        self.assertEqual(len(r["conflicts"]["conflicts"]), 1)

    def test_stabilize_with_candidates(self):
        svc = setup_service()
        seed_records(svc, [
            {"trigger": "杂项", "lesson": "低价值",
             "value": 0.2, "timestamp": NOW - 200 * DAY},
        ])
        r = svc.companion_memory_stabilize()
        self.assertEqual(
            len(r["prune_candidates"]["candidates"]), 1,
        )

    def test_stabilize_evaluation_count(self):
        svc = setup_service()
        seed_records(svc, [
            {"trigger": "t1", "lesson": "a"},
            {"trigger": "t2", "lesson": "b"},
        ])
        r = svc.companion_memory_stabilize()
        self.assertEqual(len(r["evaluation"]), 2)

    def test_stabilize_confirmed_weights(self):
        svc = setup_service()
        seed_records(svc, [
            {"trigger": "t1", "lesson": "a", "value": 0.5},
        ])
        r = svc.companion_memory_stabilize()
        self.assertEqual(r["evaluation"][0]["weight"], 0.5)

    def test_stabilize_with_extra_records(self):
        svc = setup_service()
        recs = [
            {"id": "x1", "trigger": "t", "lesson": "成功",
             "value": 0.5, "confidence": 0.5,
             "timestamp": NOW},
            {"id": "x2", "trigger": "t", "lesson": "失败",
             "value": 0.5, "confidence": 0.5,
             "timestamp": NOW},
        ]
        r = svc.companion_memory_stabilize(records=recs)
        self.assertEqual(r["total"], 2)
        self.assertEqual(len(r["conflicts"]["conflicts"]), 1)

    def test_stabilize_manual_confirmed(self):
        svc = setup_service()
        recs = [
            {"id": "x1", "trigger": "t", "lesson": "低价值",
             "value": 0.2, "confidence": 0.1,
             "timestamp": NOW - 200 * DAY},
        ]
        r = svc.companion_memory_stabilize(
            records=recs, confirmed_ids=["x1"],
        )
        self.assertEqual(r["prune_candidates"]["candidates"], [])

    def test_stabilize_repeatable(self):
        svc = setup_service()
        seed_records(svc, [
            {"trigger": "t", "lesson": "成功"},
            {"trigger": "t", "lesson": "失败"},
        ])
        r1 = svc.companion_memory_stabilize()
        r2 = svc.companion_memory_stabilize()
        self.assertEqual(
            len(r1["conflicts"]["conflicts"]),
            len(r2["conflicts"]["conflicts"]),
        )


class TestServicePrune(unittest.TestCase):
    """Service 淘汰 API"""

    def test_prune_candidates_api(self):
        svc = setup_service()
        seed_records(svc, [
            {"trigger": "杂项", "lesson": "低价值",
             "value": 0.2, "timestamp": NOW - 200 * DAY},
        ])
        r = svc.companion_memory_prune_candidates()
        self.assertEqual(len(r["candidates"]), 1)

    def test_prune_execute_api(self):
        svc = setup_service()
        store = seed_records(svc, [
            {"trigger": "杂项", "lesson": "低价值",
             "value": 0.2, "timestamp": NOW - 200 * DAY},
        ])
        rec = store.all()[0]
        r = svc.companion_memory_prune_execute([rec.id])
        self.assertEqual(r["removed"], 1)
        self.assertEqual(len(store.all()), 0)

    def test_prune_execute_unknown_id(self):
        svc = setup_service()
        r = svc.companion_memory_prune_execute(["nope"])
        self.assertEqual(r["removed"], 0)
        self.assertGreaterEqual(r["not_found"], 0)

    def test_prune_execute_audited(self):
        svc = setup_service()
        store = seed_records(svc, [
            {"trigger": "杂项", "lesson": "低价值",
             "value": 0.2, "timestamp": NOW - 200 * DAY},
        ])
        rec = store.all()[0]
        svc.companion_memory_prune_execute([rec.id])
        report = svc.companion_memory_stabilization_audit()
        self.assertGreaterEqual(
            report["stats"]["by_action"].get("prune", 0), 1,
        )

    def test_prune_execute_empty(self):
        svc = setup_service()
        r = svc.companion_memory_prune_execute([])
        self.assertEqual(r["requested"], 0)

    def test_prune_candidates_no_delete(self):
        svc = setup_service()
        store = seed_records(svc, [
            {"trigger": "杂项", "lesson": "低价值",
             "value": 0.2, "timestamp": NOW - 200 * DAY},
        ])
        svc.companion_memory_prune_candidates()
        self.assertEqual(len(store.all()), 1)


class TestServiceStats(unittest.TestCase):
    """Service 统计与审计"""

    def test_stats_api(self):
        svc = setup_service()
        r = svc.companion_memory_stabilization_stats()
        self.assertIn("compressor", r)
        self.assertIn("pruner", r)
        self.assertIn("weighter", r)
        self.assertIn("conflict_detector", r)
        self.assertIn("audit", r)

    def test_audit_api(self):
        svc = setup_service()
        r = svc.companion_memory_stabilization_audit()
        self.assertIn("stats", r)
        self.assertIn("recent", r)

    def test_audit_limit(self):
        svc = setup_service()
        seed_records(svc, [
            {"trigger": "t", "lesson": "成功"},
            {"trigger": "t", "lesson": "失败"},
        ])
        svc.companion_memory_stabilize()
        r = svc.companion_memory_stabilization_audit(limit=1)
        self.assertLessEqual(len(r["recent"]), 1)


class TestHealthLink(unittest.TestCase):
    """热机健康指标联动 (P1)"""

    def test_health_stabilization_field(self):
        svc = setup_service()
        r = svc.companion_health()
        self.assertIn("stabilization", r["memory"])
        self.assertIn("compress_count", r["memory"]["stabilization"])
        self.assertIn("prune_count", r["memory"]["stabilization"])
        self.assertIn("conflict_count", r["memory"]["stabilization"])

    def test_health_after_stabilize(self):
        svc = setup_service()
        seed_records(svc, [
            {"trigger": "拾取", "lesson": "成功完成拾取"},
            {"trigger": "拾取", "lesson": "成功完成拾取"},
        ])
        svc.companion_memory_stabilize()
        r = svc.companion_health()
        self.assertGreaterEqual(
            r["memory"]["stabilization"]["compress_count"], 1,
        )

    def test_health_after_prune(self):
        svc = setup_service()
        store = seed_records(svc, [
            {"trigger": "杂项", "lesson": "低价值",
             "value": 0.2, "timestamp": NOW - 200 * DAY},
        ])
        rec = store.all()[0]
        svc.companion_memory_prune_execute([rec.id])
        r = svc.companion_health()
        self.assertGreaterEqual(
            r["memory"]["stabilization"]["prune_count"], 1,
        )

    def test_health_after_conflict(self):
        svc = setup_service()
        seed_records(svc, [
            {"trigger": "t", "lesson": "成功"},
            {"trigger": "t", "lesson": "失败"},
        ])
        svc.companion_memory_stabilize()
        r = svc.companion_health()
        self.assertGreaterEqual(
            r["memory"]["stabilization"]["conflict_count"], 1,
        )

    def test_health_still_works(self):
        svc = setup_service()
        r = svc.companion_health()
        self.assertEqual(r["mode"], "rule_based")
        self.assertIn("overall", r)

    def test_health_audit_total(self):
        svc = setup_service()
        seed_records(svc, [
            {"trigger": "t", "lesson": "成功"},
            {"trigger": "t", "lesson": "失败"},
        ])
        svc.companion_memory_stabilize()
        r = svc.companion_health()
        self.assertGreaterEqual(
            r["memory"]["stabilization"]["audit_total"], 1,
        )


class TestCompatibility(unittest.TestCase):
    """兼容性 (热机冻结)"""

    def test_health_api_unchanged(self):
        svc = setup_service()
        r = svc.companion_health()
        for dim in ("cognitive", "memory", "growth", "safety"):
            self.assertIn(dim, r)
        self.assertIn("overall", r)

    def test_meta_cognition_ok(self):
        svc = setup_service()
        r = svc.companion_meta_cognition_monitor("任务")
        self.assertIn("monitor_id", r)

    def test_experience_stats_ok(self):
        svc = setup_service()
        seed_records(svc, [{"trigger": "t", "lesson": "a"}])
        r = svc.companion_experience_stats()
        self.assertIn("mode", r)

    def test_status_version(self):
        svc = setup_service()
        r = svc.companion_status()
        self.assertEqual(r["version"], "9.5.0")

    def test_persistence_ok(self):
        import os
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            svc = setup_service(
                companion_persistence_enabled=True,
                companion_persistence_path=os.path.join(
                    td, "state.json",
                ),
            )
            r = svc.companion_persistence_save()
            self.assertGreaterEqual(r, 0)


if __name__ == "__main__":
    unittest.main()
