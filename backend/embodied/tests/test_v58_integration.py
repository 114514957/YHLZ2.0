"""
YHLZ Embodied AI V5.8 - 反思与认知完整性 Service 集成测试
(Reflection & Cognitive Integrity via Service)

覆盖:
    - Service reflection/verification API
    - 完整闭环: Action → Experience → Verification → Reflection → Proposal
    - 认知免疫: 错误经验拒绝 / 矛盾场景化 / 现实检查
    - 身份连续: 核心人格不变
    - 向后兼容
"""
import unittest

from backend.embodied.service import EmbodiedService


class TestServiceReflection(unittest.TestCase):
    """Service 反思 API"""

    def setUp(self):
        self.svc = EmbodiedService()
        self.svc.load_config({
            "embodied_enabled": True,
            "companion_enabled": True,
        })

    def test_companion_reflection_api(self):
        """companion_reflection"""
        r = self.svc.companion_reflection()
        for key in ("observation", "evidence", "pattern", "risk",
                    "suggestion", "confidence"):
            self.assertIn(key, r)
        self.assertEqual(r["mode"], "rule_based")

    def test_reflection_validated_api(self):
        """companion_reflection_validated"""
        r = self.svc.companion_reflection_validated()
        self.assertEqual(r["mode"], "rule_based")

    def test_verification_stats_api(self):
        """companion_verification_stats"""
        st = self.svc.companion_verification_stats()
        self.assertEqual(st["mode"], "rule_based")
        self.assertIn("by_status", st)

    def test_verification_confirm_api(self):
        """companion_verification_confirm"""
        self.svc.companion_handle({"text": "扫描环境查看策略建议"})
        recs = self.svc.companion_experience._store.all()
        exp_id = recs[0].id
        v = self.svc.companion_verification_confirm(exp_id)
        self.assertIn(v["status"], ("PENDING", "PROBABLE", "CONFIRMED"))

    def test_verification_reject_api(self):
        """companion_verification_reject"""
        self.svc.companion_handle({"text": "扫描环境查看策略建议"})
        recs = self.svc.companion_experience._store.all()
        exp_id = recs[0].id
        v = self.svc.companion_verification_reject(exp_id)
        self.assertIn(v["status"], ("PENDING", "REJECTED"))

    def test_proposal_stats_api(self):
        """companion_proposal_stats"""
        st = self.svc.companion_proposal_stats()
        self.assertEqual(st["mode"], "rule_based")
        self.assertIn("total", st)


class TestCognitiveLoop(unittest.TestCase):
    """认知完整闭环"""

    def setUp(self):
        self.svc = EmbodiedService()
        self.svc.load_config({
            "embodied_enabled": True,
            "companion_enabled": True,
        })

    def test_full_loop(self):
        """Action → Experience → Verification → Reflection → Proposal"""
        # Action + Experience + Verification (handle 联动)
        for _ in range(3):
            self.svc.companion_handle({"text": "扫描环境查看策略建议"})
        # Verification 状态
        st = self.svc.companion_verification_stats()
        self.assertGreaterEqual(st["total"], 3)
        # Reflection
        ref = self.svc.companion_reflection()
        self.assertIn("observation", ref)
        # Proposal (有模式时生成)
        ps = self.svc.companion_proposal_stats()
        self.assertIn("total", ps)

    def test_confirmed_only_for_longterm(self):
        """只有 CONFIRMED 进入长期参考"""
        self.svc.companion_handle({"text": "扫描环境查看策略建议"})
        recs = self.svc.companion_experience._store.all()
        exp_id = recs[0].id
        # 未确认 → 不在 confirmed
        self.assertNotIn(exp_id, self.svc.companion_verifier.confirmed_ids())
        # 2 次确认 → CONFIRMED
        self.svc.companion_verification_confirm(exp_id)
        self.svc.companion_verification_confirm(exp_id)
        self.assertIn(exp_id, self.svc.companion_verifier.confirmed_ids())

    def test_reject_wrong_experience(self):
        """认知免疫: 拒绝错误经验"""
        self.svc.companion_handle({"text": "扫描环境查看策略建议"})
        recs = self.svc.companion_experience._store.all()
        exp_id = recs[0].id
        for _ in range(2):
            self.svc.companion_verification_reject(exp_id)
        self.assertIn(exp_id, self.svc.companion_verifier.rejected_ids())


class TestIntegrity(unittest.TestCase):
    """完整性组件 (经 Service)"""

    def setUp(self):
        self.svc = EmbodiedService()
        self.svc.load_config({
            "embodied_enabled": True,
            "companion_enabled": True,
        })

    def test_contradiction_detector(self):
        """矛盾检测"""
        from backend.embodied.companion import ContradictionDetector
        d = ContradictionDetector()
        r = d.check("用户喜欢简短回答", "用户喜欢详细工程方案",
                    context_a="日常", context_b="工程")
        self.assertTrue(r["conflict"])
        self.assertTrue(r["context_dependent"])

    def test_reality_check(self):
        """现实检查"""
        from backend.embodied.companion import RealityCheck
        r = RealityCheck().verify(source="run_goal", evidence_count=3,
                                  occurrences=5, contradictions=0,
                                  value=0.8)
        self.assertTrue(r["passed"])

    def test_confidence_engine(self):
        """置信度"""
        from backend.embodied.companion import ConfidenceEngine
        r = ConfidenceEngine().compute(source_reliability=0.9,
                                       occurrences=5,
                                       consistency=1.0,
                                       contradictions=0,
                                       age_days=30)
        self.assertGreaterEqual(r["confidence"], 0.7)


