"""
YHLZ Embodied AI V6.6 - 成长闭环单元测试 (Growth Cycle)

覆盖:
    - 触发检查 (时间/事件/手动)
    - 完整闭环 (经历 → 反思 → 建议 → 评估 → 待审批)
    - 待审批队列 (应用永远需人工)
    - 审批决策 (批准仅标记, 不自动应用)
    - 自动行为审计
"""
import threading
import time
import unittest

from backend.embodied.companion.growth import (
    CycleError,
    CYCLE_STATUS,
    CYCLE_TRIGGERS,
    GrowthCycleEngine,
    GrowthEvaluator,
    GrowthProposal,
    PENDING_DECISIONS,
)
from backend.embodied.companion.reflection import (
    CognitiveReflectionEngine,
)


def make_records(n_success=4, n_fail=2):
    records = []
    for i in range(n_success):
        records.append({
            "id": f"s{i}", "type": "improvement",
            "trigger": "生成工程Prompt", "result": "成功",
            "timestamp": time.time() - i * 86400,
        })
    for i in range(n_fail):
        records.append({
            "id": f"f{i}", "type": "failure",
            "trigger": "拾取物体", "result": "位置不匹配",
            "timestamp": time.time() - i * 86400,
        })
    return records


def make_engine(records=None, **over):
    cfg = {
        "reflection": CognitiveReflectionEngine(),
        "proposal": GrowthProposal(),
        "evaluator": GrowthEvaluator(),
        "records_fn": lambda: records if records is not None
        else make_records(),
    }
    cfg.update(over)
    return GrowthCycleEngine(**cfg)


class TestTriggerCheck(unittest.TestCase):
    """触发检查"""

    def test_time_trigger(self):
        engine = make_engine()
        engine._last_run = time.time() - 2 * 86400
        r = engine.check(experience_count=10, now=time.time())
        self.assertTrue(r["triggered"])
        self.assertTrue(any("时间" in x for x in r["reasons"]))

    def test_event_trigger(self):
        engine = make_engine()
        engine._last_experience_count = 3
        r = engine.check(experience_count=10, now=time.time())
        self.assertTrue(r["triggered"])
        self.assertTrue(any("事件" in x for x in r["reasons"]))

    def test_both_triggers(self):
        engine = make_engine()
        engine._last_run = time.time() - 3 * 86400
        engine._last_experience_count = 3
        r = engine.check(experience_count=10, now=time.time())
        self.assertEqual(len(r["reasons"]), 2)

    def test_no_trigger(self):
        engine = make_engine()
        engine._last_run = time.time()
        engine._last_experience_count = 10
        r = engine.check(experience_count=10, now=time.time())
        self.assertFalse(r["triggered"])
        self.assertEqual(r["reasons"], [])

    def test_disabled_check(self):
        engine = make_engine(enabled=False)
        engine._last_run = time.time() - 10 * 86400
        r = engine.check(experience_count=100, now=time.time())
        self.assertFalse(r["triggered"])

    def test_time_threshold_exact(self):
        engine = make_engine(cycle_days=1)
        engine._last_run = time.time() - 86400
        r = engine.check(experience_count=0, now=time.time())
        self.assertTrue(r["triggered"])

    def test_event_threshold_exact(self):
        engine = make_engine(min_experience_delta=5)
        engine._last_experience_count = 5
        r = engine.check(experience_count=10, now=time.time())
        self.assertTrue(r["triggered"])

    def test_event_below_threshold(self):
        engine = make_engine(min_experience_delta=5)
        engine._last_experience_count = 7
        r = engine.check(experience_count=10, now=time.time())
        self.assertFalse(r["triggered"])

    def test_mode_rule_based(self):
        r = make_engine().check(experience_count=0)
        self.assertEqual(r["mode"], "rule_based")


