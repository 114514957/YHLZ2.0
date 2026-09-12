"""
YHLZ Embodied AI V5.9 - 创造引擎门面测试 (Creative Engine)

覆盖 (creative_engine.py):
    - 完整闭环: run (发现 → 评估 → 推理 → 提案 → 模拟)
    - 只 CONFIRMED 经验 (认知免疫)
    - 审批流: approve / reject / execute (硬门槛) / record_result
    - 新经验形成 (闭环)
    - 安全保护 (protections)
    - 统计 / 审计 / 持久化 / 异常
"""
import os
import tempfile
import unittest

from backend.embodied.companion.creative import CreativeEngine
from backend.embodied.companion.creative import (
    CreativeEngineError,
)
from backend.embodied.companion.experience import ExperienceManager
from backend.embodied.companion.reflection import (
    ImprovementProposalEngine,
    ReflectionEngine,
)
from backend.embodied.companion.verification import ExperienceVerifier


class CreativeTestBase(unittest.TestCase):
    """基础环境: 制造 CONFIRMED 经验"""

    def setUp(self):
        self.mgr = ExperienceManager()
        self.verifier = ExperienceVerifier()
        self.reflection = ReflectionEngine()
        self.improvement = ImprovementProposalEngine()
        self.engine = CreativeEngine(
            experience_manager=self.mgr,
            verifier=self.verifier,
            reflection_engine=self.reflection,
            improvement_engine=self.improvement,
        )

    def add_confirmed(self, trigger="生成工程Prompt", n=3,
                      result="成功"):
        """添加并确认 n 条经历"""
        ids = []
        for _ in range(n):
            rec = self.mgr.store_from_event(
                success=True, trigger=trigger,
                source="creative_test", action="a", result=result,
            )
            ids.append(rec["id"])
        for rid in ids:
            for _ in range(3):
                self.verifier.verify(rid, evidence_count=2,
                                     contradictions=0)
        return ids

    def add_unconfirmed(self, trigger="未验证需求", n=3):
        """只添加不验证 (不应进入创造)"""
        for _ in range(n):
            self.mgr.store_from_event(
                success=True, trigger=trigger,
                source="creative_test", action="a", result="成功",
            )


class TestEngineInit(CreativeTestBase):
    """初始化"""

    def test_default_init(self):
        e = CreativeEngine()
        self.assertIsNotNone(e)

    def test_bridges_created(self):
        e = CreativeEngine()
        self.assertIsNotNone(e.experience_bridge)
        self.assertIsNotNone(e.reflection_bridge)
        self.assertIsNotNone(e.approval_bridge)

    def test_components_created(self):
        e = CreativeEngine()
        self.assertIsNotNone(e.detector)
        self.assertIsNotNone(e.evaluator)
        self.assertIsNotNone(e.reasoning_engine)
        self.assertIsNotNone(e.generator)
        self.assertIsNotNone(e.simulator)
        self.assertIsNotNone(e.memory)
        self.assertIsNotNone(e.audit)

    def test_config_applied(self):
        e = CreativeEngine(config={
            "companion_creative_value_threshold": 0.9,
        })
        self.assertEqual(e.evaluator.stats()["mode"], "rule_based")

    def test_disabled_engine(self):
        e = CreativeEngine(enabled=False)
        with self.assertRaises(CreativeEngineError):
            e.detect()

    def test_run_disabled(self):
        e = CreativeEngine(enabled=False)
        with self.assertRaises(CreativeEngineError):
            e.run()


class TestRunLoop(CreativeTestBase):
    """完整闭环"""

    def test_run_empty(self):
        r = self.engine.run()
        self.assertEqual(r["summary"]["opportunity_count"], 0)
        self.assertFalse(r["auto_executed"])

    def test_run_with_confirmed(self):
        self.add_confirmed()
        r = self.engine.run()
        self.assertGreaterEqual(r["summary"]["opportunity_count"], 1)

    def test_run_proposal_flow(self):
        self.add_confirmed()
        r = self.engine.run()
        self.assertGreaterEqual(r["summary"]["evaluation_count"], 1)
        self.assertGreaterEqual(r["summary"]["proposal_count"], 1)
        self.assertGreaterEqual(r["summary"]["simulation_count"], 1)

    def test_run_not_executing(self):
        """run 不自动执行 (Proposal 禁止自动执行)"""
        self.add_confirmed()
        r = self.engine.run()
        self.assertFalse(r["auto_executed"])
        st = self.engine.memory.stats()
        self.assertEqual(st["by_status"].get("EXECUTED", 0), 0)

    def test_run_ignores_unconfirmed(self):
        """未验证经验不产生机会"""
        self.add_unconfirmed()
        r = self.engine.run()
        self.assertEqual(r["summary"]["opportunity_count"], 0)

    def test_run_proposals_are_pending(self):
        self.add_confirmed()
        r = self.engine.run()
        for p in r["proposals"]:
            self.assertEqual(p["status"], "PENDING")

    def test_run_simulations_attached(self):
        self.add_confirmed()
        r = self.engine.run()
        for p in r["proposals"]:
            sim = self.engine.memory.get(p["proposal_id"])["simulation"]
            self.assertIsNotNone(sim)

    def test_run_summary_keys(self):
        r = self.engine.run()
        for key in ("opportunity_count", "evaluation_count",
                    "proposal_count", "simulation_count"):
            self.assertIn(key, r["summary"])

    def test_run_mode(self):
        r = self.engine.run()
        self.assertEqual(r["mode"], "rule_based")


