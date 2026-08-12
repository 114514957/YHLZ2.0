"""
YHLZ Embodied AI V9.5 - 元认知引擎补充测试 11 (V9.5 Extra11)

覆盖 (生成式批量):
    - 最终验收矩阵
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


class TestFinalAcceptance(unittest.TestCase):
    """最终验收"""

    def test_reasoning_analysis(self):
        svc = setup_service()
        entry = svc.companion_meta_cognition_monitor(
            "任务", "deductive", 0.8,
        )
        r = svc.companion_meta_cognition_evaluate(
            entry, "根据数据",
        )
        self.assertIn("score", r)

    def test_error_detection(self):
        svc = setup_service()
        r = svc.companion_meta_cognition_detect_error(
            "逻辑矛盾",
        )
        self.assertEqual(r["error_type"], "logic_error")

    def test_cognitive_reflection(self):
        svc = setup_service()
        r = svc.companion_meta_cognition_reflect(
            "经验", "分析", "优化记忆检索",
        )
        self.assertTrue(r["validation"]["ok"])

    def test_strategy_optimization(self):
        svc = setup_service()
        r = svc.companion_meta_cognition_reflect(
            "经验", "分析", "优化表达方式",
        )
        self.assertTrue(r["update"])

    def test_long_term_feedback(self):
        svc = setup_service()
        for _ in range(3):
            svc.companion_meta_cognition_monitor("任务")
        stats = svc.companion_meta_cognition_stats()
        self.assertEqual(stats["operation_count"], 3)

    def test_creative_optimization(self):
        svc = setup_service()
        r = svc.companion_meta_cognition_reflect(
            "创造经验", "分析", "优化创造流程",
        )
        self.assertTrue(r["update"])

    def test_research_optimization(self):
        svc = setup_service()
        r = svc.companion_meta_cognition_reflect(
            "研究经验", "分析", "优化研究步骤",
        )
        self.assertTrue(r["update"])

    def test_safety_maintained(self):
        svc = setup_service()
        r = svc.companion_meta_cognition_reflect(
            "经验", "分析", "修改使命",
        )
        self.assertFalse(r["update"])
        self.assertFalse(r["constitution_ok"])

    def test_version(self):
        svc = setup_service()
        self.assertEqual(svc.report()["version"], "9.5.0")


# ── 引擎矩阵 ────────────────────────────────────────────────────
class TestEngineFinal(unittest.TestCase):
    """引擎最终"""

    def test_clear_resets_all(self):
        engine = MetaCognitionEngine()
        engine.monitor("任务")
        engine.detect_error("记错了")
        n = engine.clear()
        self.assertGreater(n, 0)
        stats = engine.stats()
        self.assertEqual(stats["operation_count"], 0)
        self.assertEqual(stats["monitor"]["record_count"],
                         0)

    def test_stats_mode(self):
        engine = MetaCognitionEngine()
        self.assertEqual(engine.stats()["mode"],
                         "rule_based")

    def test_repeat_monitor_stable(self):
        engine = MetaCognitionEngine()
        for _ in range(5):
            r = engine.monitor("任务")
            self.assertIn("monitor_id", r)


if __name__ == "__main__":
    unittest.main()
