"""
YHLZ Embodied AI V5.4 - 自我修正与学习 Service 集成测试
(Self-Correction & Learning via Service)

覆盖:
    - Service companion_correct / companion_learning API
    - 配置驱动: correction_max_attempts / learning_enabled / correction_strict
    - 修正-学习闭环 (失败 → 学习 → 规则)
    - 修正审计
    - 安全: 修正经 Permission / 不写 Agent Memory
    - 向后兼容: V5.3 / V5.2 / V5.1 API
"""
import unittest

from backend.embodied.service import EmbodiedService


class TestServiceCorrection(unittest.TestCase):
    """Service 修正 API"""

    def setUp(self):
        self.svc = EmbodiedService()
        self.svc.load_config({
            "embodied_enabled": True,
            "companion_enabled": True,
        })

    def test_companion_correct_api(self):
        """companion_correct"""
        result = self.svc.companion_correct({
            "description": "扫描", "intent": "scan",
        })
        self.assertTrue(result["success"])
        self.assertIn("correction_id", result)

    def test_correct_attempts(self):
        """成功修正 1 次"""
        result = self.svc.companion_correct({
            "description": "扫描", "intent": "scan",
        })
        self.assertEqual(result["attempts"], 1)

    def test_correct_mode(self):
        """修正模式"""
        result = self.svc.companion_correct({
            "description": "扫描", "intent": "scan",
        })
        self.assertEqual(result["mode"], "rule_based")

    def test_correct_denied(self):
        """权限拒绝不修正"""
        svc = EmbodiedService()
        svc.load_config({"embodied_enabled": False})
        result = svc.companion_correct({
            "description": "拿起", "intent": "pick",
        })
        self.assertFalse(result["success"])
        self.assertEqual(result["final_status"], "denied")

    def test_correct_audit_via_service(self):
        """修正审计经 Service"""
        self.svc.companion_correct({
            "description": "扫描", "intent": "scan",
        })
        aud = self.svc.companion_corrector.audit()
        self.assertEqual(aud["total"], 1)

    def test_corrector_shared_instance(self):
        """修正器单实例 (审计累积)"""
        self.svc.companion_correct({"description": "扫描", "intent": "scan"})
        self.svc.companion_correct({"description": "扫描", "intent": "scan"})
        aud = self.svc.companion_corrector.audit()
        self.assertEqual(aud["total"], 2)

    def test_config_max_attempts(self):
        """配置驱动上限"""
        svc = EmbodiedService()
        svc.load_config({
            "embodied_enabled": True,
            "companion_correction_max_attempts": 2,
        })
        self.assertEqual(svc.companion_corrector.thresholds()[
            "max_attempts"], 2)


class TestServiceLearning(unittest.TestCase):
    """Service 学习 API"""

    def setUp(self):
        self.svc = EmbodiedService()
        self.svc.load_config({
            "embodied_enabled": True,
            "companion_enabled": True,
        })

    def test_companion_learning_api(self):
        """companion_learning"""
        lrn = self.svc.companion_learning()
        self.assertEqual(lrn["mode"], "rule_based")
        self.assertIn("failure_rules", lrn)
        self.assertIn("success_rules", lrn)

    def test_learning_enabled_default(self):
        """学习默认启用"""
        lrn = self.svc.companion_learning()
        self.assertTrue(lrn["enabled"])

    def test_learning_after_corrections(self):
        """修正后学习累积"""
        self.svc.companion_correct({"description": "扫描", "intent": "scan"})
        lrn = self.svc.companion_learning()
        self.assertGreaterEqual(len(lrn["success_patterns"]), 1)

    def test_learning_after_failures(self):
        """失败后学习规则"""
        for _ in range(3):
            self.svc.companion_correct({
                "description": "拿起幽灵对象", "intent": "pick",
                "target": "ghost",
            })
        lrn = self.svc.companion_learning()
        self.assertGreaterEqual(len(lrn["failure_rules"]), 1)

    def test_learning_disabled_config(self):
        """学习停用配置"""
        svc = EmbodiedService()
        svc.load_config({
            "embodied_enabled": True,
            "companion_learning_enabled": False,
        })
        lrn = svc.companion_learning()
        self.assertFalse(lrn["enabled"])

    def test_learning_threshold(self):
        """学习阈值"""
        lrn = self.svc.companion_learning()
        self.assertEqual(lrn["threshold"], 3)

    def test_learning_patterns(self):
        """学习模式字段"""
        self.svc.companion_correct({"description": "扫描", "intent": "scan"})
        lrn = self.svc.companion_learning()
        if lrn["success_patterns"]:
            p = lrn["success_patterns"][0]["pattern"]
            self.assertEqual(p["kind"], "success")