class TestRunCycle(unittest.TestCase):
    """运行闭环"""

    def test_manual_run_completed(self):
        engine = make_engine()
        r = engine.run(trigger="manual")
        self.assertEqual(r["cycle"]["status"], "completed")
        self.assertEqual(r["cycle"]["trigger"], "manual")

    def test_cycle_structure(self):
        engine = make_engine()
        r = engine.run(trigger="manual")
        cycle = r["cycle"]
        for key in ("id", "start_time", "trigger",
                    "experience_count", "proposal_count",
                    "status"):
            self.assertIn(key, cycle)
        self.assertTrue(cycle["id"].startswith("gc_"))

    def test_cycle_experience_count(self):
        engine = make_engine(records=make_records(6, 2))
        r = engine.run(trigger="manual")
        self.assertEqual(r["cycle"]["experience_count"], 8)

    def test_cycle_proposal_count(self):
        engine = make_engine()
        r = engine.run(trigger="manual")
        self.assertGreater(r["cycle"]["proposal_count"], 0)

    def test_reflection_present(self):
        engine = make_engine()
        r = engine.run(trigger="manual")
        self.assertIn("report_id", r["reflection"])
        self.assertIn("summary", r["reflection"])

    def test_proposals_present(self):
        engine = make_engine()
        r = engine.run(trigger="manual")
        self.assertGreater(len(r["proposals"]), 0)

    def test_evaluations_present(self):
        engine = make_engine()
        r = engine.run(trigger="manual")
        self.assertEqual(len(r["evaluations"]),
                         len(r["proposals"]))

    def test_pending_created(self):
        engine = make_engine()
        r = engine.run(trigger="manual")
        self.assertGreater(r["pending_count"], 0)
        self.assertGreater(r["cycle"]["proposal_count"], 0)

    def test_pending_structure(self):
        engine = make_engine()
        engine.run(trigger="manual")
        p = engine.pending()
        item = p["items"][0]
        for key in ("pending_id", "proposal", "evaluation",
                    "decision", "cycle_id", "created_at"):
            self.assertIn(key, item)
        self.assertTrue(item["pending_id"].startswith("pc_"))
        self.assertEqual(item["decision"], "pending")

    def test_auto_run_no_trigger(self):
        engine = make_engine(records=[])
        r = engine.run(trigger="auto")
        self.assertIsNone(r["cycle"])
        self.assertIn("无触发", r["reason"])

    def test_auto_run_time_trigger(self):
        engine = make_engine()
        engine._last_run = time.time() - 2 * 86400
        r = engine.run(trigger="auto")
        self.assertEqual(r["cycle"]["trigger"], "time")

    def test_auto_run_event_trigger(self):
        engine = make_engine(records=make_records(6, 2))
        r = engine.run(trigger="auto")
        self.assertEqual(r["cycle"]["trigger"], "event")

    def test_invalid_trigger(self):
        engine = make_engine()
        with self.assertRaises(CycleError):
            engine.run(trigger="bogus")

    def test_disabled_run(self):
        engine = make_engine(enabled=False)
        r = engine.run(trigger="manual")
        self.assertIsNone(r["cycle"])
        self.assertIn("停用", r["reason"])

    def test_audited_flag(self):
        engine = make_engine()
        r = engine.run(trigger="manual")
        self.assertTrue(r["audited"])

    def test_run_after_run_event_reset(self):
        engine = make_engine(records=make_records(6, 2))
        engine.run(trigger="manual")
        r = engine.check(experience_count=8)
        self.assertFalse(r["triggered"])

    def test_run_after_run_time_reset(self):
        engine = make_engine()
        engine.run(trigger="manual")
        r = engine.check(experience_count=0)
        self.assertFalse(r["triggered"])

    def test_multi_cycles_cumulative(self):
        engine = make_engine()
        engine.run(trigger="manual")
        engine.run(trigger="manual")
        self.assertEqual(engine.stats()["cycle_count"], 2)


