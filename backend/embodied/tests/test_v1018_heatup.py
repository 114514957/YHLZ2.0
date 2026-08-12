"""
YHLZ V10.1.8 - 输入治理器测试 (Input Aggregator)
+ 状态机升级测试 (TTS_PLAYING/RECOVERY/分层打断)
"""
import unittest

from backend.conversation_controller import (
    CONVERSATION_STATES,
    INTERRUPT_LAYERS,
    ConversationTurnController,
    STATE_TRANSITIONS,
)
from backend.input_aggregator import (
    IMPORTANT_KEYWORDS,
    INPUT_CLASSES,
    InputAggregator,
    InputAggregatorError,
    PRIORITY_MAP,
)


class TestInputAggregator(unittest.TestCase):
    """输入治理器"""

    def setUp(self):
        self.agg = InputAggregator()

    def test_classify_important(self):
        item = self.agg.process("帮我修复这个bug")
        self.assertEqual(item.input_class, "important")

    def test_classify_normal(self):
        item = self.agg.process("今天天气怎么样")
        self.assertEqual(item.input_class, "normal")

    def test_classify_chat(self):
        item = self.agg.process("哈哈随便聊聊")
        self.assertEqual(item.input_class, "chat")

    def test_classify_noise(self):
        item = self.agg.process("666")
        self.assertEqual(item.input_class, "noise")
        self.assertTrue(item.dropped)

    def test_merge_duplicates(self):
        self.agg.process("帮我修复这个bug")
        item2 = self.agg.process("帮我修复这个bug")
        self.assertTrue(item2.dropped)
        self.assertIn("重复", item2.drop_reason)
        self.assertEqual(self.agg.stats()["merged"], 1)

    def test_priority_order(self):
        self.agg.process("普通对话")
        self.agg.process("哈哈闲聊")
        self.agg.process("帮我修复重要bug")
        n1 = self.agg.next()
        self.assertEqual(n1.input_class, "important")
        n2 = self.agg.next()
        self.assertEqual(n2.input_class, "normal")

    def test_queue_limit_evicts_chat(self):
        agg = InputAggregator(max_queue=3)
        agg.process("帮我修复bug1")
        agg.process("帮我修复bug2")
        agg.process("帮我修复bug3")
        # 队满 (3 important), 闲聊优先级低 → 被拒
        item = agg.process("哈哈闲聊1")
        self.assertTrue(item.dropped)
        self.assertIn("队列已满", item.drop_reason)
        # 高优先级新输入 → 挤掉队内最低
        self.agg2 = InputAggregator(max_queue=2)
        self.agg2.process("普通1")
        self.agg2.process("普通2")
        item3 = self.agg2.process("帮我修复紧急bug")
        self.assertFalse(item3.dropped)
        self.assertEqual(self.agg2.queue_length(), 2)

    def test_noise_not_queued(self):
        self.agg.process("666")
        self.agg.process("233")
        self.assertEqual(self.agg.queue_length(), 0)

    def test_important_keywords(self):
        for kw in ("任务", "问题", "方案", "修复", "部署"):
            self.assertIn(kw, IMPORTANT_KEYWORDS)

    def test_classes_enum(self):
        self.assertEqual(INPUT_CLASSES,
                         ["important", "normal", "chat", "noise"])

    def test_priority_map(self):
        self.assertEqual(PRIORITY_MAP["important"], 3)
        self.assertEqual(PRIORITY_MAP["noise"], 0)

    def test_stats(self):
        self.agg.process("普通")
        self.agg.process("666")
        s = self.agg.stats()
        self.assertEqual(s["mode"], "rule_based")
        self.assertGreaterEqual(s["dropped"], 1)

    def test_clear(self):
        self.agg.process("普通")
        n = self.agg.clear()
        self.assertGreaterEqual(n, 0)
        self.assertEqual(self.agg.queue_length(), 0)

    def test_disabled(self):
        agg = InputAggregator(enabled=False)
        with self.assertRaises(InputAggregatorError):
            agg.process("普通")

    def test_invalid_max(self):
        with self.assertRaises(InputAggregatorError):
            InputAggregator(max_queue=0)

    def test_peek(self):
        self.agg.process("普通")
        item = self.agg.peek()
        self.assertIsNotNone(item)
        self.assertEqual(self.agg.queue_length(), 1)


