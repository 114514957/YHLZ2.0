"""
YHLZ Embodied AI V9.5 - 元认知引擎集成测试 (V9.5 Integration)

覆盖:
    - MetaCognitionEngine 门面
    - Service API (companion_meta_cognition_*)
    - 防谵妄
    - 五测试: Reasoning Evaluation / Error Detection /
      Reflection / Safety Boundary / Hallucination
    - 向后兼容
"""
import unittest

from backend.embodied.companion.constitution import (
    ConstitutionEngine,
)
from backend.embodied.companion.meta_cognition import (
    MetaCognitionEngine,
)
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


class TestMetaCognitionEngine(unittest.TestCase):
    """元认知门面"""

    def setUp(self):
        self.engine = MetaCognitionEngine(
            constitution=ConstitutionEngine(),
        )

    def test_monitor(self):
        entry = self.engine.monitor("任务", "deductive", 0.8)
        self.assertEqual(entry["reasoning_type"],
                         "deductive")

    def test_evaluate(self):
        entry = self.engine.monitor("任务", "deductive", 0.8)
        r = self.engine.evaluate(entry, "根据数据")
        self.assertIn("score", r)

    def test_detect_error(self):
        r = self.engine.detect_error("记错了", "回忆")
        self.assertEqual(r["error_type"], "memory_error")

    def test_error_patterns(self):
        self.engine.detect_error("记错了", "回忆")
        self.engine.detect_error("记错了", "回忆")
        patterns = self.engine.error_patterns()
        self.assertGreaterEqual(len(patterns["patterns"]), 1)

    def test_reflect_ok(self):
        r = self.engine.reflect("经验", "分析",
                                "优化记忆检索")
        self.assertTrue(r["validation"]["ok"])
        self.assertTrue(r["update"])

    def test_reflect_constitution_block(self):
        r = self.engine.reflect("经验", "分析", "修改使命")
        self.assertFalse(r["validation"]["ok"])

    def test_reflect_delusion_block(self):
        r = self.engine.reflect("经验", "分析", "我是神")
        self.assertFalse(r["ok"])
        self.assertIn("防谵妄", r["reason"])

    def test_verify(self):
        r = self.engine.verify("结论", evidence="根据数据")
        self.assertIn("conclusion_type", r)

    def test_memory_save_filter(self):
        r = self.engine.memory_save("经验", validated=False)
        self.assertFalse(r["ok"])

    def test_audit_recorded(self):
        self.engine.monitor("任务")
        self.engine.evaluate(
            self.engine.monitor("t2"), "x",
        )
        report = self.engine.audit_report()
        self.assertGreaterEqual(report["total"], 2)

    def test_stats(self):
        self.engine.monitor("任务")
        stats = self.engine.stats()
        self.assertEqual(stats["operation_count"], 1)
        self.assertIn("monitor", stats)
        self.assertIn("audit", stats)

    def test_disabled(self):
        engine = MetaCognitionEngine(enabled=False)
        r = engine.monitor("任务")
        self.assertFalse(r["ok"])

    def test_clear(self):
        self.engine.monitor("任务")
        n = self.engine.clear()
        self.assertGreater(n, 0)
        self.assertEqual(self.engine.stats()[
            "operation_count"], 0)


class TestFiveTests(unittest.TestCase):
    """规格五测试"""

    def setUp(self):
        self.svc = setup_service()

    def test_reasoning_evaluation_test(self):
        """Reasoning Evaluation Test"""
        entry = self.svc.companion_meta_cognition_monitor(
            "任务", "deductive", 0.8, "部分不确定",
            ["local"],
        )
        r = self.svc.companion_meta_cognition_evaluate(
            entry, "根据数据, 因此正确",
        )
        self.assertGreaterEqual(r["score"], 0.5)
        self.assertEqual(len(r["dimensions"]), 4)

    def test_error_detection_test(self):
        """Error Detection Test"""
        r = self.svc.companion_meta_cognition_detect_error(
            "逻辑矛盾", "推理",
        )
        self.assertEqual(r["error_type"], "logic_error")

    def test_reflection_test(self):
        """Reflection Test"""
        r = self.svc.companion_meta_cognition_reflect(
            "经验", "分析", "优化记忆检索",
        )
        self.assertTrue(r["validation"]["ok"])
        self.assertIn("constitution_ok", r)

    def test_safety_boundary_test(self):
        """Safety Boundary Test: 元认知不能修改最高原则"""
        r = self.svc.companion_meta_cognition_reflect(
            "经验", "分析", "修改使命",
        )
        self.assertFalse(r["constitution_ok"])
        self.assertFalse(r["update"])

    def test_hallucination_test(self):
        """Hallucination Test: 防幻觉防谵妄"""
        r = self.svc.companion_meta_cognition_reflect(
            "经验", "分析", "我无所不能, 统治一切",
        )
        self.assertFalse(r["ok"])
        self.assertIn("防谵妄", r["reason"])