class TestDetectEvaluate(CreativeTestBase):
    """检测与评估"""

    def test_detect(self):
        self.add_confirmed()
        opps = self.engine.detect()
        self.assertGreaterEqual(len(opps), 1)
        self.assertTrue(opps[0]["opportunity_id"].startswith("opp_"))

    def test_detect_audit_traced(self):
        self.add_confirmed()
        self.engine.detect()
        report = self.engine.audit_report()
        self.assertGreaterEqual(report["by_action"].get("detect", 0), 1)

    def test_evaluate(self):
        self.add_confirmed()
        opps = self.engine.detect()
        ev = self.engine.evaluate(opps[0]["opportunity_id"])
        self.assertIn(ev["decision"], ("create", "defer", "reject"))

    def test_evaluate_missing(self):
        with self.assertRaises(CreativeEngineError):
            self.engine.evaluate("opp_none")

    def test_evaluate_audit(self):
        self.add_confirmed()
        opps = self.engine.detect()
        self.engine.evaluate(opps[0]["opportunity_id"])
        report = self.engine.audit_report()
        self.assertGreaterEqual(
            report["by_action"].get("evaluate", 0), 1,
        )

    def test_reason(self):
        self.add_confirmed()
        opps = self.engine.detect()
        r = self.engine.reason(opps[0]["opportunity_id"])
        self.assertGreaterEqual(len(r["paths"]), 1)

    def test_reason_missing(self):
        with self.assertRaises(CreativeEngineError):
            self.engine.reason("opp_none")


class TestProposeSimulate(CreativeTestBase):
    """提案与模拟"""

    def setUp(self):
        super().setUp()
        self.add_confirmed()
        self.opps = self.engine.detect()

    def test_propose(self):
        p = self.engine.propose(self.opps[0]["opportunity_id"])
        self.assertTrue(p["proposal_id"].startswith("cp_"))
        self.assertEqual(p["status"], "PENDING")

    def test_propose_saves_to_memory(self):
        p = self.engine.propose(self.opps[0]["opportunity_id"])
        self.assertEqual(self.engine.memory.get(p["proposal_id"])[
            "proposal_id"], p["proposal_id"])

    def test_propose_audit(self):
        self.engine.propose(self.opps[0]["opportunity_id"])
        report = self.engine.audit_report()
        self.assertGreaterEqual(report["by_action"].get("propose", 0), 1)

    def test_propose_mirror_submitted(self):
        p = self.engine.propose(self.opps[0]["opportunity_id"])
        self.assertIn("improvement_proposal_id", p)

    def test_simulate(self):
        p = self.engine.propose(self.opps[0]["opportunity_id"])
        sim = self.engine.simulate(p["proposal_id"])
        self.assertTrue(sim["simulation_id"].startswith("sim_"))
        self.assertIn(sim["recommendation"],
                      ("proceed", "revise", "abandon"))

    def test_simulate_updates_proposal(self):
        p = self.engine.propose(self.opps[0]["opportunity_id"])
        self.engine.simulate(p["proposal_id"])
        stored = self.engine.memory.get(p["proposal_id"])
        self.assertIsNotNone(stored["simulation"])

    def test_simulate_missing(self):
        with self.assertRaises(CreativeEngineError):
            self.engine.simulate("cp_none")

    def test_propose_missing(self):
        with self.assertRaises(CreativeEngineError):
            self.engine.propose("opp_none")


