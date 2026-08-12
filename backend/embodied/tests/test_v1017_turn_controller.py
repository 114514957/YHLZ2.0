"""
YHLZ V10.1.7 - 对话回合控制器测试 (Conversation Turn Controller)

覆盖:
    - 状态机迁移 (IDLE→RECEIVING→READY→PROCESSING→STREAMING→COMPLETED)
    - 事件协议 (START/TOKEN/FLUSH/COMPLETE + sequence 单调)
    - 打断 (INTERRUPTED + 队列推进)
    - 队列 (有序/上限/超限错误)
    - 上下文不污染 (turn 独立)
    - 延迟追踪 (TTFT/总耗时)
    - 非法输入防护
"""
import unittest

from backend.conversation_controller import (
    CONVERSATION_STATES,
    ConversationControllerError,
    ConversationTurn,
    ConversationTurnController,
    EVENT_TYPES,
    STATE_TRANSITIONS,
)


class TestTurnController(unittest.TestCase):
    """对话回合控制器"""

    def setUp(self):
        self.ctc = ConversationTurnController()

    def test_begin_turn(self):
        t = self.ctc.begin_turn("你好")
        self.assertEqual(t.state, "READY")
        self.assertTrue(t.turn_id.startswith("turn_"))
        self.assertTrue(t.conversation_id.startswith("conv_"))

    def test_turn_fields(self):
        t = self.ctc.begin_turn("测试输入")
        d = t.to_dict()
        for key in ("conversation_id", "turn_id", "input_text",
                    "content_hash", "source", "state", "created_at",
                    "updated_at", "sequence", "response_text",
                    "error", "latency", "interrupted"):
            self.assertIn(key, d)

    def test_content_hash(self):
        t1 = self.ctc.begin_turn("相同文本")
        t2 = self.ctc.begin_turn("相同文本")  # 但 t1 占活跃, t2 入队
        self.assertEqual(t1.content_hash, t2.content_hash)

    def test_claim_ready(self):
        t = self.ctc.begin_turn("你好")
        claimed = self.ctc.claim_ready_turn()
        self.assertEqual(claimed.turn_id, t.turn_id)
        self.assertEqual(claimed.state, "PROCESSING")

    def test_mark_streaming(self):
        t = self.ctc.begin_turn("你好")
        self.ctc.claim_ready_turn()
        self.ctc.mark_streaming(t.turn_id)
        self.assertEqual(self.ctc.turn(t.turn_id)["state"],
                         "STREAMING")

    def test_complete_cycle(self):
        t = self.ctc.begin_turn("你好")
        self.ctc.claim_ready_turn()
        self.ctc.mark_streaming(t.turn_id)
        self.ctc.complete_turn(t.turn_id)
        self.assertEqual(self.ctc.turn(t.turn_id)["state"],
                         "COMPLETED")
        self.assertEqual(self.ctc.state()["active_state"], "IDLE")

    def test_interrupt(self):
        t = self.ctc.begin_turn("问题")
        self.ctc.claim_ready_turn()
        self.ctc.mark_streaming(t.turn_id)
        self.ctc.interrupt_turn(t.turn_id)
        d = self.ctc.turn(t.turn_id)
        self.assertEqual(d["state"], "INTERRUPTED")
        self.assertTrue(d["interrupted"])

    def test_interrupt_promotes_queue(self):
        t1 = self.ctc.begin_turn("A")
        self.ctc.claim_ready_turn()
        self.ctc.mark_streaming(t1.turn_id)
        t2 = self.ctc.begin_turn("B")
        self.assertEqual(t2.state, "QUEUED")
        self.ctc.interrupt_turn(t1.turn_id)
        self.assertEqual(self.ctc.state()["active_turn_id"],
                         t2.turn_id)
        self.assertEqual(self.ctc.turn(t2.turn_id)["state"],
                         "READY")

    def test_queue_ordered(self):
        t1 = self.ctc.begin_turn("A")
        self.ctc.claim_ready_turn()
        self.ctc.mark_streaming(t1.turn_id)
        t2 = self.ctc.begin_turn("B")
        t3 = self.ctc.begin_turn("C")
        self.assertEqual(t2.state, "QUEUED")
        self.assertEqual(t3.state, "QUEUED")
        self.assertEqual(list(self.ctc.state()["queue_ids"]),
                         [t2.turn_id, t3.turn_id])

    def test_queue_limit(self):
        ctc = ConversationTurnController(max_queue=2)
        a = ctc.begin_turn("A")
        ctc.claim_ready_turn()
        ctc.mark_streaming(a.turn_id)
        ctc.begin_turn("B")
        ctc.begin_turn("C")
        with self.assertRaises(ConversationControllerError):
            ctc.begin_turn("D")

    def test_error_state(self):
        t = self.ctc.begin_turn("A")
        self.ctc.claim_ready_turn()
        self.ctc.error_turn(t.turn_id, "测试错误")
        d = self.ctc.turn(t.turn_id)
        self.assertEqual(d["state"], "ERROR")
        self.assertEqual(d["error"], "测试错误")

    def test_disabled(self):
        ctc = ConversationTurnController(enabled=False)
        with self.assertRaises(ConversationControllerError):
            ctc.begin_turn("A")

    def test_invalid_event_type(self):
        t = self.ctc.begin_turn("A")
        with self.assertRaises(ConversationControllerError):
            self.ctc.stream_event(t.turn_id, "BAD_EVENT")

    def test_missing_turn(self):
        with self.assertRaises(ConversationControllerError):
            self.ctc.mark_streaming("nonexistent")