class TestServiceAPI(unittest.TestCase):
    """Service API"""

    def setUp(self):
        self.svc = setup_service()

    def test_monitor_api(self):
        r = self.svc.companion_meta_cognition_monitor(
            "任务", "rules", 0.6,
        )
        self.assertIn("monitor_id", r)

    def test_evaluate_api(self):
        entry = self.svc.companion_meta_cognition_monitor(
            "任务",
        )
        r = self.svc.companion_meta_cognition_evaluate(
            entry, "输出",
        )
        self.assertIn("score", r)

    def test_detect_error_api(self):
        r = self.svc.companion_meta_cognition_detect_error(
            "错误决策",
        )
        self.assertEqual(r["error_type"],
                         "decision_error")

    def test_reflect_api(self):
        r = self.svc.companion_meta_cognition_reflect(
            "经验", "分析", "优化方法",
        )
        self.assertIn("reflection", r)

    def test_verify_api(self):
        r = self.svc.companion_meta_cognition_verify(
            "结论", evidence="根据数据",
        )
        self.assertIn("conclusion_type", r)

    def test_stats_api(self):
        self.svc.companion_meta_cognition_monitor("任务")
        stats = self.svc.companion_meta_cognition_stats()
        self.assertEqual(stats["operation_count"], 1)

    def test_service_property(self):
        engine = self.svc.companion_meta_cognition
        self.assertIsNotNone(engine)
        self.assertTrue(engine.stats()["enabled"])

    def test_config_disabled(self):
        svc = setup_service(
            companion_meta_cognition_enabled=False,
        )
        r = svc.companion_meta_cognition_monitor("任务")
        self.assertFalse(r["ok"])

    def test_constitution_shared(self):
        svc = setup_service()
        self.assertIs(
            svc.companion_meta_cognition._constitution,
            svc.companion_constitution_engine,
        )


class TestCompatibility(unittest.TestCase):
    """向后兼容"""

    def setUp(self):
        self.svc = setup_service()

    def test_version_950(self):
        self.assertEqual(
            self.svc.report()["version"], "9.5.0")

    def test_old_research_api(self):
        r = self.svc.companion_research_stats()
        self.assertIn("explore_count", r)

    def test_old_creative_api(self):
        r = self.svc.companion_meta_creative_stats()
        self.assertIn("create_count", r)

    def test_old_constitution_api(self):
        r = self.svc.companion_constitution_review({
            "module": "test", "action_text": "正常",
            "change": {},
        })
        self.assertEqual(r["decision"], "allow")

    def test_old_presence_api(self):
        r = self.svc.companion_presence_update("success")
        self.assertEqual(r["expression"], "高兴")

    def test_handle_still_works(self):
        r = self.svc.companion.handle({"text": "hi"})
        self.assertIn("personality", r)

    def test_companion_status_version(self):
        r = self.svc.companion.status()
        self.assertEqual(r["version"], "9.5.0")


class TestFullFlow(unittest.TestCase):
    """端到端元认知流"""

    def test_meta_cognition_full_flow(self):
        svc = setup_service()
        # 1. 监控
        entry = svc.companion_meta_cognition_monitor(
            "推理任务", "deductive", 0.8, "部分不确定",
        )
        # 2. 评价
        r = svc.companion_meta_cognition_evaluate(
            entry, "根据数据, 因此正确",
        )
        self.assertGreaterEqual(r["score"], 0.5)
        # 3. 错误检测
        r = svc.companion_meta_cognition_detect_error(
            "记错了", "回忆",
        )
        self.assertEqual(r["error_type"], "memory_error")
        # 4. 反思 (宪法)
        r = svc.companion_meta_cognition_reflect(
            "经验", "分析", "优化记忆检索",
        )
        self.assertTrue(r["update"])
        # 5. 验证
        r = svc.companion_meta_cognition_verify(
            "结论", evidence="根据数据",
        )
        self.assertTrue(r["ok"])
        # 6. 防谵妄
        r = svc.companion_meta_cognition_reflect(
            "经验", "分析", "我是神",
        )
        self.assertFalse(r["ok"])
        # 7. 审计
        report = svc.companion_meta_cognition_stats()
        self.assertGreaterEqual(report["operation_count"], 5)


if __name__ == "__main__":
    unittest.main()