class TestTolerance(unittest.TestCase):
    """异常容错"""

    def test_no_components(self):
        engine = GrowthCycleEngine()
        r = engine.run(trigger="manual")
        self.assertEqual(r["cycle"]["status"], "completed")
        self.assertEqual(r["pending_count"], 0)

    def test_reflection_error_tolerated(self):
        class BoomReflection:
            def analyze(self, records, identity):
                raise RuntimeError("boom")

        engine = make_engine(reflection=BoomReflection())
        r = engine.run(trigger="manual")
        self.assertIn("error", r["reflection"])
        self.assertEqual(r["cycle"]["status"], "completed")

    def test_proposal_error_tolerated(self):
        class BoomProposal:
            def generate(self, report):
                raise RuntimeError("boom")

        engine = make_engine(proposal=BoomProposal())
        r = engine.run(trigger="manual")
        self.assertEqual(r["proposals"], [])
        self.assertEqual(r["cycle"]["status"], "completed")

    def test_evaluator_error_tolerated(self):
        class BoomEvaluator:
            def evaluate(self, proposal, identity):
                raise RuntimeError("boom")

        engine = make_engine(evaluator=BoomEvaluator())
        r = engine.run(trigger="manual")
        for e in r["evaluations"]:
            self.assertFalse(e["approved"])
        self.assertEqual(r["cycle"]["status"], "completed")

    def test_records_fn_error_tolerated(self):
        def boom():
            raise RuntimeError("boom")

        engine = make_engine(records_fn=boom)
        r = engine.run(trigger="manual")
        self.assertEqual(r["cycle"]["status"], "completed")
        self.assertEqual(r["cycle"]["experience_count"], 0)

    def test_audit_none_ok(self):
        engine = make_engine(audit=None)
        r = engine.run(trigger="manual")
        self.assertEqual(r["cycle"]["status"], "completed")

    def test_audit_error_tolerated(self):
        class BoomAudit:
            def record(self, **kwargs):
                raise RuntimeError("boom")

        engine = make_engine(audit=BoomAudit())
        r = engine.run(trigger="manual")
        self.assertEqual(r["cycle"]["status"], "completed")


class TestPendingDecisions(unittest.TestCase):
    """待审批决策"""

    def test_approve_marks_only(self):
        engine = make_engine()
        engine.run(trigger="manual")
        pid = engine.pending()["items"][0]["pending_id"]
        r = engine.decide(pid, "approve")
        self.assertEqual(r["decision"], "approve")
        self.assertFalse(r["applied"])

    def test_reject(self):
        engine = make_engine()
        engine.run(trigger="manual")
        pid = engine.pending()["items"][0]["pending_id"]
        r = engine.decide(pid, "reject")
        self.assertEqual(r["decision"], "reject")

    def test_decide_updates_pending_state(self):
        engine = make_engine()
        engine.run(trigger="manual")
        pid = engine.pending()["items"][0]["pending_id"]
        engine.decide(pid, "approve")
        item = next(
            i for i in engine.pending()["items"]
            if i["pending_id"] == pid
        )
        self.assertEqual(item["decision"], "approve")

    def test_approve_never_auto_apply(self):
        engine = make_engine()
        engine.run(trigger="manual")
        pid = engine.pending()["items"][0]["pending_id"]
        engine.decide(pid, "approve")
        stats = engine.stats()
        self.assertEqual(stats["pending_decisions"]["approve"],
                         1)
        self.assertEqual(stats["by_status"]["completed"], 1)

    def test_approve_reason_note(self):
        engine = make_engine()
        engine.run(trigger="manual")
        pid = engine.pending()["items"][0]["pending_id"]
        r = engine.decide(pid, "approve", reason="用户确认")
        self.assertEqual(r["reason"], "用户确认")

    def test_missing_pending_id(self):
        engine = make_engine()
        with self.assertRaises(CycleError):
            engine.decide("pc_missing", "approve")

    def test_invalid_decision(self):
        engine = make_engine()
        engine.run(trigger="manual")
        pid = engine.pending()["items"][0]["pending_id"]
        with self.assertRaises(CycleError):
            engine.decide(pid, "maybe")

    def test_decisions_whitelist(self):
        self.assertEqual(PENDING_DECISIONS,
                         ["approve", "reject"])

    def test_decide_records_audit(self):
        audit = __import__(
            "backend.embodied.companion.growth.growth_audit",
            fromlist=["GrowthAudit"],
        ).GrowthAudit()
        engine = make_engine(audit=audit)
        engine.run(trigger="manual")
        pid = engine.pending()["items"][0]["pending_id"]
        engine.decide(pid, "approve")
        report = audit.report(limit=0)
        decisions = report["by_decision"]
        self.assertIn("cycle_approve", decisions)


class TestMaxPending(unittest.TestCase):
    """待审批上限"""

    def test_max_pending_cap(self):
        engine = make_engine(max_pending=1)
        engine.run(trigger="manual")
        self.assertEqual(engine.stats()["pending_count"], 1)

    def test_max_pending_zero_blocks(self):
        engine = make_engine(max_pending=0)
        engine.run(trigger="manual")
        self.assertEqual(engine.stats()["pending_count"], 0)