class TestCorrectionLearningLoop(unittest.TestCase):
    """修正-学习闭环"""

    def setUp(self):
        self.svc = EmbodiedService()
        self.svc.load_config({
            "embodied_enabled": True,
            "companion_enabled": True,
        })

    def test_correction_feeds_learning(self):
        """修正 → 学习闭环"""
        self.svc.companion_correct({
            "description": "拿起幽灵对象", "intent": "pick",
            "target": "ghost",
        })
        lrn = self.svc.companion_learning()
        total = (len(lrn["failure_patterns"])
                 + len(lrn["success_patterns"]))
        self.assertGreaterEqual(total, 1)

    def test_learning_rule_reusable(self):
        """学习规则可查 (修正参考)"""
        learner = self.svc.companion_learner
        learner.record_failure(cause="position_mismatch", action="pick")
        rule = learner.best_failure_rule("position_mismatch")
        self.assertIsNotNone(rule)
        from backend.embodied.companion import SelfCorrector
        corr = SelfCorrector.rule_for(rule["pattern"]["cause"])
        self.assertEqual(corr["adjustment"], "move_first")


class TestSafetyCompat(unittest.TestCase):
    """安全与兼容"""

    def setUp(self):
        self.svc = EmbodiedService()
        self.svc.load_config({
            "embodied_enabled": True,
            "companion_enabled": True,
        })

    def test_correction_not_memory(self):
        """修正不写 Agent Memory"""
        result = self.svc.companion_correct({
            "description": "扫描", "intent": "scan",
        })
        self.assertNotIn("agent_memory", result)

    def test_correction_permission(self):
        """修正执行经 Permission"""
        result = self.svc.companion_correct({
            "description": "扫描", "intent": "scan",
        })
        self.assertTrue(result["success"])

    def test_v53_execute_works(self):
        """V5.3 companion_execute 兼容"""
        rec = self.svc.companion_execute({
            "description": "扫描", "intent": "scan",
        })
        self.assertTrue(rec["success"])

    def test_v53_loop_works(self):
        """V5.3 companion_loop 兼容"""
        loop = self.svc.companion_loop({
            "description": "扫描", "intent": "scan",
        })
        self.assertTrue(loop["success"])

    def test_v52_pipeline_works(self):
        """V5.2 companion_pipeline 兼容"""
        pa = self.svc.companion_pipeline()
        self.assertEqual(len(pa["stages"]), 2)

    def test_v51_stats_works(self):
        """V5.1 companion_stats 兼容"""
        st = self.svc.companion_stats()
        self.assertEqual(st["mode"], "rule_based")

    def test_version_5_4_0(self):
        """版本 = 9.5.0"""
        self.assertEqual(self.svc.report()["version"], "9.5.0")

    def test_audit_still_tracked(self):
        """审计仍记录"""
        self.svc.companion_handle({"text": "扫描"})
        log = self.svc.audit_policy_log(limit=0, action="companion_handle")
        self.assertEqual(log["total"], 1)

    def test_correction_explainable(self):
        """修正可解释"""
        result = self.svc.companion_correct({
            "description": "扫描", "intent": "scan",
        })
        self.assertIn("自我修正", result["explainable_reason"])

    def test_learning_rule_based(self):
        """学习纯规则"""
        lrn = self.svc.companion_learning()
        self.assertEqual(lrn["mode"], "rule_based")

    def test_correct_record_result(self):
        """修正记录结果"""
        result = self.svc.companion_correct({
            "description": "扫描", "intent": "scan",
        })
        self.assertIn("result", result["records"][0])
        self.assertIn("status", result["records"][0]["result"])

    def test_correction_strict_config(self):
        """严格模式配置"""
        svc = EmbodiedService()
        svc.load_config({
            "embodied_enabled": True,
            "companion_correction_strict": True,
        })
        self.assertTrue(svc.companion_corrector.thresholds()["strict"])

    def test_learning_threshold_config(self):
        """学习阈值默认 3"""
        lrn = self.svc.companion_learning()
        self.assertEqual(lrn["threshold"], 3)

    def test_corrector_failure_learning_loop(self):
        """修正-学习-规则闭环"""
        for _ in range(3):
            self.svc.companion_correct({
                "description": "拿起幽灵对象", "intent": "pick",
                "target": "ghost",
            })
        lrn = self.svc.companion_learning()
        self.assertGreaterEqual(len(lrn["failure_rules"]), 1)
        rule = lrn["failure_rules"][0]
        self.assertIn("pattern", rule)
        self.assertIn("count", rule)

    def test_correction_not_device(self):
        """修正不控制设备"""
        result = self.svc.companion_correct({
            "description": "扫描", "intent": "scan",
        })
        self.assertNotIn("device", result)


if __name__ == "__main__":
    unittest.main()