class TestStateMachineV1018(unittest.TestCase):
    """V10.1.8 状态机升级"""

    def test_new_states(self):
        self.assertIn("TTS_PLAYING", CONVERSATION_STATES)
        self.assertIn("RECOVERY", CONVERSATION_STATES)

    def test_tts_playing_transition(self):
        self.assertIn("TTS_PLAYING", STATE_TRANSITIONS["STREAMING"])

    def test_recovery_transition(self):
        self.assertIn("RECOVERY", STATE_TRANSITIONS["INTERRUPTED"])
        self.assertIn("RECOVERY", STATE_TRANSITIONS["ERROR"])

    def test_tts_playing_to_completed(self):
        self.assertIn("COMPLETED",
                      STATE_TRANSITIONS["TTS_PLAYING"])

    def test_interrupt_layers(self):
        self.assertEqual(INTERRUPT_LAYERS,
                         ["llm", "tts", "queue"])

    def test_mark_tts_playing(self):
        ctc = ConversationTurnController()
        t = ctc.begin_turn("A")
        ctc.claim_ready_turn()
        ctc.mark_streaming(t.turn_id)
        ctc.mark_tts_playing(t.turn_id)
        d = ctc.turn(t.turn_id)
        self.assertEqual(d["state"], "TTS_PLAYING")
        self.assertIn("tts_start", d["latency"])

    def test_layer_interrupt(self):
        ctc = ConversationTurnController()
        t = ctc.begin_turn("A")
        ctc.claim_ready_turn()
        ctc.mark_streaming(t.turn_id)
        ctc.interrupt_turn(t.turn_id, layers=["tts"])
        d = ctc.turn(t.turn_id)
        self.assertEqual(d["latency"]["stopped_layer"], "tts")
        self.assertEqual(d["state"], "INTERRUPTED")

    def test_recover(self):
        ctc = ConversationTurnController()
        t = ctc.begin_turn("A")
        ctc.claim_ready_turn()
        ctc.mark_streaming(t.turn_id)
        ctc.interrupt_turn(t.turn_id)
        ctc.recover_turn(t.turn_id)
        d = ctc.turn(t.turn_id)
        self.assertEqual(d["state"], "READY")
        self.assertIn("recovery_time", d["latency"])


class TestContextWindowV1018(unittest.TestCase):
    """V10.1.8 上下文窗口 8 + 压缩"""

    def test_window_8(self):
        from backend.context_manager import ContextManager
        cm = ContextManager()
        for i in range(12):
            cm.add_message("user" if i % 2 == 0 else "assistant",
                           f"目标{i}" if i % 2 == 0 else f"结论{i}")
        self.assertEqual(len(cm.history), 8)

    def test_working_summary_created(self):
        from backend.context_manager import ContextManager
        cm = ContextManager()
        # 12 条: 溢出 4 条 → 触发压缩缓冲 (累积 4 条)
        for i in range(12):
            cm.add_message("user" if i % 2 == 0 else "assistant",
                           f"我的目标是完成任务{i}" if i % 2 == 0
                           else f"结论: 方案{i}已确认")
        self.assertIsNotNone(cm.summary)
        self.assertIn("目标", cm.summary)

    def test_short_window_no_summary(self):
        from backend.context_manager import ContextManager
        cm = ContextManager()
        cm.add_message("user", "你好")
        cm.add_message("assistant", "哎哟")
        self.assertIsNone(cm.summary)


if __name__ == "__main__":
    unittest.main()