class TestApprovalFlow(CreativeTestBase):
    """审批流"""

    def setUp(self):
        super().setUp()
        self.add_confirmed()
        self.opps = self.engine.detect()
        self.prop = self.engine.propose(self.opps[0]["opportunity_id"])

    def test_approve(self):
        p = self.engine.approve(self.prop["proposal_id"])
        self.assertEqual(p["status"], "APPROVED")

    def test_approve_audit(self):
        self.engine.approve(self.prop["proposal_id"])
        report = self.engine.audit_report()
        self.assertGreaterEqual(report["by_action"].get("approve", 0), 1)

    def test_execute_requires_approval(self):
        with self.assertRaises(CreativeEngineError):
            self.engine.execute(self.prop["proposal_id"])

    def test_execute_after_approve(self):
        self.engine.approve(self.prop["proposal_id"])
        p = self.engine.execute(self.prop["proposal_id"])
        self.assertEqual(p["status"], "EXECUTED")

    def test_execute_audit(self):
        self.engine.approve(self.prop["proposal_id"])
        self.engine.execute(self.prop["proposal_id"])
        report = self.engine.audit_report()
        self.assertGreaterEqual(report["by_action"].get("execute", 0), 1)

    def test_reject(self):
        p = self.engine.reject(self.prop["proposal_id"], "暂不需要")
        self.assertEqual(p["status"], "REJECTED")
        self.assertEqual(p["reason"], "暂不需要")

    def test_reject_audit(self):
        self.engine.reject(self.prop["proposal_id"])
        report = self.engine.audit_report()
        self.assertGreaterEqual(report["by_action"].get("reject", 0), 1)

    def test_execute_missing(self):
        with self.assertRaises(CreativeEngineError):
            self.engine.execute("cp_none")

    def test_approve_missing(self):
        with self.assertRaises(CreativeEngineError):
            self.engine.approve("cp_none")

    def test_execute_after_reject_invalid(self):
        self.engine.reject(self.prop["proposal_id"])
        with self.assertRaises(CreativeEngineError):
            self.engine.execute(self.prop["proposal_id"])


class TestRecordResult(CreativeTestBase):
    """结果 → 新经验闭环"""

    def setUp(self):
        super().setUp()
        self.add_confirmed()
        self.opps = self.engine.detect()
        self.prop = self.engine.propose(self.opps[0]["opportunity_id"])
        self.engine.approve(self.prop["proposal_id"])
        self.engine.execute(self.prop["proposal_id"])

    def test_record_success(self):
        p = self.engine.record_result(
            self.prop["proposal_id"], True, result="成功",
        )
        self.assertEqual(p["status"], "COMPLETED")
        self.assertTrue(p["success"])

    def test_record_creates_experience(self):
        p = self.engine.record_result(
            self.prop["proposal_id"], True, result="成功",
        )
        self.assertIn("experience_id", p)
        exp = self.mgr.retrieve(p["experience_id"])
        self.assertIsNotNone(exp)
        self.assertEqual(exp["type"], "engineering")

    def test_record_experience_verified(self):
        p = self.engine.record_result(
            self.prop["proposal_id"], True, result="成功",
        )
        state = self.verifier.get(p["experience_id"])
        self.assertIsNotNone(state)
        self.assertEqual(state["status"], "PENDING")

    def test_record_failure(self):
        p = self.engine.record_result(
            self.prop["proposal_id"], False, result="失败",
        )
        self.assertEqual(p["status"], "FAILED")

    def test_record_audit(self):
        self.engine.record_result(
            self.prop["proposal_id"], True, result="成功",
        )
        report = self.engine.audit_report()
        self.assertGreaterEqual(report["by_action"].get("result", 0), 1)

    def test_record_before_execute_invalid(self):
        p = self.engine.propose(self.opps[0]["opportunity_id"])
        with self.assertRaises(CreativeEngineError):
            self.engine.record_result(p["proposal_id"], True)

    def test_record_missing(self):
        with self.assertRaises(CreativeEngineError):
            self.engine.record_result("cp_none", True)


