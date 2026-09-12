"""
YHLZ Embodied AI V5.9 - 创造智能 Service 集成测试
(Creative Intelligence & Value Discovery via Service)

覆盖:
    - Service creative_* API (run/detect/evaluate/propose/simulate/
      approve/reject/execute/record_result/stats/audit)
    - 完整闭环: Action → Experience → Verification → Reflection
      → Opportunity → Evaluation → Proposal → Simulation → Approval
      → Execution → New Experience
    - 安全: 未验证经验不创造 / 未批准不执行 / 身份稳定
    - 向后兼容 (V5.8 全部 API 仍可用)
"""
import unittest

from backend.embodied.service import EmbodiedService


def setup_service():
    svc = EmbodiedService()
    svc.load_config({
        "embodied_enabled": True,
        "companion_enabled": True,
    })
    return svc


def seed_confirmed(svc, trigger="生成工程Prompt", n=3):
    """添加并确认经历"""
    mgr = svc.companion_experience
    verifier = svc.companion_verifier
    ids = []
    for _ in range(n):
        rec = mgr.store_from_event(
            success=True, trigger=trigger,
            source="v59_integration", action="a", result="成功",
        )
        ids.append(rec["id"])
    for rid in ids:
        for _ in range(3):
            verifier.verify(rid, evidence_count=2, contradictions=0)
    return ids


class TestServiceCreativeAPI(unittest.TestCase):
    """Service 创造 API"""

    def setUp(self):
        self.svc = setup_service()

    def test_creative_run_api(self):
        r = self.svc.companion_creative_run()
        self.assertIn("summary", r)
        self.assertFalse(r["auto_executed"])
        self.assertEqual(r["mode"], "rule_based")

    def test_creative_detect_api(self):
        out = self.svc.companion_creative_detect()
        self.assertIsInstance(out, list)

    def test_creative_evaluate_api(self):
        seed_confirmed(self.svc)
        opps = self.svc.companion_creative_detect()
        self.assertGreaterEqual(len(opps), 1)
        ev = self.svc.companion_creative_evaluate(
            opps[0]["opportunity_id"],
        )
        self.assertIn(ev["decision"], ("create", "defer", "reject"))

    def test_creative_propose_api(self):
        seed_confirmed(self.svc)
        opps = self.svc.companion_creative_detect()
        p = self.svc.companion_creative_propose(
            opps[0]["opportunity_id"],
        )
        self.assertTrue(p["proposal_id"].startswith("cp_"))
        self.assertEqual(p["status"], "PENDING")

    def test_creative_simulate_api(self):
        seed_confirmed(self.svc)
        opps = self.svc.companion_creative_detect()
        p = self.svc.companion_creative_propose(
            opps[0]["opportunity_id"],
        )
        sim = self.svc.companion_creative_simulate(p["proposal_id"])
        self.assertIn(sim["recommendation"],
                      ("proceed", "revise", "abandon"))

    def test_creative_approve_api(self):
        seed_confirmed(self.svc)
        opps = self.svc.companion_creative_detect()
        p = self.svc.companion_creative_propose(
            opps[0]["opportunity_id"],
        )
        ap = self.svc.companion_creative_approve(
            p["proposal_id"], approver="user",
        )
        self.assertEqual(ap["status"], "APPROVED")

    def test_creative_reject_api(self):
        seed_confirmed(self.svc)
        opps = self.svc.companion_creative_detect()
        p = self.svc.companion_creative_propose(
            opps[0]["opportunity_id"],
        )
        rj = self.svc.companion_creative_reject(
            p["proposal_id"], "不需要",
        )
        self.assertEqual(rj["status"], "REJECTED")

    def test_creative_execute_api(self):
        seed_confirmed(self.svc)
        opps = self.svc.companion_creative_detect()
        p = self.svc.companion_creative_propose(
            opps[0]["opportunity_id"],
        )
        self.svc.companion_creative_approve(p["proposal_id"])
        ex = self.svc.companion_creative_execute(p["proposal_id"])
        self.assertEqual(ex["status"], "EXECUTED")

    def test_creative_record_result_api(self):
        seed_confirmed(self.svc)
        opps = self.svc.companion_creative_detect()
        p = self.svc.companion_creative_propose(
            opps[0]["opportunity_id"],
        )
        self.svc.companion_creative_approve(p["proposal_id"])
        self.svc.companion_creative_execute(p["proposal_id"])
        rr = self.svc.companion_creative_record_result(
            p["proposal_id"], True, result="成功",
        )
        self.assertEqual(rr["status"], "COMPLETED")

    def test_creative_stats_api(self):
        st = self.svc.companion_creative_stats()
        self.assertIn("summary", st)
        self.assertEqual(st["mode"], "rule_based")

    def test_creative_audit_api(self):
        seed_confirmed(self.svc)
        self.svc.companion_creative_detect()
        r = self.svc.companion_creative_audit()
        self.assertEqual(r["mode"], "rule_based")
        self.assertGreaterEqual(r["by_action"].get("detect", 0), 1)

    def test_version_5_9(self):
        self.assertEqual(self.svc.companion.status()["version"], "9.5.0")


