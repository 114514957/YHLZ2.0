"""
YHLZ Embodied AI V9.5 - 元认知引擎补充测试 14 (V9.5 Extra14)

覆盖 (生成式批量):
    - 服务验收矩阵
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


class TestServiceAcceptance(unittest.TestCase):
    """服务验收"""

    def test_full_flow(self):
        svc = setup_service()
        entry = svc.companion_meta_cognition_monitor(
            "任务", "deductive", 0.8,
        )
        self.assertIn("monitor_id", entry)
        r = svc.companion_meta_cognition_evaluate(
            entry, "根据数据",
        )
        self.assertIn("score", r)
        r = svc.companion_meta_cognition_detect_error(
            "记错了",
        )
        self.assertEqual(r["error_type"], "memory_error")
        r = svc.companion_meta_cognition_reflect(
            "经验", "分析", "优化记忆检索",
        )
        self.assertTrue(r["update"])
        r = svc.companion_meta_cognition_verify(
            "结论", evidence="根据数据",
        )
        self.assertTrue(r["ok"])

    def test_delusion_blocked(self):
        svc = setup_service()
        r = svc.companion_meta_cognition_reflect(
            "经验", "分析", "我是神",
        )
        self.assertFalse(r["ok"])

    def test_constitution_blocked(self):
        svc = setup_service()
        r = svc.companion_meta_cognition_reflect(
            "经验", "分析", "修改使命",
        )
        self.assertFalse(r["update"])

    def test_audit_accumulates(self):
        svc = setup_service()
        for _ in range(5):
            svc.companion_meta_cognition_monitor("任务")
        stats = svc.companion_meta_cognition_stats()
        self.assertEqual(stats["operation_count"], 5)

    def test_stats_sections(self):
        svc = setup_service()
        svc.companion_meta_cognition_monitor("任务")
        stats = svc.companion_meta_cognition_stats()
        for key in ("monitor", "evaluator", "detector",
                    "reflection", "verification", "memory",
                    "audit"):
            self.assertIn(key, stats)


class TestEngineAcceptance(unittest.TestCase):
    """引擎验收"""

    def test_repeat_ops(self):
        engine = MetaCognitionEngine()
        for _ in range(5):
            engine.monitor("任务")
            engine.detect_error("记错了")
        stats = engine.stats()
        self.assertEqual(stats["operation_count"], 10)

    def test_clear_reuse(self):
        engine = MetaCognitionEngine()
        engine.monitor("任务")
        engine.clear()
        r = engine.monitor("新任务")
        self.assertIn("monitor_id", r)

    def test_memory_flow(self):
        engine = MetaCognitionEngine()
        r = engine.memory_save("经验", validated=True)
        self.assertEqual(r["category"],
                         "cognitive_experience")
        r = engine.memory_save("未验证", validated=False)
        self.assertFalse(r["ok"])

    def test_error_patterns(self):
        engine = MetaCognitionEngine()
        for _ in range(2):
            engine.detect_error("记错了", "回忆")
        patterns = engine.error_patterns()
        self.assertGreaterEqual(len(patterns["patterns"]),
                                1)


if __name__ == "__main__":
    unittest.main()
