"""
YHLZ Embodied AI V4.1 - 反馈分析器单元测试

覆盖:
    - SUCCESS → success=True + 建议
    - NO_CHANGE → success=False + 规则建议
    - PARTIAL → success=True + 部分完成
    - FAILURE → success=False + 规则建议 (按关键词匹配)
    - 未知失败 → 默认建议
    - None 输入 → 异常
    - analyze_many 批量
    - stats / reset
    - 规则表完整性 (非空 / 关键词有序)
"""
import unittest

from backend.embodied.feedback import (
    FeedbackAnalyzer,
    FeedbackAnalyzerError,
    SUGGESTION_RULES,
)
from backend.embodied.schema import (
    EmbodiedAction,
    Feedback,
    FeedbackResult,
)


class TestAnalyzerSuccess(unittest.TestCase):

    def setUp(self):
        self.analyzer = FeedbackAnalyzer()

    def test_success_result(self):
        fb = Feedback.create(action_id="a1", result="success", environment_change={"event": "scan"})
        analysis = self.analyzer.analyze(fb)
        self.assertTrue(analysis.success)
        self.assertEqual(analysis.action_id, "a1")
        self.assertIsNone(analysis.failure_reason)
        self.assertTrue(analysis.suggestion)

    def test_partial_result(self):
        fb = Feedback.create(action_id="a2", result="partial")
        analysis = self.analyzer.analyze(fb)
        self.assertTrue(analysis.success)
        self.assertEqual(analysis.failure_reason, "部分完成")


class TestAnalyzerFailure(unittest.TestCase):

    def setUp(self):
        self.analyzer = FeedbackAnalyzer()

    def test_failure_with_error(self):
        fb = Feedback.create(action_id="a3", result="failure", error="boom")
        analysis = self.analyzer.analyze(fb)
        self.assertFalse(analysis.success)
        self.assertEqual(analysis.failure_reason, "boom")

    def test_failure_without_error(self):
        fb = Feedback.create(action_id="a4", result="failure")
        analysis = self.analyzer.analyze(fb)
        self.assertFalse(analysis.success)
        self.assertTrue(analysis.failure_reason)

    def test_no_change_result(self):
        fb = Feedback.create(
            action_id="a5", result="no_change",
            environment_change={"event": "move_stationary"},
        )
        analysis = self.analyzer.analyze(fb)
        self.assertFalse(analysis.success)
        self.assertIn("无状态变化", analysis.failure_reason)


class TestSuggestionRules(unittest.TestCase):

    def setUp(self):
        self.analyzer = FeedbackAnalyzer()

    def test_pick_not_in_reach_suggestion(self):
        fb = Feedback.create(
            action_id="a1", result="failure",
            environment_change={"event": "pick_not_in_reach"},
            error="对象 lamp 不在当前位置, 无法拾取",
        )
        analysis = self.analyzer.analyze(fb)
        self.assertIn("移动到", analysis.suggestion)

    def test_move_out_of_bounds_suggestion(self):
        fb = Feedback.create(
            action_id="a2", result="no_change",
            environment_change={"event": "move_out_of_bounds"},
            error="移动越界: (5, 0) 超出网格 [5, 5]",
        )
        analysis = self.analyzer.analyze(fb)
        self.assertIn("调整移动方向", analysis.suggestion)

    def test_missing_object_suggestion(self):
        fb = Feedback.create(
            action_id="a3", result="failure",
            environment_change={"event": "pick_missing"},
            error="对象不存在: ghost",
        )
        analysis = self.analyzer.analyze(fb)
        self.assertIn("确认目标对象", analysis.suggestion)

    def test_place_not_held_suggestion(self):
        fb = Feedback.create(
            action_id="a4", result="failure",
            environment_change={"event": "place_not_held"},
            error="对象 box 未被持有, 无法放置",
        )
        analysis = self.analyzer.analyze(fb)
        self.assertIn("先执行拾取", analysis.suggestion)

    def test_unsupported_suggestion(self):
        fb = Feedback.create(
            action_id="a5", result="failure",
            error="不支持的动作类型: fly",
        )
        analysis = self.analyzer.analyze(fb)
        self.assertIn("更换", analysis.suggestion)

    def test_unknown_failure_default(self):
        fb = Feedback.create(action_id="a6", result="failure", error="某神秘错误")
        analysis = self.analyzer.analyze(fb)
        self.assertIn("重新规划", analysis.suggestion)

    def test_environment_change_referenced(self):
        fb = Feedback.create(
            action_id="a7", result="failure",
            environment_change={"event": "pick_not_in_reach"},
            error="",
        )
        analysis = self.analyzer.analyze(fb)
        self.assertIn("移动到", analysis.suggestion)


class TestAnalyzerEdgeCases(unittest.TestCase):

    def test_none_raises(self):
        with self.assertRaises(FeedbackAnalyzerError):
            FeedbackAnalyzer().analyze(None)  # type: ignore[arg-type]

    def test_with_action_context(self):
        a = EmbodiedAction.create(action_type="pick", target="lamp")
        fb = Feedback.create(action_id="a1", result="success")
        analysis = FeedbackAnalyzer().analyze(fb, action=a)
        self.assertTrue(analysis.success)

    def test_analyze_many(self):
        analyzer = FeedbackAnalyzer()
        fbs = [
            Feedback.create(action_id="a1", result="success"),
            Feedback.create(action_id="a2", result="failure", error="pick_not_in_reach"),
            Feedback.create(action_id="a3", result="no_change"),
        ]
        results = analyzer.analyze_many(fbs)
        self.assertEqual(len(results), 3)
        self.assertTrue(results[0].success)
        self.assertFalse(results[1].success)

    def test_stats(self):
        analyzer = FeedbackAnalyzer()
        analyzer.analyze(Feedback.create(result="success"))
        analyzer.analyze(Feedback.create(result="failure"))
        st = analyzer.stats()
        self.assertEqual(st["analyzed_count"], 2)
        self.assertEqual(st["mode"], "rule_based")
        self.assertGreater(st["rules_count"], 0)

    def test_reset(self):
        analyzer = FeedbackAnalyzer()
        analyzer.analyze(Feedback.create(result="success"))
        analyzer.reset()
        self.assertEqual(analyzer.stats()["analyzed_count"], 0)

    def test_environment_change_copied(self):
        fb = Feedback.create(
            action_id="a1", result="success",
            environment_change={"event": "move", "to": [1, 0]},
        )
        analysis = FeedbackAnalyzer().analyze(fb)
        self.assertEqual(analysis.environment_change["event"], "move")


class TestSuggestionTable(unittest.TestCase):

    def test_rules_non_empty(self):
        self.assertGreater(len(SUGGESTION_RULES), 5)

    def test_rules_structure(self):
        for keyword, suggestion in SUGGESTION_RULES:
            self.assertTrue(keyword)
            self.assertTrue(suggestion)


if __name__ == "__main__":
    unittest.main()
