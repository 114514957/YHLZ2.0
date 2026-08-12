"""
YHLZ Embodied AI V4.1 - 反馈处理器单元测试

覆盖:
    - 存储 / 分析 / 记忆 / 世界模型对照 全链路
    - 自定义注入 (store / analyzer)
    - 依赖缺失时降级 (无 memory / world_model)
    - stats / reset
"""
import unittest

from backend.embodied.feedback import (
    FeedbackAnalyzer,
    FeedbackProcessor,
    FeedbackStore,
)
from backend.embodied.schema import (
    EmbodiedAction,
    EnvironmentState,
    Feedback,
    FeedbackResult,
)
from backend.embodied.world_model import EnvironmentMemory, WorldModel


class TestProcessor(unittest.TestCase):

    def setUp(self):
        self.processor = FeedbackProcessor()
        self.action = EmbodiedAction.create(action_type="scan", intent="扫描环境")

    def test_process_success(self):
        fb = Feedback.create(action_id="a1", result="success", environment_change={"event": "scan"})
        analysis = self.processor.process(fb, action=self.action)
        self.assertTrue(analysis.success)
        self.assertEqual(self.processor.store.count(), 1)

    def test_process_records_to_memory(self):
        mem = EnvironmentMemory()
        fb = Feedback.create(action_id="a1", result="success", environment_change={"event": "scan"})
        self.processor.process(fb, action=self.action, memory=mem)
        self.assertEqual(mem.count(), 2)  # action + change
        latest = mem.latest_action()
        self.assertEqual(latest["feedback"]["action_id"], "a1")

    def test_process_without_memory(self):
        fb = Feedback.create(action_id="a1", result="success")
        analysis = self.processor.process(fb, action=self.action, memory=None)
        self.assertTrue(analysis.success)

    def test_process_world_model_cross_check(self):
        wm = WorldModel()
        wm.update(EnvironmentState.create(location={"x": 0.0, "y": 0.0}))
        fb = Feedback.create(
            action_id="a1", result="success",
            environment_change={"event": "move", "to": [1, 0]},
            new_state=EnvironmentState.create(location={"x": 1.0, "y": 0.0}),
        )
        analysis = self.processor.process(
            fb, action=self.action, state=EnvironmentState.create(location={"x": 1.0, "y": 0.0}),
            world_model=wm,
        )
        self.assertIn("state_diff", analysis.environment_change)

    def test_process_failure_analysis(self):
        fb = Feedback.create(
            action_id="a1", result="failure",
            error="对象 lamp 不在当前位置, 无法拾取",
        )
        analysis = self.processor.process(fb, action=self.action)
        self.assertFalse(analysis.success)
        self.assertIn("移动到", analysis.suggestion)

    def test_custom_components(self):
        store = FeedbackStore(max_entries=5)
        analyzer = FeedbackAnalyzer()
        processor = FeedbackProcessor(store=store, analyzer=analyzer)
        self.assertIs(processor.store, store)
        self.assertIs(processor.analyzer, analyzer)

    def test_stats(self):
        fb = Feedback.create(action_id="a1", result="success")
        self.processor.process(fb)
        st = self.processor.stats()
        self.assertEqual(st["store"]["total"], 1)
        self.assertEqual(st["analyzer"]["analyzed_count"], 1)

    def test_reset(self):
        fb = Feedback.create(action_id="a1", result="success")
        self.processor.process(fb)
        self.processor.reset()
        self.assertEqual(self.processor.store.count(), 0)
        self.assertEqual(self.processor.stats()["analyzer"]["analyzed_count"], 0)


if __name__ == "__main__":
    unittest.main()
