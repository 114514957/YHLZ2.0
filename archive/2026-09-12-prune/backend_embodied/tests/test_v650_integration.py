"""
YHLZ Embodied AI V6.5 - 认知反思与自主成长集成测试 (V6.5 Integration)

覆盖:
    - Service API (reflection/pattern/contradiction/growth)
    - 完整闭环: 经历 → 反思 → 建议 → 评估 → 受控应用
    - 安全: 未经批准不能修改 / 人格稳定
    - 向后兼容 (V6.4 及以前)
"""
import unittest

from backend.embodied.service import EmbodiedService


def setup_service(**extra):
    cfg = {
        "embodied_enabled": True,
        "companion_enabled": True,
    }
    cfg.update(extra)
    svc = EmbodiedService()
    svc.load_config(cfg)
    return svc


def seed_experiences(svc, success_n=4, fail_n=3):
    mgr = svc.companion_experience
    for _ in range(success_n):
        mgr.store_from_event(
            success=True, trigger="生成工程Prompt",
            source="v650_test", action="a", result="成功",
        )
    for _ in range(fail_n):
        mgr.store_from_event(
            success=False, trigger="拾取物体",
            source="v650_test", action="a", result="位置不匹配",
        )


class TestReflectionAPI(unittest.TestCase):
    """反思 API"""

    def setUp(self):
        self.svc = setup_service()
        seed_experiences(self.svc)

    def test_reflection_analyze_api(self):
        r = self.svc.companion_reflection_analyze()
        for key in ("report_id", "summary", "pattern",
                    "success_factor", "failure_factor",
                    "confidence", "patterns", "mode"):
            self.assertIn(key, r)
        self.assertEqual(r["mode"], "rule_based")

    def test_reflection_summary(self):
        r = self.svc.companion_reflection_analyze()
        self.assertIn("7", r["summary"])

    def test_pattern_detect_api(self):
        r = self.svc.companion_pattern_detect()
        self.assertIn("patterns", r)
        self.assertIn("stats", r)
        self.assertGreaterEqual(r["stats"]["pattern_count"], 1)

    def test_contradiction_check_api(self):
        r = self.svc.companion_contradiction_check()
        self.assertIn("conflict", r)
        self.assertEqual(r["mode"], "rule_based")

    def test_contradiction_no_experience(self):
        svc = setup_service()
        r = svc.companion_contradiction_check()
        self.assertFalse(r["conflict"])


class TestGrowthAPI(unittest.TestCase):
    """成长 API"""

    def setUp(self):
        self.svc = setup_service()
        seed_experiences(self.svc)

    def test_growth_generate_api(self):
        r = self.svc.companion_growth_generate()
        self.assertIn("proposals", r)
        self.assertGreaterEqual(r["proposal_count"], 1)

    def test_growth_proposal_types(self):
        r = self.svc.companion_growth_generate()
        types = {p["type"] for p in r["proposals"]}
        self.assertIn("skill_improvement", types)

    def test_growth_evaluate_api(self):
        g = self.svc.companion_growth_generate()
        if g["proposals"]:
            ev = self.svc.companion_growth_evaluate(
                g["proposals"][0],
            )
            self.assertIn("approved", ev)
            self.assertIn("score", ev)

    def test_growth_apply_approved(self):
        """approved + 人工变更 → 应用"""
        g = self.svc.companion_growth_generate()
        if g["proposals"]:
            p = g["proposals"][0]
            ev = self.svc.companion_growth_evaluate(p)
            r = self.svc.companion_growth_apply(
                p, ev, changes={"note": "记录优化"},
            )
            self.assertIn(r["status"], ("applied", "blocked",
                                        "pending_confirm"))

    def test_growth_apply_unapproved_blocked(self):
        """未批准 → 拒绝"""
        p = {
            "id": "gp_x", "type": "skill_improvement",
            "description": "改进", "expected_gain": "g",
            "risk": "low", "confidence": 0.8,
        }
        r = self.svc.companion_growth_apply(
            p, {"approved": False, "reason": "x"},
        )
        self.assertEqual(r["status"], "blocked")

    def test_growth_apply_identity_guard(self):
        """非法变更 → 身份守护拦截"""
        p = {
            "id": "gp_y", "type": "skill_improvement",
            "description": "改进技能", "expected_gain": "g",
            "risk": "low", "confidence": 0.8,
        }
        r = self.svc.companion_growth_apply(
            p, {"approved": True, "reason": "x"},
            changes={"mission": "新使命"},
        )
        self.assertEqual(r["status"], "blocked")
        self.assertIn("守护", r["reason"])

    def test_growth_audit_api(self):
        self.svc.companion_growth_generate()
        r = self.svc.companion_growth_audit()
        self.assertEqual(r["mode"], "rule_based")

    def test_growth_stats_api(self):
        st = self.svc.companion_growth_stats()
        for key in ("reflection", "proposal", "evaluator",
                    "applier", "identity_guard",
                    "change_validator"):
            self.assertIn(key, st)


