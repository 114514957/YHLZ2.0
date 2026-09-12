"""
YHLZ Embodied AI V9.5 - 元认知引擎补充测试 9 (V9.5 Extra9)

覆盖 (生成式批量):
    - 认知记忆分类统计矩阵
    - 边界与稳定矩阵
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


# ── 认知记忆分类统计矩阵 ────────────────────────────────────────
_CAT_STAT_CASES = [
    [("cognitive_experience", True)],
    [("cognitive_experience", True),
     ("error_case", True)],
    [("cognitive_experience", True),
     ("error_case", True), ("optimization_strategy", True)],
]


class TestGeneratedCatStats(unittest.TestCase):
    """生成式: 分类统计"""
    pass


for _i, _entries in enumerate(_CAT_STAT_CASES):
    def _make(entries=_entries):
        def test(self):
            memory = CognitionMemory()
            for (cat, ok) in entries:
                memory.save(f"内容_{cat}", cat,
                            validated=ok)
            stats = memory.stats()
            self.assertEqual(stats["record_count"],
                             len(entries))
            self.assertIn("by_category", stats)
        test.__name__ = f"test_catstats_{_i}"
        test.__doc__ = f"分类统计 {len(_entries)}"
        return test
    setattr(TestGeneratedCatStats,
            _make().__name__, _make())


# ── 边界矩阵 ────────────────────────────────────────────────────
class TestBoundary2(unittest.TestCase):
    """边界"""

    def test_memory_capacity(self):
        memory = CognitionMemory(max_records=3)
        for i in range(10):
            memory.save(f"经验{i}", validated=True)
        self.assertEqual(memory.stats()[
            "record_count"], 3)

    def test_monitor_capacity(self):
        from backend.embodied.companion.meta_cognition import (
            CognitiveMonitor,
        )
        monitor = CognitiveMonitor(max_records=3)
        for i in range(10):
            monitor.record(f"任务{i}")
        self.assertEqual(monitor.stats()[
            "record_count"], 3)

    def test_evaluate_empty_entry(self):
        engine = MetaCognitionEngine()
        r = engine.evaluate({}, "")
        self.assertIn("score", r)

    def test_verify_high_conf(self):
        engine = MetaCognitionEngine()
        r = engine.verify("结论", confidence=0.95)
        self.assertIn("conclusion_type", r)

    def test_detect_error_empty(self):
        engine = MetaCognitionEngine()
        r = engine.detect_error("")
        self.assertEqual(r["error_type"], "none")


# ── 稳定矩阵 ────────────────────────────────────────────────────
class TestStability2(unittest.TestCase):
    """稳定"""

    def test_many_ops(self):
        engine = MetaCognitionEngine()
        for i in range(10):
            engine.monitor(f"任务{i}")
            engine.detect_error("记错了", f"t{i}")
            engine.verify(f"结论{i}", evidence="e")
        stats = engine.stats()
        self.assertEqual(stats["operation_count"], 30)

    def test_clear_and_reuse(self):
        engine = MetaCognitionEngine()
        engine.monitor("任务")
        engine.clear()
        r = engine.monitor("新任务")
        self.assertIn("monitor_id", r)

    def test_mixed_ops_service(self):
        svc = setup_service()
        for i in range(5):
            svc.companion_meta_cognition_monitor(
                f"任务{i}",
            )
            svc.companion_meta_cognition_reflect(
                f"经验{i}", "分析", "优化方法",
            )
        stats = svc.companion_meta_cognition_stats()
        self.assertEqual(stats["operation_count"], 10)


# ── 服务最终矩阵 ────────────────────────────────────────────────
class TestServiceFinal(unittest.TestCase):
    """服务最终"""

    def test_version(self):
        svc = setup_service()
        self.assertEqual(svc.report()["version"], "9.5.0")

    def test_stats_sections(self):
        svc = setup_service()
        svc.companion_meta_cognition_monitor("任务")
        stats = svc.companion_meta_cognition_stats()
        self.assertEqual(stats["mode"], "rule_based")
        self.assertTrue(stats["enabled"])

    def test_audit_traceable(self):
        svc = setup_service()
        svc.companion_meta_cognition_monitor("任务")
        replay = svc.companion_meta_cognition._audit\
            .replay()
        seq = replay["sequence"][0]
        for key in ("audit_id", "time", "task",
                    "evaluation", "error", "adjustment"):
            self.assertIn(key, seq)


if __name__ == "__main__":
    unittest.main()
