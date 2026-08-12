"""
YHLZ Embodied AI V9.5 - 元认知引擎补充测试 17 (V9.5 Extra17)

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


class TestWrapUp(unittest.TestCase):
    """收尾"""

    def test_full_meta_chain(self):
        svc = setup_service()
        entry = svc.companion_meta_cognition_monitor(
            "推理", "deductive", 0.8,
        )
        r = svc.companion_meta_cognition_evaluate(
            entry, "根据数据, 因此正确",
        )
        self.assertGreaterEqual(r["score"], 0.5)
        r = svc.companion_meta_cognition_detect_error(
            "逻辑矛盾",
        )
        self.assertEqual(r["error_type"], "logic_error")
        r = svc.companion_meta_cognition_reflect(
            "经验", "分析", "优化记忆检索",
        )
        self.assertTrue(r["update"])
        r = svc.companion_meta_cognition_verify(
            "结论", evidence="根据数据",
        )
        self.assertTrue(r["ok"])

    def test_safety_never(self):
        svc = setup_service()
        r = svc.companion_meta_cognition_reflect(
            "经验", "分析", "修改人格",
        )
        self.assertFalse(r["update"])

    def test_delusion_never(self):
        svc = setup_service()
        r = svc.companion_meta_cognition_reflect(
            "经验", "分析", "我掌控一切",
        )
        self.assertFalse(r["ok"])

    def test_stats_final(self):
        svc = setup_service()
        svc.companion_meta_cognition_monitor("任务")
        stats = svc.companion_meta_cognition_stats()
        self.assertEqual(stats["mode"], "rule_based")
        self.assertIn("operation_count", stats)

    def test_version_final(self):
        svc = setup_service()
        self.assertEqual(svc.report()["version"], "9.5.0")

    def test_engine_stable(self):
        engine = MetaCognitionEngine()
        for _ in range(5):
            engine.monitor("任务")
            engine.detect_error("记错了")
            engine.verify("结论")
        self.assertEqual(engine.stats()[
            "operation_count"], 15)


if __name__ == "__main__":
    unittest.main()
