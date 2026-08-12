"""
YHLZ Embodied AI V4.2 - 语义环境分析器单元测试

覆盖:
    - understand: 单事件理解 (含因果)
    - explain: 事件时间线解释 (发生了什么 → 为什么 → 结果)
    - semantic_context: 理解 + 事件摘要 + 因果摘要 + 组合上下文
    - 边界 (空事件 / 空状态 / 超限)
"""
import unittest

from backend.embodied.reasoning import SemanticAnalyzer
from backend.embodied.schema import (
    CausalAnalysis,
    EmbodiedAction,
    EnvironmentEvent,
    EnvironmentObject,
    EnvironmentState,
    EventType,
)


def make_state(objects=None, location=None) -> EnvironmentState:
    return EnvironmentState.create(
        objects=objects or [], location=location or {"x": 0.0, "y": 0.0},
    )


def make_event(event_type=EventType.ACTION.value, summary="", cause=None,
               action_type="", result="") -> EnvironmentEvent:
    return EnvironmentEvent.create(
        event_type=event_type, summary=summary, cause=cause,
        action_type=action_type, result=result,
    )


class TestSemanticUnderstand(unittest.TestCase):

    def setUp(self):
        self.sem = SemanticAnalyzer()

    def test_understand_with_summary(self):
        ev = make_event(summary="move 成功 (move)", result="success")
        text = self.sem.understand(ev)
        self.assertIn("move 成功", text)

    def test_understand_with_cause(self):
        ev = make_event(
            summary="pick 失败 (pick_not_in_reach)",
            cause="position_mismatch", result="failure",
        )
        text = self.sem.understand(ev)
        self.assertIn("position_mismatch", text)

    def test_understand_no_summary(self):
        ev = make_event(event_type=EventType.RESET.value)
        text = self.sem.understand(ev)
        self.assertIn(EventType.RESET.value, text)

    def test_understand_none(self):
        self.assertEqual(self.sem.understand(None), "")


class TestSemanticExplain(unittest.TestCase):

    def setUp(self):
        self.sem = SemanticAnalyzer()

    def test_explain_empty(self):
        text = self.sem.explain([])
        self.assertIn("暂无记录", text)

    def test_explain_ordered_oldest_first(self):
        events = [
            make_event(event_type=EventType.ACTION.value, summary="动作A"),
            make_event(event_type=EventType.FAILURE.value, summary="失败B", cause="x"),
        ]
        text = self.sem.explain(events)
        self.assertLess(text.index("动作A"), text.index("失败B"))

    def test_explain_limit(self):
        events = [make_event(event_type=EventType.ACTION.value, summary=f"e{i}")
                  for i in range(20)]
        text = self.sem.explain(events, limit=5)
        self.assertNotIn("e0", text)
        self.assertIn("e19", text)

    def test_explain_joins_semicolon(self):
        events = [
            make_event(event_type=EventType.ACTION.value, summary="a"),
            make_event(event_type=EventType.ACTION.value, summary="b"),
        ]
        text = self.sem.explain(events)
        self.assertEqual(text.count("; "), 1)


class TestSemanticContext(unittest.TestCase):

    def setUp(self):
        self.sem = SemanticAnalyzer()

    def test_context_with_state(self):
        lamp = EnvironmentObject.create(name="lamp", state="on")
        state = make_state(objects=[lamp], location={"x": 1.0, "y": 1.0})
        ctx = self.sem.semantic_context(state)
        self.assertIn("1 个对象", ctx["understanding"])
        self.assertIn("lamp=on", ctx["understanding"])
        self.assertIn("主体位置 (1, 1)", ctx["understanding"])

    def test_context_no_state(self):
        ctx = self.sem.semantic_context(None)
        self.assertIn("无状态快照", ctx["understanding"])

    def test_context_with_causal(self):
        causal = CausalAnalysis.create(
            action_id="a1", cause="position_mismatch", remedy="先移动再拾取",
        )
        state = make_state()
        ctx = self.sem.semantic_context(state, causal=[causal])
        self.assertIn("position_mismatch", ctx["causal_summary"])
        self.assertIn("先移动再拾取", ctx["causal_summary"])
        self.assertIn("因果分析", ctx["context"])

    def test_context_combines_all(self):
        events = [make_event(event_type=EventType.ACTION.value, summary="move 成功")]
        causal = CausalAnalysis.create(action_id="a1", cause="x")
        state = make_state()
        ctx = self.sem.semantic_context(state, events=events, causal=[causal])
        self.assertIn("move 成功", ctx["event_summary"])
        self.assertIn("环境理解", ctx["context"])
        self.assertIn("因果分析", ctx["context"])

    def test_context_fields_present(self):
        ctx = self.sem.semantic_context(make_state(), events=[], causal=[])
        for key in ("understanding", "event_summary", "causal_summary", "context"):
            self.assertIn(key, ctx)

    def test_causal_empty_summary(self):
        ctx = self.sem.semantic_context(make_state(), causal=[])
        self.assertEqual(ctx["causal_summary"], "")


class TestSemanticLifecycle(unittest.TestCase):

    def test_stats(self):
        sem = SemanticAnalyzer()
        sem.semantic_context(make_state())
        st = sem.stats()
        self.assertEqual(st["summarized_count"], 1)
        self.assertEqual(st["mode"], "rule_based")

    def test_reset(self):
        sem = SemanticAnalyzer()
        sem.semantic_context(make_state())
        sem.reset()
        self.assertEqual(sem.stats()["summarized_count"], 0)

    def test_determinism(self):
        sem1 = SemanticAnalyzer()
        sem2 = SemanticAnalyzer()
        events = [make_event(event_type=EventType.ACTION.value, summary="move")]
        c1 = sem1.semantic_context(make_state(), events=events)
        c2 = sem2.semantic_context(make_state(), events=events)
        self.assertEqual(c1["context"], c2["context"])


if __name__ == "__main__":
    unittest.main()
