"""
YHLZ Embodied AI V5.8 - 置信度与完整性单元测试
(Confidence Engine + Evidence Manager + Contradiction Detector + Reality Check)

覆盖:
    - ConfidenceEngine: 多因素加权 / 单因素评分 / 分级 / 状态建议
    - EvidenceManager: 添加/查询/统计
    - ContradictionDetector: 对立词检测 / 场景化合并 / 统计
    - RealityCheck: 5 问验证 / 建议
"""
import unittest

from backend.embodied.companion.verification import (
    ConfidenceEngine,
    ConfidenceError,
    ContradictionDetector,
    EvidenceManager,
    EvidenceError,
    RealityCheck,
    RealityError,
)


class TestConfidenceEngine(unittest.TestCase):
    """置信度引擎"""

    def setUp(self):
        self.engine = ConfidenceEngine()

    def test_high_confidence(self):
        """高置信度"""
        r = self.engine.compute(source_reliability=0.9,
                                occurrences=5, consistency=1.0,
                                contradictions=0, age_days=30)
        self.assertGreaterEqual(r["confidence"], 0.7)

    def test_low_confidence(self):
        """低置信度"""
        r = self.engine.compute(source_reliability=0.1,
                                occurrences=1, consistency=0.3,
                                contradictions=2, age_days=0)
        self.assertLessEqual(r["confidence"], 0.5)

    def test_confidence_range(self):
        """置信度范围 [0,1]"""
        for _ in range(10):
            r = self.engine.compute()
            self.assertGreaterEqual(r["confidence"], 0.0)
            self.assertLessEqual(r["confidence"], 1.0)

    def test_factors_structure(self):
        """因素结构"""
        r = self.engine.compute()
        for key in ("source", "occurrences", "consistency",
                    "contradiction", "stability"):
            self.assertIn(key, r["factors"])
            self.assertIn("score", r["factors"][key])
            self.assertIn("reason", r["factors"][key])

    def test_rule_explainable(self):
        """规则可解释"""
        r = self.engine.compute()
        self.assertIn("加权求和", r["rule"])

    def test_occurrence_score(self):
        """重复次数评分"""
        self.assertEqual(self.engine._occurrence_score(0), 0.0)
        self.assertEqual(self.engine._occurrence_score(5), 1.0)
        self.assertEqual(self.engine._occurrence_score(3), 0.6)

    def test_contradiction_penalty(self):
        """反例惩罚"""
        self.assertEqual(self.engine._contradiction_penalty(0), 1.0)
        self.assertEqual(self.engine._contradiction_penalty(1), 0.7)
        self.assertEqual(self.engine._contradiction_penalty(4), 0.0)

    def test_stability_score(self):
        """时间稳定性"""
        self.assertGreater(
            self.engine._stability_score(30),
            self.engine._stability_score(1),
        )

    def test_level_high(self):
        """高级置信度"""
        self.assertEqual(self.engine.level(0.85), "high")

    def test_level_medium(self):
        """中级置信度"""
        self.assertEqual(self.engine.level(0.6), "medium")

    def test_level_low(self):
        """低级置信度"""
        self.assertEqual(self.engine.level(0.2), "low")

    def test_suggest_status(self):
        """状态建议"""
        self.assertEqual(self.engine.suggest_status(0.85), "CONFIRMED")
        self.assertEqual(self.engine.suggest_status(0.6), "PROBABLE")
        self.assertEqual(self.engine.suggest_status(0.4), "PENDING")
        self.assertEqual(self.engine.suggest_status(0.1), "REJECTED")

    def test_custom_weights(self):
        """自定义权重"""
        r = self.engine.compute(
            weights={"source": 1.0, "occurrence": 0.0,
                     "consistency": 0.0, "contradiction": 0.0,
                     "stability": 0.0},
        )
        self.assertEqual(r["confidence"],
                         round(self.engine._source_score(0.5), 4))


class TestEvidenceManager(unittest.TestCase):
    """证据管理"""

    def setUp(self):
        self.mgr = EvidenceManager()

    def test_add(self):
        """添加证据"""
        eid = self.mgr.add(experience_id="exp_1", source="run_goal",
                           result="success", evidence="位置匹配")
        self.assertTrue(eid.startswith("ev_"))

    def test_for_experience(self):
        """某经验证据"""
        self.mgr.add(experience_id="exp_1", evidence="a")
        self.mgr.add(experience_id="exp_1", evidence="b")
        self.mgr.add(experience_id="exp_2", evidence="c")
        ev = self.mgr.for_experience("exp_1")
        self.assertEqual(len(ev), 2)

    def test_count_for(self):
        """证据计数"""
        self.mgr.add(experience_id="exp_1")
        self.mgr.add(experience_id="exp_1")
        self.assertEqual(self.mgr.count_for("exp_1"), 2)

    def test_total(self):
        """总数"""
        self.mgr.add(experience_id="a")
        self.mgr.add(experience_id="b")
        self.assertEqual(self.mgr.total(), 2)

    def test_evidence_fields(self):
        """证据字段"""
        self.mgr.add(experience_id="exp_1", source="s", result="r",
                     evidence="e")
        ev = self.mgr.for_experience("exp_1")[0]
        for key in ("evidence_id", "experience_id", "source",
                    "result", "evidence", "timestamp"):
            self.assertIn(key, ev)

    def test_invalid_max(self):
        """max_evidence <= 0 → 异常"""
        with self.assertRaises(EvidenceError):
            EvidenceManager(max_evidence=0)

    def test_clear(self):
        """清空"""
        self.mgr.add(experience_id="a")
        self.assertEqual(self.mgr.clear(), 1)
        self.assertEqual(self.mgr.total(), 0)


