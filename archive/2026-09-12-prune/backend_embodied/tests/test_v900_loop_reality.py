"""
YHLZ Embodied AI V9.0 - 假设循环与现实验证单元测试 (Loop & Reality)

覆盖:
    - HypothesisLoop: 循环/失败有效/知识更新
    - RealityValidation: 五级分级/推测禁止
"""
import unittest

from backend.embodied.companion.research_engine import (
    HypothesisLoop,
    RealityValidation,
)
from backend.embodied.companion.research_engine.reality_validation import (
    REALITY_LEVELS,
)


class TestHypothesisLoop(unittest.TestCase):
    """假设循环"""

    def setUp(self):
        self.loop = HypothesisLoop()

    def test_run_structure(self):
        r = self.loop.run("问题", "假设", "分析", True)
        for key in ("loop_id", "question", "hypothesis",
                    "analysis", "result", "validation",
                    "knowledge_update", "mode"):
            self.assertIn(key, r)
        self.assertTrue(r["loop_id"].startswith("hl_"))

    def test_validated_updates_knowledge(self):
        r = self.loop.run("问题", "假设", "分析", True)
        self.assertTrue(r["knowledge_update"])
        self.assertTrue(r["validation"]["ok"])

    def test_failed_result_valid(self):
        """失败结果也属于有效探索数据"""
        r = self.loop.run("问题", "假设", "分析", False)
        self.assertFalse(r["validation"]["ok"])
        self.assertFalse(r["knowledge_update"])
        # 仍被记录 (有效探索)
        self.assertEqual(self.loop.stats()["loop_count"], 1)

    def test_result_text(self):
        r = self.loop.run("问题", "假设", "分析", True)
        self.assertIn("验证通过", r["result"])

    def test_result_fail_text(self):
        r = self.loop.run("问题", "假设", "分析", False)
        self.assertIn("验证失败", r["result"])

    def test_validation_reason(self):
        r = self.loop.run("问题", "假设", "分析", True,
                          "证据充分")
        self.assertEqual(r["validation"]["reason"],
                         "证据充分")

    def test_stats_by_validation(self):
        self.loop.run("q1", "h1", "a", True)
        self.loop.run("q2", "h2", "a", False)
        stats = self.loop.stats()
        self.assertEqual(stats["loop_count"], 2)
        self.assertEqual(stats["by_validation"]["ok"], 1)
        self.assertEqual(stats["by_validation"]["fail"], 1)

    def test_stats_updates(self):
        self.loop.run("q1", "h1", "a", True)
        self.loop.run("q2", "h2", "a", False)
        self.assertEqual(self.loop.stats()[
            "knowledge_updates"], 1)

    def test_history(self):
        self.loop.run("q", "h", "a", True)
        h = self.loop.history()
        self.assertEqual(len(h), 1)
        self.assertEqual(h[0]["question"], "q")

    def test_disabled(self):
        loop = HypothesisLoop(enabled=False)
        r = loop.run("q", "h", "a")
        self.assertFalse(r["ok"])
        self.assertIn("停用", r["reason"])

    def test_clear(self):
        self.loop.run("q", "h", "a", True)
        n = self.loop.clear()
        self.assertEqual(n, 1)
        self.assertEqual(self.loop.stats()["loop_count"], 0)


class TestRealityValidation(unittest.TestCase):
    """现实验证"""

    def setUp(self):
        self.validator = RealityValidation()

    def test_fact_level(self):
        r = self.validator.validate(
            "根据数据, 证据显示结果正确",
            source="local", reliability=0.9,
        )
        self.assertEqual(r["level"], "fact")
        self.assertTrue(r["ok"])

    def test_evidence_level(self):
        r = self.validator.validate(
            "来源记录显示结果",
            source="local", reliability=0.9,
        )
        self.assertEqual(r["level"], "evidence")
        self.assertTrue(r["ok"])

    def test_inference_level(self):
        r = self.validator.validate(
            "因此可能如此",
            source="unknown", reliability=0.3,
        )
        self.assertEqual(r["level"], "inference")

    def test_hypothesis_level(self):
        r = self.validator.validate(
            "这是候选方案",
            source="unknown", reliability=0.3,
        )
        self.assertEqual(r["level"], "hypothesis")

    def test_speculation_blocked(self):
        """推测禁止写入事实记忆"""
        r = self.validator.validate("", source="unknown")
        self.assertEqual(r["level"], "speculation")
        self.assertFalse(r["ok"])
        self.assertIn("推测禁止", r["reason"])

    def test_ok_means_memory_safe(self):
        r = self.validator.validate("根据数据, 结果正确",
                                    source="local")
        self.assertTrue(r["ok"])
        self.assertIn("可入长期记忆", r["reason"])

    def test_structure(self):
        r = self.validator.validate("内容", "local")
        for key in ("validation_id", "level", "ok",
                    "reason", "checks", "mode"):
            self.assertIn(key, r)
        self.assertTrue(r["validation_id"].startswith("rv_"))

    def test_checks_three(self):
        r = self.validator.validate("内容", "local")
        names = [c["name"] for c in r["checks"]]
        self.assertEqual(names, ["source", "evidence",
                                 "reasoning"])

    def test_levels_constant(self):
        self.assertEqual(REALITY_LEVELS,
                         ["fact", "evidence", "inference",
                          "hypothesis", "speculation"])

    def test_reliability_keyword(self):
        # "根据" → 来源可靠; 无证据关键词 → evidence
        r = self.validator.validate("根据记录, 结果正确")
        self.assertEqual(r["level"], "evidence")

    def test_stats(self):
        self.validator.validate("a", "local")
        self.validator.validate("", "unknown")
        stats = self.validator.stats()
        self.assertEqual(stats["validated_count"], 2)
        self.assertEqual(stats["speculation_count"], 1)

    def test_disabled(self):
        validator = RealityValidation(enabled=False)
        r = validator.validate("")
        self.assertTrue(r["ok"])
        self.assertIn("停用", r["reason"])

    def test_clear(self):
        self.validator.validate("a")
        self.validator.clear()
        self.assertEqual(self.validator.stats()[
            "validated_count"], 0)


if __name__ == "__main__":
    unittest.main()