class TestEventProtocol(unittest.TestCase):
    """事件协议"""

    def setUp(self):
        self.ctc = ConversationTurnController()

    def _active_turn(self):
        t = self.ctc.begin_turn("你好")
        self.ctc.claim_ready_turn()
        self.ctc.mark_streaming(t.turn_id)
        return t

    def test_start_event(self):
        t = self._active_turn()
        e = self.ctc.stream_event(t.turn_id, "START")
        self.assertEqual(e["event_type"], "START")
        self.assertEqual(e["turn_id"], t.turn_id)
        self.assertEqual(e["sequence"], 1)

    def test_event_fields(self):
        t = self._active_turn()
        e = self.ctc.stream_event(t.turn_id, "TOKEN",
                                  {"content": "x"})
        for key in ("conversation_id", "turn_id", "timestamp",
                    "sequence", "event_type", "payload"):
            self.assertIn(key, e)

    def test_sequence_monotonic(self):
        t = self._active_turn()
        seqs = []
        for i in range(10):
            e = self.ctc.stream_event(t.turn_id, "TOKEN",
                                      {"content": str(i)})
            seqs.append(e["sequence"])
        self.assertEqual(seqs, list(range(1, 11)))

    def test_token_accumulates(self):
        t = self._active_turn()
        self.ctc.stream_event(t.turn_id, "TOKEN", {"content": "哎"})
        self.ctc.stream_event(t.turn_id, "TOKEN", {"content": "哟"})
        self.assertEqual(self.ctc.turn(t.turn_id)["response_text"],
                         "哎哟")

    def test_complete_event(self):
        t = self._active_turn()
        e = self.ctc.stream_event(t.turn_id, "COMPLETE",
                                  {"full_content": "完成"})
        self.assertEqual(e["event_type"], "COMPLETE")
        self.assertIn("stream_end", self.ctc.turn(
            t.turn_id)["latency"])

    def test_event_types_enum(self):
        self.assertEqual(EVENT_TYPES, [
            "START", "TOKEN", "FLUSH", "COMPLETE",
            "INTERRUPTED", "ERROR", "HEARTBEAT",
        ])


class TestStateMachine(unittest.TestCase):
    """状态机规则"""

    def test_states_enum(self):
        self.assertEqual(CONVERSATION_STATES, [
            "IDLE", "RECEIVING", "READY", "PROCESSING",
            "STREAMING", "TTS_PLAYING", "COMPLETED",
            "INTERRUPTED", "QUEUED", "RECOVERY", "ERROR",
        ])

    def test_transitions_defined(self):
        for state in CONVERSATION_STATES:
            self.assertIn(state, STATE_TRANSITIONS)

    def test_idle_to_receiving(self):
        self.assertIn("RECEIVING", STATE_TRANSITIONS["IDLE"])

    def test_streaming_to_completed(self):
        self.assertIn("COMPLETED", STATE_TRANSITIONS["STREAMING"])

    def test_streaming_to_interrupted(self):
        self.assertIn("INTERRUPTED",
                      STATE_TRANSITIONS["STREAMING"])

    def test_interrupted_to_ready(self):
        self.assertIn("READY", STATE_TRANSITIONS["INTERRUPTED"])

    def test_error_to_idle(self):
        self.assertIn("IDLE", STATE_TRANSITIONS["ERROR"])

    def test_turn_object(self):
        t = ConversationTurn("conv_1", "turn_1", "你好")
        self.assertEqual(t.state, "RECEIVING")
        self.assertEqual(t.source, "user")


class TestLatencyTracking(unittest.TestCase):
    """延迟追踪"""

    def setUp(self):
        self.ctc = ConversationTurnController()

    def test_latency_marks(self):
        t = self.ctc.begin_turn("你好")
        self.assertIn("input_start", t.latency)
        self.ctc.claim_ready_turn()
        self.ctc.mark_streaming(t.turn_id)
        self.assertIn("llm_start", t.latency)
        self.ctc.stream_event(t.turn_id, "TOKEN", {"content": "x"})
        self.ctc.stream_event(t.turn_id, "COMPLETE",
                              {"full_content": "完成"})
        self.ctc.complete_turn(t.turn_id)
        d = self.ctc.turn(t.turn_id)
        for key in ("input_start", "input_end", "turn_start",
                    "runtime_start", "llm_start", "stream_end",
                    "response_complete", "turn_close"):
            self.assertIn(key, d["latency"])

    def test_interrupt_latency(self):
        t = self.ctc.begin_turn("A")
        self.ctc.claim_ready_turn()
        self.ctc.mark_streaming(t.turn_id)
        self.ctc.interrupt_turn(t.turn_id)
        self.assertIn("interrupt_time",
                      self.ctc.turn(t.turn_id)["latency"])

    def test_latency_summary(self):
        for i in range(5):
            t = self.ctc.begin_turn(f"t{i}")
            self.ctc.claim_ready_turn()
            self.ctc.mark_streaming(t.turn_id)
            self.ctc.stream_event(t.turn_id, "TOKEN",
                                  {"content": "x"})
            self.ctc.complete_turn(t.turn_id)
        s = self.ctc.latency_summary()
        self.assertEqual(s["completed"], 5)
        self.assertEqual(s["errors"], 0)

    def test_clear(self):
        self.ctc.begin_turn("A")
        n = self.ctc.clear()
        self.assertGreaterEqual(n, 1)
        self.assertEqual(self.ctc.state()["turn_count"], 0)


if __name__ == "__main__":
    unittest.main()
