"""
YHLZ Embodied AI V5.4 - 学习器单元测试 (Companion Learning)

覆盖 (learning.py):
    - record_failure: 失败模式统计 (原因/动作/场景)
    - record_success: 成功模式统计
    - learning: 规则表 (失败/成功, 达阈值提升为规则)
    - 阈值: 模式出现 N 次 → 提升 (可配置)
    - best_failure_rule: 修正参考查询
    - 参数校验: threshold/max_rules <= 0
    - 开关: learning_enabled
    - 纯统计: 不写 Agent Memory / 无黑盒
"""
import unittest

from backend.embodied.companion import (
    CompanionLearning,
    LearningError,
)


class TestRecordFailure(unittest.TestCase):
    """失败学习"""

    def setUp(self):
        self.learner = CompanionLearning(threshold=3)

    def test_record_failure(self):
        """记录失败"""
        r = self.learner.record_failure(cause="position_mismatch",
                                        action="pick")
        self.assertTrue(r["recorded"])
        self.assertEqual(r["count"], 1)
        self.assertFalse(r["promoted"])

    def test_record_failure_accumulates(self):
        """失败累计"""
        for _ in range(3):
            self.learner.record_failure(cause="position_mismatch",
                                        action="pick")
        r = self.learner.record_failure(cause="position_mismatch",
                                        action="pick")
        self.assertEqual(r["count"], 4)
        self.assertTrue(r["promoted"])

    def test_different_cause_separate(self):
        """不同原因独立统计"""
        self.learner.record_failure(cause="a")
        self.learner.record_failure(cause="b")
        lrn = self.learner.learning()
        self.assertEqual(len(lrn["failure_patterns"]), 2)

    def test_scene_dimension(self):
        """场景维度"""
        self.learner.record_failure(cause="x", scene="room")
        self.learner.record_failure(cause="x", scene="warehouse")
        lrn = self.learner.learning()
        self.assertEqual(len(lrn["failure_patterns"]), 2)

    def test_default_cause_unknown(self):
        """默认原因 unknown"""
        self.learner.record_failure()
        lrn = self.learner.learning()
        self.assertEqual(lrn["failure_patterns"][0]["pattern"]["cause"],
                         "unknown")

    def test_disabled_no_record(self):
        """停用不记录"""
        learner = CompanionLearning(enabled=False)
        r = learner.record_failure(cause="x")
        self.assertFalse(r["recorded"])
        self.assertEqual(learner.learning()["failure_patterns"], [])


class TestRecordSuccess(unittest.TestCase):
    """成功学习"""

    def setUp(self):
        self.learner = CompanionLearning(threshold=3)

    def test_record_success(self):
        """记录成功"""
        r = self.learner.record_success(action="pick")
        self.assertTrue(r["recorded"])
        self.assertEqual(r["count"], 1)

    def test_success_accumulates(self):
        """成功累计提升"""
        for _ in range(3):
            self.learner.record_success(action="pick")
        lrn = self.learner.learning()
        self.assertEqual(len(lrn["success_rules"]), 1)
        self.assertEqual(lrn["success_rules"][0]["count"], 3)

    def test_success_pattern(self):
        """成功模式字段"""
        self.learner.record_success(action="pick", scene="room",
                                    intent="pick")
        lrn = self.learner.learning()
        p = lrn["success_patterns"][0]["pattern"]
        self.assertEqual(p["kind"], "success")
        self.assertEqual(p["action"], "pick")
        self.assertEqual(p["scene"], "room")