class TestCreativeFullLoop(unittest.TestCase):
    """完整创造闭环"""

    def setUp(self):
        self.svc = setup_service()

    def test_full_loop_via_handle(self):
        """Action → Experience → Verification → 创造闭环"""
        seed_confirmed(self.svc)
        r = self.svc.companion_creative_run()
        self.assertGreaterEqual(r["summary"]["opportunity_count"], 1)
        self.assertGreaterEqual(r["summary"]["proposal_count"], 1)
        self.assertGreaterEqual(r["summary"]["simulation_count"], 1)

    def test_confirmed_only_via_service(self):
        """未验证经验不产生机会"""
        self.svc.companion_handle({"text": "扫描环境查看策略建议"})
        r = self.svc.companion_creative_run()
        self.assertEqual(r["summary"]["opportunity_count"], 0)

    def test_approval_gate_via_service(self):
        """未批准不能执行"""
        seed_confirmed(self.svc)
        opps = self.svc.companion_creative_detect()
        p = self.svc.companion_creative_propose(
            opps[0]["opportunity_id"],
        )
        with self.assertRaises(Exception):
            self.svc.companion_creative_execute(p["proposal_id"])

    def test_new_experience_cycle(self):
        """执行结果 → 新经验 → 验证"""
        seed_confirmed(self.svc)
        opps = self.svc.companion_creative_detect()
        p = self.svc.companion_creative_propose(
            opps[0]["opportunity_id"],
        )
        self.svc.companion_creative_approve(p["proposal_id"])
        self.svc.companion_creative_execute(p["proposal_id"])
        rr = self.svc.companion_creative_record_result(
            p["proposal_id"], True, result="成功",
        )
        exp_id = rr["experience_id"]
        exp = self.svc.companion_experience.retrieve(exp_id)
        self.assertIsNotNone(exp)
        state = self.svc.companion_verifier.get(exp_id)
        self.assertIn(state["status"],
                      ("PENDING", "PROBABLE", "CONFIRMED"))

    def test_opportunity_repeated_runs_deduplicated(self):
        seed_confirmed(self.svc)
        self.svc.companion_creative_run()
        first = self.svc.companion_creative_stats()[
            "summary"]["opportunity_count"]
        self.svc.companion_creative_run()
        second = self.svc.companion_creative_stats()[
            "summary"]["opportunity_count"]
        self.assertEqual(first, second)

    def test_persist_via_engine(self):
        seed_confirmed(self.svc)
        opps = self.svc.companion_creative_detect()
        self.svc.companion_creative_propose(
            opps[0]["opportunity_id"],
        )
        engine = self.svc.companion_creative_engine
        st = engine.stats()
        self.assertGreaterEqual(st["summary"]["proposal_count"], 1)


class TestIdentityStability(unittest.TestCase):
    """身份稳定与边界"""

    def setUp(self):
        self.svc = setup_service()

    def test_personality_untouched(self):
        seed_confirmed(self.svc)
        before = self.svc.companion_personality()
        self.svc.companion_creative_run()
        after = self.svc.companion_personality()
        self.assertEqual(before["base"], after["base"])
        self.assertEqual(before["dimensions"], after["dimensions"])

    def test_relationship_untouched(self):
        seed_confirmed(self.svc)
        before = self.svc.companion_relationship()["trust_level"]
        self.svc.companion_creative_run()
        after = self.svc.companion_relationship()["trust_level"]
        self.assertEqual(before, after)

    def test_no_memory_write_to_agent(self):
        seed_confirmed(self.svc)
        self.svc.companion_creative_run()
        stats = self.svc.companion_experience.stats()
        self.assertIn("total", stats)

    def test_creative_enabled_config(self):
        svc = EmbodiedService()
        svc.load_config({
            "companion_creative_enabled": False,
        })
        self.assertEqual(
            svc.companion_creative_engine.status()["enabled"], False,
        )

    def test_stats_zero_before_run(self):
        st = self.svc.companion_creative_stats()
        self.assertEqual(st["summary"]["opportunity_count"], 0)


class TestBackwardCompatibility(unittest.TestCase):
    """V5.8 向后兼容"""

    def setUp(self):
        self.svc = setup_service()

    def test_v58_reflection_api(self):
        r = self.svc.companion_reflection()
        self.assertEqual(r["mode"], "rule_based")

    def test_v58_verification_api(self):
        st = self.svc.companion_verification_stats()
        self.assertEqual(st["mode"], "rule_based")

    def test_v58_proposal_api(self):
        st = self.svc.companion_proposal_stats()
        self.assertEqual(st["mode"], "rule_based")

    def test_v57_experience_api(self):
        st = self.svc.companion_experience_stats()
        self.assertIn("total", st)

    def test_v56_relationship_api(self):
        r = self.svc.companion_relationship()
        self.assertIn("trust_level", r)

    def test_v55_personality_api(self):
        p = self.svc.companion_personality()
        self.assertIn("base", p)

    def test_v50_handle_api(self):
        r = self.svc.companion_handle({"text": "扫描环境查看策略建议"})
        self.assertIn("request_id", r)

    def test_improvement_proposal_mirror(self):
        """创造方案在 V5.8 审批流有镜像"""
        seed_confirmed(self.svc)
        opps = self.svc.companion_creative_detect()
        p = self.svc.companion_creative_propose(
            opps[0]["opportunity_id"],
        )
        mirror_id = p["improvement_proposal_id"]
        mirror = self.svc.companion_reflection_engine._proposals.get(
            mirror_id,
        )
        self.assertIsNotNone(mirror)
        self.assertEqual(mirror["status"], "PENDING_APPROVAL")

    def test_handle_records_experience(self):
        self.svc.companion_handle({"text": "扫描环境查看策略建议"})
        self.assertGreaterEqual(
            self.svc.companion_experience.stats()["total"], 1,
        )


if __name__ == "__main__":
    unittest.main()