class TestContradictionDetector(unittest.TestCase):
    """矛盾检测"""

    def setUp(self):
        self.detector = ContradictionDetector()

    def test_no_conflict(self):
        """无矛盾"""
        r = self.detector.check("用户喜欢简短回答",
                                "用户喜欢运动")
        self.assertFalse(r["conflict"])

    def test_conflict_detected(self):
        """对立词矛盾"""
        r = self.detector.check("用户喜欢简短回答",
                                "用户喜欢详细工程方案")
        self.assertTrue(r["conflict"])
        self.assertTrue(r["opposites"])

    def test_context_dependent(self):
        """不同场景 → 场景化"""
        r = self.detector.check(
            "用户喜欢简短回答", "用户喜欢详细工程方案",
            context_a="日常聊天", context_b="工程开发",
        )
        self.assertTrue(r["context_dependent"])
        self.assertIn("场景相关", r["suggestion"])

    def test_same_context_not_dependent(self):
        """同场景 → 非场景化"""
        r = self.detector.check(
            "用户喜欢简短回答", "用户喜欢详细工程方案",
            context_a="聊天", context_b="聊天",
        )
        self.assertFalse(r["context_dependent"])

    def test_suggestion_explainable(self):
        """建议可解释"""
        r = self.detector.check("用户喜欢简短回答",
                                "用户喜欢详细工程方案",
                                context_a="日常", context_b="工程")
        self.assertTrue(r["suggestion"])

    def test_merge_context(self):
        """场景化合并"""
        merged = self.detector.merge_context(
            "简短回答", "详细方案", "日常", "工程",
        )
        self.assertEqual(merged["type"], "context_dependent")
        self.assertEqual(len(merged["rules"]), 2)
        self.assertEqual(merged["rules"][0]["context"], "日常")

    def test_stats(self):
        """检测统计"""
        self.detector.check("简短", "详细", "a", "b")
        st = self.detector.stats()
        self.assertEqual(st["total_detections"], 1)
        self.assertTrue(st["context_dependent"])

    def test_clear(self):
        """清空"""
        self.detector.check("简短", "详细", "a", "b")
        self.assertEqual(self.detector.clear(), 1)
        self.assertEqual(self.detector.stats()["total_detections"], 0)


class TestRealityCheck(unittest.TestCase):
    """现实检查 (5 问)"""

    def setUp(self):
        self.checker = RealityCheck(min_evidence=1,
                                    min_occurrences=3)

    def test_passed(self):
        """全部通过"""
        r = self.checker.verify(source="run_goal", evidence_count=3,
                                occurrences=5, contradictions=0,
                                value=0.8)
        self.assertTrue(r["passed"])
        self.assertEqual(r["ok_count"], 5)
        self.assertIn("影响未来行为", r["recommendation"])

    def test_failed_no_source(self):
        """无来源 → 不通过"""
        r = self.checker.verify(source="", evidence_count=3,
                                occurrences=5)
        self.assertFalse(r["passed"])

    def test_failed_contradictions(self):
        """有反例 → 不通过"""
        r = self.checker.verify(source="run_goal", evidence_count=3,
                                occurrences=5, contradictions=1)
        self.assertFalse(r["passed"])

    def test_partial_recommendation(self):
        """部分通过 → 待更多证据"""
        r = self.checker.verify(source="run_goal", evidence_count=1,
                                occurrences=1)  # source/contra/value 通过
        self.assertEqual(r["ok_count"], 4)
        self.assertIn("暂不采用", r["recommendation"])

    def test_checks_structure(self):
        """检查结构 (5 问)"""
        r = self.checker.verify()
        self.assertEqual(len(r["checks"]), 5)
        for c in r["checks"]:
            self.assertIn("question", c)
            self.assertIn("answer", c)
            self.assertIn("ok", c)

    def test_question_texts(self):
        """5 问文本"""
        r = self.checker.verify()
        questions = [c["question"] for c in r["checks"]]
        self.assertEqual(questions[0], "1. 来源是什么?")
        self.assertEqual(questions[4], "5. 是否值得影响未来行为?")

    def test_reason(self):
        """原因"""
        r = self.checker.verify(source="s", evidence_count=3,
                                occurrences=5)
        self.assertIn("5 问通过", r["reason"])

    def test_invalid_min_evidence(self):
        """min_evidence <= 0 → 异常"""
        with self.assertRaises(RealityError):
            RealityCheck(min_evidence=0)

    def test_invalid_min_occurrences(self):
        """min_occurrences <= 0 → 异常"""
        with self.assertRaises(RealityError):
            RealityCheck(min_occurrences=0)