class TestStatsAndProtections(CreativeTestBase):
    """统计与安全保护"""

    def test_stats_structure(self):
        st = self.engine.stats()
        for key in ("mode", "enabled", "opportunities", "evaluations",
                    "reasoning", "proposals", "simulations", "memory",
                    "summary"):
            self.assertIn(key, st)

    def test_stats_summary(self):
        self.add_confirmed()
        self.engine.run()
        st = self.engine.stats()
        s = st["summary"]
        self.assertGreaterEqual(s["opportunity_count"], 1)
        self.assertGreaterEqual(s["confirmed_source_count"], 1)

    def test_protections(self):
        checks = self.engine.protections()
        names = {c["name"] for c in checks}
        self.assertIn("confirmed_only", names)
        self.assertIn("no_auto_execute", names)
        self.assertIn("approval_required", names)
        self.assertIn("no_personality_change", names)
        self.assertIn("verifiable", names)

    def test_protections_all_passed(self):
        for c in self.engine.protections():
            self.assertTrue(c["passed"], c["name"])

    def test_protection_reasons_explainable(self):
        for c in self.engine.protections():
            self.assertTrue(c["reason"])

    def test_status(self):
        st = self.engine.status()
        self.assertEqual(st["version"], "9.5.0")
        self.assertTrue(st["enabled"])
        self.assertEqual(st["mode"], "rule_based")

    def test_audit_report(self):
        r = self.engine.audit_report()
        self.assertEqual(r["mode"], "rule_based")

    def test_clear(self):
        self.add_confirmed()
        self.engine.run()
        cleared = self.engine.clear()
        self.assertEqual(self.engine.stats()["summary"][
            "opportunity_count"], 0)

    def test_clear_counts(self):
        cleared = self.engine.clear()
        for v in cleared.values():
            self.assertGreaterEqual(v, 0)


class TestPersistence(CreativeTestBase):
    """持久化"""

    def setUp(self):
        super().setUp()
        self.tmp = tempfile.mkdtemp(prefix="yhlz_engine_")
        self.path = os.path.join(self.tmp, "creative.jsonl")

    def tearDown(self):
        if os.path.exists(self.path):
            os.remove(self.path)
        os.rmdir(self.tmp)

    def test_persist(self):
        self.add_confirmed()
        opps = self.engine.detect()
        self.engine.propose(opps[0]["opportunity_id"])
        n = self.engine.persist(self.path)
        self.assertEqual(n, 1)
        self.assertTrue(os.path.exists(self.path))

    def test_persist_audit(self):
        self.add_confirmed()
        opps = self.engine.detect()
        self.engine.propose(opps[0]["opportunity_id"])
        self.engine.persist(self.path)
        report = self.engine.audit_report()
        self.assertGreaterEqual(report["by_action"].get("persist", 0), 1)

    def test_load(self):
        self.add_confirmed()
        opps = self.engine.detect()
        self.engine.propose(opps[0]["opportunity_id"])
        self.engine.persist(self.path)
        e2 = CreativeEngine()
        n = e2.load(self.path)
        self.assertEqual(n, 1)
        self.assertGreaterEqual(e2.memory.stats()["total"], 1)

    def test_load_missing_file(self):
        with self.assertRaises(CreativeEngineError) as ctx:
            self.engine.load(self.path)
        self.assertIn("不存在", str(ctx.exception))


class TestIdentityStability(CreativeTestBase):
    """身份稳定 (创造不修改人格)"""

    def test_no_personality_touch(self):
        """创造引擎不持有/不修改人格状态"""
        self.assertFalse(hasattr(self.engine, "_personality"))
        self.add_confirmed()
        self.engine.run()
        self.assertFalse(hasattr(self.engine, "adjust_personality"))

    def test_relationship_trust_mapping(self):
        """RelationshipManager trust_level → trust 兼容映射"""
        from backend.embodied.companion.relationship import (
            RelationshipManager,
        )
        mgr = RelationshipManager()
        for _ in range(10):
            mgr.update(success=True)
        e = CreativeEngine(relationship_manager=mgr)
        rel = e._relationship()
        self.assertIn("trust", rel)
        self.assertEqual(rel["trust"], rel["trust_level"])
        self.assertGreaterEqual(rel["trust"], 0.7)

    def test_relationship_opportunity_via_engine(self):
        """高信任关系 + 成功经验 → relationship 机会"""
        from backend.embodied.companion.relationship import (
            RelationshipManager,
        )
        mgr = RelationshipManager()
        for _ in range(10):
            mgr.update(success=True)
        e = CreativeEngine(
            experience_manager=self.mgr,
            verifier=self.verifier,
            reflection_engine=self.reflection,
            improvement_engine=self.improvement,
            relationship_manager=mgr,
        )
        self.add_confirmed(trigger="常用问候")
        opps = e.detect()
        types = {o["source_type"] for o in opps}
        self.assertIn("relationship", types)

    def test_relationship_no_manager_none(self):
        e = CreativeEngine()
        self.assertIsNone(e._relationship())

    def test_creative_does_not_change_goals(self):
        self.add_confirmed()
        self.engine.run()
        st = self.engine.status()
        self.assertEqual(st["mode"], "rule_based")


if __name__ == "__main__":
    unittest.main()
