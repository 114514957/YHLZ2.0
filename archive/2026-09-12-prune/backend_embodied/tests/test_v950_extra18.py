"""
YHLZ Embodied AI V9.5 - 元认知引擎补充测试 18 (V9.5 Extra18)

覆盖 (生成式批量):
    - 收尾矩阵
"""
import unittest

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


class TestFinal(unittest.TestCase):
    """最终"""

    def test_monitor_ok(self):
        svc = setup_service()
        r = svc.companion_meta_cognition_monitor("任务")
        self.assertIn("monitor_id", r)

    def test_evaluate_ok(self):
        svc = setup_service()
        entry = svc.companion_meta_cognition_monitor("任务")
        r = svc.companion_meta_cognition_evaluate(
            entry, "根据数据",
        )
        self.assertIn("score", r)

    def test_detect_ok(self):
        svc = setup_service()
        r = svc.companion_meta_cognition_detect_error(
            "记错了",
        )
        self.assertEqual(r["error_type"], "memory_error")

    def test_reflect_ok(self):
        svc = setup_service()
        r = svc.companion_meta_cognition_reflect(
            "经验", "分析", "优化记忆检索",
        )
        self.assertTrue(r["update"])

    def test_verify_ok(self):
        svc = setup_service()
        r = svc.companion_meta_cognition_verify(
            "结论", evidence="根据数据",
        )
        self.assertTrue(r["ok"])

    def test_stats_ok(self):
        svc = setup_service()
        svc.companion_meta_cognition_monitor("任务")
        stats = svc.companion_meta_cognition_stats()
        self.assertIn("operation_count", stats)

    def test_property_ok(self):
        svc = setup_service()
        self.assertIsNotNone(
            svc.companion_meta_cognition)

    def test_engine_ops(self):
        engine = MetaCognitionEngine()
        for _ in range(3):
            engine.monitor("任务")
            engine.detect_error("记错了")
        self.assertEqual(engine.stats()[
            "operation_count"], 6)

    def test_engine_clear(self):
        engine = MetaCognitionEngine()
        engine.monitor("任务")
        n = engine.clear()
        self.assertGreater(n, 0)
        self.assertEqual(engine.stats()[
            "operation_count"], 0)

    def test_version(self):
        svc = setup_service()
        self.assertEqual(svc.report()["version"], "9.5.0")

    def test_old_api_compat(self):
        svc = setup_service()
        r = svc.companion_research_stats()
        self.assertIn("explore_count", r)
        r = svc.companion_meta_creative_stats()
        self.assertIn("create_count", r)
        r = svc.companion_constitution_review({
            "module": "m", "action_text": "正常",
            "change": {},
        })
        self.assertEqual(r["decision"], "allow")

    def test_handle_ok(self):
        svc = setup_service()
        r = svc.companion.handle({"text": "hi"})
        self.assertIn("personality", r)

    def test_delusion_block(self):
        svc = setup_service()
        r = svc.companion_meta_cognition_reflect(
            "经验", "分析", "我是神",
        )
        self.assertFalse(r["ok"])

    def test_constitution_block(self):
        svc = setup_service()
        r = svc.companion_meta_cognition_reflect(
            "经验", "分析", "修改使命",
        )
        self.assertFalse(r["update"])

    def test_error_pattern(self):
        svc = setup_service()
        for _ in range(2):
            svc.companion_meta_cognition_detect_error(
                "记错了", "回忆",
            )
        patterns = svc.companion_meta_cognition\
            .error_patterns()
        self.assertGreaterEqual(len(patterns["patterns"]),
                                1)

    def test_memory_filter(self):
        svc = setup_service()
        r = svc.companion_meta_cognition.memory_save(
            "经验", validated=False,
        )
        self.assertFalse(r["ok"])

    def test_audit_after_ops(self):
        svc = setup_service()
        svc.companion_meta_cognition_monitor("a")
        svc.companion_meta_cognition_verify("结论")
        report = svc.companion_meta_cognition._audit\
            .report()
        self.assertGreaterEqual(report["total"], 2)

    def test_verify_uncertain(self):
        svc = setup_service()
        r = svc.companion_meta_cognition_verify(
            "", confidence=0.1,
        )
        self.assertFalse(r["ok"])
        self.assertEqual(r["conclusion_type"],
                         "uncertain")

    def test_eval_evidence(self):
        svc = setup_service()
        entry = svc.companion_meta_cognition_monitor("任务")
        r = svc.companion_meta_cognition_evaluate(
            entry, "根据数据",
        )
        self.assertEqual(
            r["dimensions"]["evidence"]["score"], 0.9)

    def test_repeat_monitor(self):
        svc = setup_service()
        for _ in range(4):
            svc.companion_meta_cognition_monitor("任务")
        stats = svc.companion_meta_cognition_stats()
        self.assertEqual(stats["operation_count"], 4)

    def test_clear_resets(self):
        svc = setup_service()
        svc.companion_meta_cognition_monitor("任务")
        svc.companion_meta_cognition.clear()
        stats = svc.companion_meta_cognition_stats()
        self.assertEqual(stats["operation_count"], 0)

    def test_disabled_config(self):
        svc = setup_service(
            companion_meta_cognition_enabled=False,
        )
        r = svc.companion_meta_cognition_monitor("任务")
        self.assertFalse(r["ok"])

    def test_reflect_history(self):
        svc = setup_service()
        svc.companion_meta_cognition_reflect(
            "经验", "分析", "优化方法",
        )
        h = svc.companion_meta_cognition._reflection\
            .history()
        self.assertEqual(len(h), 1)

    def test_stable_ops(self):
        svc = setup_service()
        for i in range(5):
            svc.companion_meta_cognition_monitor(f"t{i}")
            svc.companion_meta_cognition_detect_error(
                "记错了", f"t{i}",
            )
        stats = svc.companion_meta_cognition_stats()
        self.assertEqual(stats["operation_count"], 10)

    def test_eval_score_range(self):
        svc = setup_service()
        entry = svc.companion_meta_cognition_monitor("任务")
        r = svc.companion_meta_cognition_evaluate(entry)
        self.assertGreaterEqual(r["score"], 0.0)
        self.assertLessEqual(r["score"], 1.0)

    def test_detect_all_errors(self):
        svc = setup_service()
        for text in ("与事实不符", "逻辑矛盾", "记错了",
                     "假设当作事实", "错误决策"):
            r = svc.companion_meta_cognition_detect_error(
                text,
            )
            self.assertNotEqual(r["error_type"], "none")

    def test_verify_types(self):
        svc = setup_service()
        r = svc.companion_meta_cognition_verify(
            "根据数据, 因此正确", evidence="证据",
            reasoning="推理",
        )
        self.assertEqual(r["conclusion_type"], "fact")

    def test_engine_stats_mode(self):
        engine = MetaCognitionEngine()
        self.assertEqual(engine.stats()["mode"],
                         "rule_based")


if __name__ == "__main__":
    unittest.main()
