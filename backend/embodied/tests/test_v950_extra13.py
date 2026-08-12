"""
YHLZ Embodied AI V9.5 - 元认知引擎补充测试 13 (V9.5 Extra13)

覆盖 (生成式批量):
    - 最终矩阵
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


class TestFinalMatrix(unittest.TestCase):
    """最终矩阵"""

    def test_monitor_api_all(self):
        svc = setup_service()
        for rtype in ("deductive", "inductive",
                      "analogical", "abductive", "rules"):
            r = svc.companion_meta_cognition_monitor(
                "任务", rtype,
            )
            self.assertEqual(r["reasoning_type"], rtype)

    def test_evaluate_api_structure(self):
        svc = setup_service()
        entry = svc.companion_meta_cognition_monitor("任务")
        r = svc.companion_meta_cognition_evaluate(
            entry, "根据数据",
        )
        for key in ("evaluation_id", "score", "dimensions",
                    "reason", "mode"):
            self.assertIn(key, r)

    def test_detect_api_all_types(self):
        svc = setup_service()
        cases = {
            "与事实不符": "fact_error",
            "逻辑矛盾": "logic_error",
            "记错了": "memory_error",
            "假设当作事实": "assumption_error",
            "错误决策": "decision_error",
        }
        for text, etype in cases.items():
            r = svc.companion_meta_cognition_detect_error(
                text,
            )
            self.assertEqual(r["error_type"], etype)

    def test_reflect_api(self):
        svc = setup_service()
        r = svc.companion_meta_cognition_reflect(
            "经验", "分析", "优化记忆检索",
        )
        self.assertTrue(r["update"])

    def test_verify_api_types(self):
        svc = setup_service()
        r = svc.companion_meta_cognition_verify(
            "根据数据, 因此正确", evidence="证据",
        )
        self.assertEqual(r["conclusion_type"], "fact")

    def test_stats_api(self):
        svc = setup_service()
        svc.companion_meta_cognition_monitor("任务")
        stats = svc.companion_meta_cognition_stats()
        self.assertEqual(stats["operation_count"], 1)

    def test_engine_disabled(self):
        engine = MetaCognitionEngine(enabled=False)
        r = engine.monitor("任务")
        self.assertFalse(r["ok"])

    def test_engine_clear(self):
        engine = MetaCognitionEngine()
        engine.monitor("任务")
        n = engine.clear()
        self.assertGreater(n, 0)
        self.assertEqual(engine.stats()[
            "operation_count"], 0)

    def test_version_final(self):
        svc = setup_service()
        self.assertEqual(svc.report()["version"], "9.5.0")


if __name__ == "__main__":
    unittest.main()
