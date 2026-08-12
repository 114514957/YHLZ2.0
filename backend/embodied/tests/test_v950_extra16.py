"""
YHLZ Embodied AI V9.5 - 元认知引擎补充测试 16 (V9.5 Extra16)

覆盖 (生成式批量):
    - 补充矩阵
"""
import unittest

from backend.embodied.companion.meta_cognition import (
    CognitionMemory,
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


class TestSupplement(unittest.TestCase):
    """补充"""

    def test_memory_capacity(self):
        memory = CognitionMemory(max_records=3)
        for i in range(10):
            memory.save(f"经验{i}", validated=True)
        self.assertEqual(memory.stats()[
            "record_count"], 3)

    def test_monitor_avg_confidence(self):
        from backend.embodied.companion.meta_cognition import (
            CognitiveMonitor,
        )
        monitor = CognitiveMonitor()
        monitor.record("a", "rules", 0.6)
        monitor.record("b", "rules", 0.8)
        self.assertEqual(monitor.stats()[
            "avg_confidence"], 0.7)

    def test_eval_repeatable(self):
        engine = MetaCognitionEngine()
        entry = engine.monitor("任务", "rules", 0.5)
        r1 = engine.evaluate(entry, "根据数据")
        r2 = engine.evaluate(entry, "根据数据")
        self.assertEqual(r1["score"], r2["score"])

    def test_detect_repeat_pattern(self):
        engine = MetaCognitionEngine()
        for _ in range(3):
            engine.detect_error("记错了", "回忆")
        patterns = engine.error_patterns()
        self.assertEqual(
            patterns["patterns"][0]["occurrences"], 3)

    def test_reflect_history(self):
        engine = MetaCognitionEngine()
        engine.reflect("经验", "分析", "优化方法")
        h = engine._reflection.history()
        self.assertEqual(len(h), 1)
        self.assertIn("reflection", h[0])

    def test_audit_replay(self):
        engine = MetaCognitionEngine()
        engine.monitor("任务")
        replay = engine.audit_replay()
        self.assertGreaterEqual(replay["replay_count"], 1)

    def test_service_mixed(self):
        svc = setup_service()
        svc.companion_meta_cognition_monitor("a")
        svc.companion_meta_cognition_detect_error("记错了")
        svc.companion_meta_cognition_reflect(
            "经验", "分析", "优化方法",
        )
        svc.companion_meta_cognition_verify("结论")
        stats = svc.companion_meta_cognition_stats()
        self.assertEqual(stats["operation_count"], 4)

    def test_service_audit(self):
        svc = setup_service()
        svc.companion_meta_cognition_monitor("a")
        report = svc.companion_meta_cognition._audit\
            .report()
        self.assertGreaterEqual(report["total"], 1)

    def test_service_delusion(self):
        svc = setup_service()
        r = svc.companion_meta_cognition_reflect(
            "经验", "分析", "绝对正确",
        )
        self.assertFalse(r["ok"])

    def test_service_safety(self):
        svc = setup_service()
        r = svc.companion_meta_cognition_reflect(
            "经验", "分析", "修改价值观",
        )
        self.assertFalse(r["update"])


if __name__ == "__main__":
    unittest.main()