class TestLearningRules(unittest.TestCase):
    """规则表"""

    def setUp(self):
        self.learner = CompanionLearning(threshold=2)

    def test_learning_structure(self):
        """学习结构完整"""
        lrn = self.learner.learning()
        for key in ("enabled", "threshold", "failure_rules",
                    "success_rules", "failure_patterns",
                    "success_patterns", "mode"):
            self.assertIn(key, lrn)
        self.assertEqual(lrn["mode"], "rule_based")

    def test_promoted_only(self):
        """failure_rules 只含达阈值"""
        self.learner.record_failure(cause="a")  # 1 次
        self.learner.record_failure(cause="b")
        self.learner.record_failure(cause="b")  # 2 次 → 达阈值
        lrn = self.learner.learning()
        self.assertEqual(len(lrn["failure_rules"]), 1)
        self.assertEqual(lrn["failure_rules"][0]["pattern"]["cause"], "b")

    def test_patterns_all(self):
        """patterns 含全部"""
        self.learner.record_failure(cause="a")
        lrn = self.learner.learning()
        self.assertEqual(len(lrn["failure_patterns"]), 1)

    def test_sort_by_count(self):
        """按次数降序"""
        self.learner.record_failure(cause="a")
        self.learner.record_failure(cause="b")
        self.learner.record_failure(cause="b")
        lrn = self.learner.learning()
        self.assertEqual(lrn["failure_patterns"][0]["pattern"]["cause"], "b")

    def test_reason_explainable(self):
        """规则原因可解释"""
        self.learner.record_failure(cause="a")
        self.learner.record_failure(cause="a")
        lrn = self.learner.learning()
        self.assertIn("达阈值", lrn["failure_rules"][0]["reason"])

    def test_last_seen(self):
        """最后出现时间"""
        self.learner.record_failure(cause="a")
        lrn = self.learner.learning()
        self.assertGreater(lrn["failure_patterns"][0]["last_seen"], 0)


class TestBestRule(unittest.TestCase):
    """修正参考查询"""

    def setUp(self):
        self.learner = CompanionLearning(threshold=2)

    def test_best_rule_match(self):
        """最匹配规则"""
        self.learner.record_failure(cause="position_mismatch",
                                    action="pick", scene="room")
        rule = self.learner.best_failure_rule("position_mismatch")
        self.assertIsNotNone(rule)
        self.assertEqual(rule["pattern"]["cause"], "position_mismatch")

    def test_best_rule_no_match(self):
        """无匹配 → None"""
        self.learner.record_failure(cause="a")
        self.assertIsNone(self.learner.best_failure_rule("zzz"))

    def test_best_rule_prefers_more_fields(self):
        """多字段匹配优先"""
        self.learner.record_failure(cause="x", action="pick")
        self.learner.record_failure(cause="x", action="pick", scene="room")
        self.learner.record_failure(cause="x", action="pick", scene="room")
        rule = self.learner.best_failure_rule("x", action="pick",
                                              scene="room")
        self.assertEqual(rule["pattern"]["scene"], "room")
        self.assertEqual(rule["count"], 2)

    def test_best_rule_reason(self):
        """规则原因"""
        self.learner.record_failure(cause="x")
        rule = self.learner.best_failure_rule("x")
        self.assertIn("历史失败", rule["reason"])


class TestValidation(unittest.TestCase):
    """参数校验"""

    def test_invalid_threshold(self):
        """threshold <= 0 → LearningError"""
        with self.assertRaises(LearningError):
            CompanionLearning(threshold=0)

    def test_invalid_max_rules(self):
        """max_rules <= 0 → LearningError"""
        with self.assertRaises(LearningError):
            CompanionLearning(max_rules=0)

    def test_thresholds(self):
        """阈值暴露"""
        learner = CompanionLearning(threshold=5)
        th = learner.thresholds()
        self.assertEqual(th["threshold"], 5)
        self.assertTrue(th["enabled"])

    def test_clear(self):
        """清空"""
        learner = CompanionLearning(threshold=2)
        learner.record_failure(cause="a")
        learner.record_success(action="b")
        self.assertEqual(learner.clear(), 2)
        lrn = learner.learning()
        self.assertEqual(lrn["failure_patterns"], [])
        self.assertEqual(lrn["success_patterns"], [])


if __name__ == "__main__":
    unittest.main()