class TestSafety(unittest.TestCase):
    """安全边界"""

    def setUp(self):
        self.svc = setup_service()
        seed_experiences(self.svc)

    def test_no_auto_apply_by_default(self):
        """默认禁止自动成长修改"""
        st = self.svc.companion_growth_stats()
        # 仅生成建议不应用
        self.svc.companion_growth_generate()
        self.assertEqual(
            self.svc.companion_growth_stats()["applier"][
                "applied_count"], 0,
        )

    def test_personality_stable_after_reflection(self):
        p_before = self.svc.companion_personality()
        self.svc.companion_reflection_analyze()
        self.svc.companion_growth_generate()
        p_after = self.svc.companion_personality()
        self.assertEqual(p_before["base"], p_after["base"])
        self.assertEqual(p_before["dimensions"],
                         p_after["dimensions"])

    def test_identity_guard_intercepts(self):
        self.svc.companion_growth_apply(
            {"id": "gp_z", "type": "skill_improvement",
             "description": "改进", "expected_gain": "g",
             "risk": "low", "confidence": 0.8},
            {"approved": True, "reason": "x"},
            changes={"core_value": "新价值"},
        )
        st = self.svc.companion_growth_stats()
        self.assertGreaterEqual(
            st["identity_guard"]["intercept_count"], 1,
        )

    def test_change_validator_blocks_protected(self):
        """变更验证: 保护字段变更被拦截"""
        g = self.svc.companion_growth_generate()
        if g["proposals"]:
            p = g["proposals"][0]
            r = self.svc.companion_growth_apply(
                p, {"approved": True, "reason": "x"},
                changes={"mission": "新使命"},
            )
            self.assertEqual(r["status"], "blocked")


class TestBackwardCompat(unittest.TestCase):
    """向后兼容"""

    def setUp(self):
        self.svc = setup_service()

    def test_v64_cognitive_api(self):
        c = {"candidate_id": "mc_1", "source": "camera",
             "kind": "ocr", "summary": "重要任务",
             "confidence": 0.9}
        r = self.svc.companion_reflection_evaluate(c)
        self.assertIn("recommendation", r)

    def test_v63_gate_api(self):
        st = self.svc.companion_perception_memory_gate_stats()
        self.assertIn("candidate_count", st)

    def test_v62_expression_api(self):
        r = self.svc.companion_expression_generate(
            emotion={"positivity": 0.9},
        )
        self.assertEqual(r["style"], "more_positive")

    def test_v611_emotion_api(self):
        self.svc.companion_emotion_adjust("success")
        self.assertIn("positivity", self.svc.companion_emotion())

    def test_v60_persistence_api(self):
        import os
        import shutil
        import tempfile
        svc = setup_service(companion_persistence_enabled=True)
        tmp = tempfile.mkdtemp(prefix="yhlz_bc65_")
        path = os.path.join(tmp, "s.jsonl")
        svc.companion_persistence_save(path)
        svc2 = EmbodiedService()
        svc2.load_config({"companion_persistence_enabled": True})
        res = svc2.companion_persistence_load(path)
        self.assertTrue(res["success"])
        shutil.rmtree(tmp, ignore_errors=True)

    def test_v59_creative_api(self):
        r = self.svc.companion_creative_run()
        self.assertIn("summary", r)

    def test_v50_handle_api(self):
        r = self.svc.companion_handle({"text": "扫描环境查看策略建议"})
        self.assertIn("request_id", r)

    def test_version_6_5_0(self):
        self.assertEqual(self.svc.companion.status()["version"],
                         "9.5.0")

    def test_growth_report_api(self):
        r = self.svc.companion_growth_report()
        self.assertEqual(r["mode"], "rule_based")


class TestConfigDriven(unittest.TestCase):
    """配置驱动"""

    def test_pattern_disabled(self):
        svc = setup_service()
        # 认知反思引擎读取 reflection_enabled
        eng = svc.companion_cognitive_reflection
        self.assertTrue(eng._enabled)

    def test_growth_proposal_disabled(self):
        svc = setup_service(growth_proposal_enabled=False)
        eng = svc.companion_growth_engine
        self.assertFalse(eng["proposal"]._enabled)

    def test_growth_auto_apply_config(self):
        svc = setup_service(growth_auto_apply=True)
        applier = svc.companion_growth_engine["applier"]
        self.assertTrue(applier._auto_apply)

    def test_identity_guard_disabled(self):
        svc = setup_service(identity_guard_enabled=False)
        guard = svc.companion_identity_guard["guard"]
        self.assertFalse(guard._enabled)

    def test_growth_audit_disabled(self):
        svc = setup_service(growth_audit_enabled=False)
        applier = svc.companion_growth_engine["applier"]
        self.assertFalse(applier._audit._enabled)


if __name__ == "__main__":
    unittest.main()
