"""Tests for the bounded LLM-delta -> spoken-text segmentation boundary."""
import unittest

from backend.voice_streaming import SpokenDeltaFilter, StreamingTextChunker, TextChunkerConfig


class VoiceStreamingTest(unittest.TestCase):
    def test_first_punctuation_flush_is_bounded(self):
        c = StreamingTextChunker()
        out = []
        for delta in ("你好，", "我是元亨。", "第二句继续。"):
            out.extend(c.push(delta))
        out.extend(c.finish())
        self.assertTrue(out)
        self.assertEqual("".join(out), "你好，我是元亨。第二句继续。")
        self.assertLessEqual(len(out[0]), 20)

    def test_hard_limit_flushes_without_punctuation(self):
        c = StreamingTextChunker()
        out = c.push("甲" * 70)
        out.extend(c.finish())
        self.assertGreaterEqual(len(out), 2)
        self.assertLessEqual(len(out[0]), 20)

    def test_first_idle_deadline_without_new_delta(self):
        now = [0.0]
        c = StreamingTextChunker(clock=lambda: now[0])
        self.assertEqual(c.push("甲" * 10), [])
        now[0] = .349
        self.assertEqual(c.tick(), [])
        now[0] = .350
        self.assertEqual(c.tick(), ["甲" * 10])

    def test_hard_deadline_flushes_short_first_fragment(self):
        now = [0.0]
        c = StreamingTextChunker(clock=lambda: now[0])
        c.push("好")
        now[0] = .350
        self.assertEqual(c.tick(), [])
        now[0] = .600
        self.assertEqual(c.tick(), ["好"])

    def test_continuous_deltas_cannot_reset_hard_deadline(self):
        now = [0.0]
        c = StreamingTextChunker(clock=lambda: now[0])
        c.push("甲")
        for i in range(1, 6):
            now[0] = i / 10
            self.assertEqual(c.push("甲"), [])
        now[0] = .600
        self.assertEqual(c.tick(), ["甲" * 6])

    def test_idle_flush_happens_before_next_delta_resets_clock(self):
        now = [0.0]
        c = StreamingTextChunker(clock=lambda: now[0])
        c.push("甲" * 10)
        now[0] = .4
        self.assertEqual(c.push("乙"), ["甲" * 10])
        self.assertEqual(c.finish(), ["乙"])

    def test_normal_bound_and_finish_preserve_text(self):
        for length in (1, 7, 19, 20, 21, 45, 60, 200, 4096):
            with self.subTest(length=length):
                c = StreamingTextChunker()
                out = c.push("甲" * length) + c.finish()
                self.assertEqual("".join(out), "甲" * length)
                self.assertLessEqual(len(out[0]), 20)
                self.assertTrue(all(len(s) <= 45 for s in out[1:]))
                self.assertEqual(c.finish(), [])
                self.assertEqual(c.push("迟到"), [])

    def test_cancel_never_flushes_late_data(self):
        c = StreamingTextChunker()
        c.push("还没够")
        c.cancel()
        self.assertEqual(c.buffered, "")
        self.assertEqual(c.finish() + c.tick() + c.push("迟到"), [])

    def test_invalid_limits_fail_fast(self):
        with self.assertRaises(ValueError):
            TextChunkerConfig(normal_max_chars=100)

    def test_short_normal_delta_is_immediate(self):
        got = []
        f = SpokenDeltaFilter(got.append)
        f.push("你好呀")
        self.assertEqual(got, ["你好呀"])

    def test_native_and_dev_marker_at_every_split(self):
        for marker in ("<think>", "<|tool_call>", "[[dev:", "<analysis>"):
            for n in range(1, len(marker)):
                got = []
                f = SpokenDeltaFilter(got.append)
                f.push("安全内容" + marker[:n])
                f.push(marker[n:] + "隐藏内容")
                f.push("甲" * 10000)
                f.finish()
                self.assertEqual("".join(got), "安全内容")
                self.assertEqual(f._buffer, "")

    def test_incomplete_marker_and_cancel_are_not_flushed(self):
        got = []
        f = SpokenDeltaFilter(got.append)
        f.push("可见<th")
        f.finish()
        f.push("迟到")
        self.assertEqual("".join(got), "可见")

    def test_marker_split_across_deltas_is_not_emitted(self):
        got = []
        f = SpokenDeltaFilter(got.append)
        f.push("正常回答（思")
        f.push("考模式启动：不要读出来")
        f.finish()
        self.assertEqual("正常回答", "".join(got).strip())


if __name__ == "__main__":
    unittest.main()