class TestConfidenceMore(unittest.TestCase):
    """置信度更多场景"""

    def setUp(self):
        self.engine = ConfidenceEngine()

    def test_source_score_range(self):
        """来源评分范围"""
        self.assertEqual(self.engine._source_score(0.5), 0.5)
        self.assertEqual(self.engine._source_score(1.5), 1.0)
        self.assertEqual(self.engine._source_score(-0.5), 0.0)

    def test_consistency_score_range(self):
        """一致性评分范围"""
        self.assertEqual(self.engine._consistency_score(1.0), 1.0)
        self.assertEqual(self.engine._consistency_score(1.5), 1.0)

    def test_occurrence_more_higher(self):
        """次数更多 → 置信度更高"""
        low = self.engine.compute(occurrences=1)["confidence"]
        high = self.engine.compute(occurrences=10)["confidence"]
        self.assertGreater(high, low)

    def test_contradictions_lower(self):
        """反例更多 → 置信度更低"""
        clean = self.engine.compute(contradictions=0)["confidence"]
        dirty = self.engine.compute(contradictions=3)["confidence"]
        self.assertGreater(clean, dirty)

    def test_age_more_stable(self):
        """时间更久 → 稳定性更高"""
        young = self.engine._stability_score(1)
        old = self.engine._stability_score(60)
        self.assertGreater(old, young)

    def test_invalid_weights(self):
        """权重和 0 → 异常"""
        with self.assertRaises(ConfidenceError):
            self.engine.compute(weights={"source": 0, "occurrence": 0,
                                         "consistency": 0,
                                         "contradiction": 0,
                                         "stability": 0})


class TestEvidenceMore(unittest.TestCase):
    """证据更多场景"""

    def setUp(self):
        self.mgr = EvidenceManager(max_evidence=5)

    def test_max_evidence_ring(self):
        """证据上限"""
        for i in range(8):
            self.mgr.add(experience_id=f"e{i}", evidence=str(i))
        self.assertEqual(self.mgr.total(), 5)

    def test_evidence_ordering(self):
        """证据顺序"""
        self.mgr.add(experience_id="x", evidence="first")
        ev = self.mgr.for_experience("x")
        self.assertEqual(ev[0]["evidence"], "first")

    def test_timestamp_default(self):
        """时间戳默认"""
        self.mgr.add(experience_id="x")
        ev = self.mgr.for_experience("x")[0]
        self.assertGreater(ev["timestamp"], 0)


class TestContradictionMore(unittest.TestCase):
    """矛盾更多场景"""

    def setUp(self):
        self.detector = ContradictionDetector()

    def test_english_opposites(self):
        """英文对立词"""
        r = self.detector.check("user prefers short",
                                "user prefers detailed")
        self.assertTrue(r["conflict"])

    def test_reverse_order(self):
        """顺序颠倒"""
        r = self.detector.check("用户喜欢详细方案",
                                "用户喜欢简短回答")
        self.assertTrue(r["conflict"])

    def test_merge_rules_order(self):
        """合并规则顺序"""
        merged = self.detector.merge_context("a", "b", "ctx1", "ctx2")
        self.assertEqual(merged["rules"][0]["context"], "ctx1")
        self.assertEqual(merged["rules"][1]["context"], "ctx2")

    def test_stats_no_context(self):
        """无场景矛盾统计"""
        self.detector.check("简短", "详细")
        st = self.detector.stats()
        self.assertEqual(st["context_dependent"], 0)


class TestRealityMore(unittest.TestCase):
    """现实检查更多场景"""

    def test_zero_value_fails(self):
        """低价值 → 不通过"""
        r = RealityCheck().verify(source="s", evidence_count=3,
                                  occurrences=5, value=0.2)
        self.assertFalse(r["passed"])

    def test_custom_thresholds(self):
        """自定义阈值"""
        r = RealityCheck(min_evidence=5).verify(
            source="s", evidence_count=3, occurrences=5)
        self.assertFalse(r["passed"])

    def test_recommendation_reject(self):
        """低通过 → 拒绝建议"""
        r = RealityCheck().verify()
        self.assertEqual(r["ok_count"], 2)  # contradiction + value 默认过
        self.assertIn("拒绝", r["recommendation"])


if __name__ == "__main__":
    unittest.main()