class TestSafetyCompatV58(unittest.TestCase):
    """安全与兼容"""

    def setUp(self):
        self.svc = EmbodiedService()
        self.svc.load_config({
            "embodied_enabled": True,
            "companion_enabled": True,
        })

    def test_identity_stable(self):
        """身份连续: 核心人格不变"""
        self.svc.companion_reflection()
        self.svc.companion_verification_stats()
        p = self.svc.companion_personality()
        self.assertEqual(p["base"], "铁哥们")

    def test_reflection_no_memory_write(self):
        """反思不写 Agent Memory"""
        before = self.svc.memory.stats().get("total", 0)
        self.svc.companion_reflection()
        self.svc.companion_verification_stats()
        after = self.svc.memory.stats().get("total", 0)
        self.assertEqual(after, before)

    def test_v57_experience_works(self):
        """V5.7 经历兼容"""
        st = self.svc.companion_experience_stats()
        self.assertIn("total", st)

    def test_v56_relationship_works(self):
        """V5.6 关系兼容"""
        rel = self.svc.companion_relationship()
        self.assertIn("trust_level", rel)

    def test_v55_personality_works(self):
        """V5.5 人格兼容"""
        p = self.svc.companion_personality()
        self.assertEqual(p["base"], "铁哥们")

    def test_version_5_8_0(self):
        """版本 = 9.5.0"""
        self.assertEqual(self.svc.report()["version"], "9.5.0")

    def test_proposal_not_executed_auto(self):
        """建议不自动执行 (Proposal ≠ Action)"""
        self.svc.companion_handle({"text": "扫描环境查看策略建议"})
        ps = self.svc.companion_proposal_stats()
        self.assertEqual(ps["executed"], 0)

    def test_reflection_report_id(self):
        """反思报告 ID"""
        r = self.svc.companion_reflection()
        self.assertTrue(r["report_id"].startswith("ref_"))

    def test_verification_after_handle(self):
        """handle 后自动验证"""
        self.svc.companion_handle({"text": "扫描环境查看策略建议"})
        st = self.svc.companion_verification_stats()
        self.assertGreaterEqual(st["total"], 1)

    def test_confidence_via_service(self):
        """置信度可用"""
        from backend.embodied.companion import ConfidenceEngine
        r = ConfidenceEngine().compute()
        self.assertIn("confidence", r)

    def test_evidence_via_service(self):
        """证据管理可用"""
        from backend.embodied.companion import EvidenceManager
        mgr = EvidenceManager()
        mgr.add(experience_id="x", evidence="e")
        self.assertEqual(mgr.count_for("x"), 1)

    def test_reflection_mode(self):
        """反思模式"""
        r = self.svc.companion_reflection()
        self.assertEqual(r["mode"], "rule_based")

    def test_verification_mode(self):
        """验证模式"""
        st = self.svc.companion_verification_stats()
        self.assertEqual(st["mode"], "rule_based")

    def test_handle_after_reflection(self):
        """反思后 handle 正常"""
        self.svc.companion_reflection()
        r = self.svc.companion_handle({"text": "扫描环境查看策略建议"})
        self.assertEqual(r["mode"], "rule_based")

    def test_verification_statuses_whitelist(self):
        """验证状态白名单"""
        from backend.embodied.companion import VERIFICATION_STATUSES
        self.assertEqual(len(VERIFICATION_STATUSES), 5)

    def test_reflection_evidence(self):
        """反思含证据"""
        r = self.svc.companion_reflection()
        self.assertIsInstance(r["evidence"], list)

    def test_reflection_risk(self):
        """反思含风险"""
        r = self.svc.companion_reflection()
        self.assertIn(r["risk"], ("low", "medium", "high"))

    def test_verifier_thresholds_config(self):
        """验证阈值配置"""
        svc = EmbodiedService()
        svc.load_config({
            "embodied_enabled": True,
            "companion_verification_confirm_threshold": 3,
        })
        st = svc.companion_verification_stats()
        self.assertEqual(st["confirm_threshold"], 3)

    def test_pattern_config(self):
        """模式阈值配置"""
        svc = EmbodiedService()
        svc.load_config({
            "embodied_enabled": True,
            "companion_pattern_min_occurrences": 5,
        })
        # 配置在 main agent 构造时生效
        pd = svc.companion_reflection_engine._patterns
        self.assertEqual(pd._min_occurrences, 5)

    def test_reflection_identity_preserved(self):
        """反思不改变核心人格"""
        before = self.svc.companion_personality()["base"]
        self.svc.companion_reflection()
        self.svc.companion_verification_stats()
        after = self.svc.companion_personality()["base"]
        self.assertEqual(before, after)

    def test_v57_reflection_report_works(self):
        """V5.7 反思报告兼容"""
        r = self.svc.companion_experience_reflection()
        self.assertIn("observation", r)

    def test_reject_threshold_config(self):
        """拒绝阈值配置"""
        svc = EmbodiedService()
        svc.load_config({
            "embodied_enabled": True,
            "companion_verification_reject_threshold": 1,
        })
        st = svc.companion_verification_stats()
        self.assertEqual(st["reject_threshold"], 1)

    def test_reflection_after_failures(self):
        """失败后反思含失败分析"""
        svc = EmbodiedService()
        svc.load_config({"embodied_enabled": False,
                         "companion_enabled": True})
        svc.companion_handle({"text": "执行拿起任务"})
        r = svc.companion_reflection()
        self.assertIn("failure_analyses", r)


if __name__ == "__main__":
    unittest.main()
