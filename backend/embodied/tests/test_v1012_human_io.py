"""
YHLZ Human Interaction & Multimodal Layer V10.1.2 测试

覆盖:
    - 人类协作者层 (记录类型/每日反馈/价值判断/持久化)
    - 多模态经验层 (输入类型/评分/分类/记忆决策/弹幕过滤)
"""
import json
import os
import tempfile
import unittest

from backend.human_io import (
    CLASSIFICATIONS,
    HUMAN_RECORD_TYPES,
    HumanLayerError,
    HumanOperatorLayer,
    INPUT_TYPES,
    MultimodalError,
    MultimodalExperienceLayer,
    SCORE_DISCARD_MAX,
    SCORE_LONG_MIN,
    SCORE_SHORT_MIN,
)


class TestHumanOperatorLayer(unittest.TestCase):
    """人类协作者层"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.layer = HumanOperatorLayer(
            save_dir=self._tmp.name,
        )

    def tearDown(self):
        self._tmp.cleanup()

    def test_record_task(self):
        r = self.layer.record("task", "完成热机验收", user="老万")
        self.assertTrue(r["ok"])
        self.assertEqual(r["type"], "task")
        self.assertEqual(r["user"], "老万")

    def test_record_all_types(self):
        for t in HUMAN_RECORD_TYPES:
            r = self.layer.record(t, f"内容{t}")
            self.assertTrue(r["ok"])
            self.assertEqual(r["type"], t)

    def test_invalid_type(self):
        with self.assertRaises(HumanLayerError):
            self.layer.record("bad", "内容")

    def test_empty_content(self):
        with self.assertRaises(HumanLayerError):
            self.layer.record("task", "  ")

    def test_value_assess(self):
        r = self.layer.record("task", "发现方案问题并给建议")
        self.assertGreaterEqual(r["value_score"], 4)

    def test_query(self):
        self.layer.record("task", "任务A")
        self.layer.record("feedback", "反馈B")
        self.assertEqual(len(self.layer.query()), 2)

    def test_query_by_type(self):
        self.layer.record("task", "任务A")
        self.layer.record("idea", "想法B")
        hits = self.layer.query(record_type="task")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["type"], "task")

    def test_daily_feedback(self):
        r = self.layer.daily_feedback(
            date="2026-08-09", task="热机", experience="稳定",
            problem="无", suggestion="继续",
        )
        self.assertTrue(r["ok"])
        path = os.path.join(self._tmp.name,
                            "feedback_2026-08-09.json")
        self.assertTrue(os.path.exists(path))
        with open(path, "r", encoding="utf-8") as f:
            entries = json.load(f)
        self.assertEqual(entries[0]["task"], "热机")

    def test_daily_feedback_append(self):
        self.layer.daily_feedback(date="2026-08-09", task="A")
        self.layer.daily_feedback(date="2026-08-09", task="B")
        path = os.path.join(self._tmp.name,
                            "feedback_2026-08-09.json")
        with open(path, "r", encoding="utf-8") as f:
            entries = json.load(f)
        self.assertEqual(len(entries), 2)

    def test_stats(self):
        self.layer.record("task", "A")
        self.layer.record("feedback", "B")
        s = self.layer.stats()
        self.assertEqual(s["total"], 2)
        self.assertEqual(s["by_type"]["task"], 1)

    def test_clear(self):
        self.layer.record("task", "A")
        self.assertEqual(self.layer.clear(), 1)
        self.assertEqual(self.layer.stats()["total"], 0)

    def test_disabled(self):
        layer = HumanOperatorLayer(enabled=False)
        r = layer.record("task", "A")
        self.assertEqual(r["mode"], "error_frame")

    def test_invalid_max(self):
        with self.assertRaises(HumanLayerError):
            HumanOperatorLayer(max_records=0)

    def test_save_dir_created(self):
        with tempfile.TemporaryDirectory() as td:
            sub = os.path.join(td, "human_feedback")
            HumanOperatorLayer(save_dir=sub)
            self.assertTrue(os.path.isdir(sub))


class TestMultimodalLayer(unittest.TestCase):
    """多模态经验层"""

    def setUp(self):
        self.layer = MultimodalExperienceLayer()

    def test_input_types(self):
        self.assertEqual(INPUT_TYPES, [
            "camera", "screen", "audio", "video", "stream",
            "danmaku",
        ])

    def test_process_high_value(self):
        r = self.layer.process(
            "screen", "完成项目部署方案设计", context="热机",
        )
        self.assertTrue(r["ok"])
        self.assertEqual(r["classification"], "high_value")
        self.assertEqual(r["memory_decision"],
                         "long_term_candidate")

    def test_process_temporary(self):
        r = self.layer.process("screen", "查看当前任务反馈")
        self.assertEqual(r["classification"], "temporary")
        self.assertEqual(r["memory_decision"], "short_term")

    def test_process_noise(self):
        r = self.layer.process("screen", "随便看看")
        self.assertEqual(r["classification"], "noise")
        self.assertEqual(r["memory_decision"], "discard")

    def test_danmaku_noise(self):
        for content in ("666", "哈哈", "hhh", "233", "路过"):
            r = self.layer.process("danmaku", content)
            self.assertEqual(r["classification"], "noise", content)

    def test_danmaku_short_digits(self):
        r = self.layer.process("danmaku", "123")
        self.assertEqual(r["classification"], "noise")

    def test_danmaku_opinion(self):
        r = self.layer.process(
            "danmaku", "我认为这个方案应该调整",
        )
        self.assertEqual(r["classification"], "temporary")

    def test_importance_score_range(self):
        r = self.layer.process("camera", "完成重要任务方案")
        self.assertGreaterEqual(r["importance_score"], 0)
        self.assertLessEqual(r["importance_score"], 10)

    def test_reason_explainable(self):
        r = self.layer.process("screen", "随便看看")
        self.assertIn("丢弃", r["reason"])
        r2 = self.layer.process("screen", "完成项目部署方案设计")
        self.assertIn("长期候选", r2["reason"])

    def test_invalid_input_type(self):
        with self.assertRaises(MultimodalError):
            self.layer.process("bad", "内容")

    def test_noise_not_recorded(self):
        self.layer.process("danmaku", "666")
        self.layer.process("screen", "完成项目部署方案设计")
        self.assertEqual(self.layer.stats()["total_kept"], 1)
        self.assertEqual(self.layer.stats()["discard_count"], 1)

    def test_query_by_classification(self):
        self.layer.process("screen", "完成项目部署方案设计")
        self.layer.process("danmaku", "我认为可以")
        hits = self.layer.query(classification="high_value")
        self.assertEqual(len(hits), 1)

    def test_stats_structure(self):
        self.layer.process("screen", "完成项目部署方案设计")
        s = self.layer.stats()
        for key in ("total_kept", "discard_count", "by_type",
                    "by_classification"):
            self.assertIn(key, s)

    def test_score_constants(self):
        self.assertEqual(SCORE_DISCARD_MAX, 4)
        self.assertEqual(SCORE_SHORT_MIN, 5)
        self.assertEqual(SCORE_LONG_MIN, 8)
        self.assertEqual(CLASSIFICATIONS,
                         ["high_value", "temporary", "noise"])

    def test_clear(self):
        self.layer.process("screen", "完成项目部署方案设计")
        self.layer.process("danmaku", "666")
        self.assertEqual(self.layer.clear(), 2)
        self.assertEqual(self.layer.stats()["total_kept"], 0)

    def test_disabled(self):
        layer = MultimodalExperienceLayer(enabled=False)
        r = layer.process("screen", "内容")
        self.assertEqual(r["mode"], "error_frame")

    def test_invalid_max(self):
        with self.assertRaises(MultimodalError):
            MultimodalExperienceLayer(max_records=0)


if __name__ == "__main__":
    unittest.main()