class TestConstructionValidation(unittest.TestCase):
    """构造校验"""

    def test_cycle_days_zero(self):
        with self.assertRaises(CycleError):
            GrowthCycleEngine(cycle_days=0)

    def test_cycle_days_negative(self):
        with self.assertRaises(CycleError):
            GrowthCycleEngine(cycle_days=-1)

    def test_min_delta_zero(self):
        with self.assertRaises(CycleError):
            GrowthCycleEngine(min_experience_delta=0)

    def test_min_delta_negative(self):
        with self.assertRaises(CycleError):
            GrowthCycleEngine(min_experience_delta=-3)


class TestStats(unittest.TestCase):
    """统计"""

    def test_initial_stats(self):
        engine = make_engine()
        stats = engine.stats()
        self.assertEqual(stats["cycle_count"], 0)
        self.assertEqual(stats["run_count"], 0)
        self.assertEqual(stats["pending_count"], 0)

    def test_stats_after_runs(self):
        engine = make_engine()
        engine.run(trigger="manual")
        engine.run(trigger="manual")
        stats = engine.stats()
        self.assertEqual(stats["cycle_count"], 2)
        self.assertEqual(stats["run_count"], 2)
        self.assertEqual(stats["by_status"]["completed"], 2)

    def test_stats_trigger_reasons(self):
        engine = make_engine()
        engine.run(trigger="manual")
        stats = engine.stats()
        self.assertEqual(stats["trigger_reasons"]["manual"], 1)

    def test_stats_thresholds(self):
        engine = make_engine(cycle_days=2,
                             min_experience_delta=7,
                             max_pending=9)
        t = engine.stats()["thresholds"]
        self.assertEqual(t["cycle_days"], 2)
        self.assertEqual(t["min_experience_delta"], 7)
        self.assertEqual(t["max_pending"], 9)

    def test_stats_enabled(self):
        self.assertTrue(make_engine().stats()["enabled"])
        self.assertFalse(make_engine(
            enabled=False).stats()["enabled"])

    def test_pending_limit(self):
        engine = make_engine()
        engine.run(trigger="manual")
        self.assertGreater(engine.pending()["pending_count"], 0)
        self.assertEqual(engine.pending(limit=1)[
            "pending_count"], 1)

    def test_clear(self):
        engine = make_engine()
        engine.run(trigger="manual")
        n = engine.clear()
        self.assertGreater(n, 0)
        stats = engine.stats()
        self.assertEqual(stats["cycle_count"], 0)
        self.assertEqual(stats["pending_count"], 0)

    def test_constants(self):
        self.assertEqual(CYCLE_STATUS,
                         ["running", "completed", "failed"])
        self.assertEqual(CYCLE_TRIGGERS,
                         ["time", "event", "manual"])


class TestAuditIntegration(unittest.TestCase):
    """审计集成"""

    def test_run_records_audit(self):
        audit = __import__(
            "backend.embodied.companion.growth.growth_audit",
            fromlist=["GrowthAudit"],
        ).GrowthAudit()
        engine = make_engine(audit=audit)
        engine.run(trigger="manual")
        report = audit.report(limit=0)
        self.assertIn("cycle_completed",
                      report["by_decision"])
        self.assertGreater(report["total"], 0)

    def test_audit_entry_structure(self):
        audit = __import__(
            "backend.embodied.companion.growth.growth_audit",
            fromlist=["GrowthAudit"],
        ).GrowthAudit()
        engine = make_engine(audit=audit)
        engine.run(trigger="manual")
        entry = audit.report(limit=0)["recent"][0]
        for key in ("audit_id", "proposal_id", "before",
                    "decision", "after", "time"):
            self.assertIn(key, entry)


class TestThreadSafety(unittest.TestCase):
    """线程安全"""

    def test_concurrent_run(self):
        engine = make_engine()
        errors = []

        def work():
            try:
                for _ in range(5):
                    engine.run(trigger="manual")
            except Exception as e:  # pragma: no cover
                errors.append(e)

        threads = [threading.Thread(target=work)
                   for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        self.assertEqual(engine.stats()["cycle_count"], 20)

    def test_concurrent_check(self):
        engine = make_engine()
        errors = []

        def work():
            try:
                for _ in range(20):
                    engine.check(experience_count=1)
            except Exception as e:  # pragma: no cover
                errors.append(e)

        threads = [threading.Thread(target=work)
                   for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
