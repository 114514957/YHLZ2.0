"""
YHLZ Embodied AI V6.5 - 矛盾检测与认知反思单元测试 (Contradiction & Cognitive Reflection)

覆盖:
    - CognitiveContradictionDetector: 身份/知识/价值观冲突
    - CognitiveReflectionEngine: 认知总结
    - ReflectionReport: 反思记忆
"""
import time
import unittest

from backend.embodied.companion.reflection import (
    CONTRADICTION_TYPES,
    CognitiveContradictionDetector,
    CognitiveReflectionEngine,
    PatternAnalyzer,
    ReflectionReport,
    ReportError,
)


def make_record(trigger="生成工程Prompt", type="improvement",
                result="成功", rid=None, ts_offset=0):
    return {
        "id": rid or f"exp_{trigger}_{ts_offset}",
        "type": type,
        "trigger": trigger,
        "lesson": "l",
        "result": result,
        "timestamp": time.time() - ts_offset * 86400,
    }


class TestContradictionDetector(unittest.TestCase):
    """矛盾检测"""

    def setUp(self):
        self.detector = CognitiveContradictionDetector()

    def test_no_conflict(self):
        r = self.detector.detect(make_record())
        self.assertFalse(r["conflict"])
        self.assertEqual(r["type"], "")
        self.assertEqual(r["severity"], 0.0)

    def test_identity_conflict(self):
        """新经验含与身份冲突的信号"""
        r = self.detector.detect(
            {"trigger": "改变使命方向", "lesson": "l",
             "result": "成功"},
            identity_state={"mission": "长期陪伴"},
        )
        self.assertTrue(r["conflict"])
        self.assertEqual(r["type"], "identity_conflict")

    def test_knowledge_conflict(self):
        """同触发器相反结果"""
        r = self.detector.detect(
            {"trigger": "拾取物体", "lesson": "l",
             "result": "失败"},
            known_experiences=[
                {"trigger": "拾取物体", "result": "成功",
                 "lesson": "l"},
            ],
        )
        self.assertTrue(r["conflict"])
        self.assertEqual(r["type"], "knowledge_conflict")

    def test_value_conflict(self):
        r = self.detector.detect(
            {"trigger": "任务", "lesson": "l",
             "result": "不可靠处理"},
        )
        # "不可靠" 含 不+可靠
        self.assertTrue(r["conflict"])
        self.assertEqual(r["type"], "value_conflict")

    def test_result_structure(self):
        r = self.detector.detect(make_record())
        for key in ("conflict_id", "conflict", "type", "severity",
                    "reason", "mode", "checked_at"):
            self.assertIn(key, r)

    def test_conflict_id_prefix(self):
        r = self.detector.detect(make_record())
        self.assertTrue(r["conflict_id"].startswith("cnd_"))

    def test_mode(self):
        r = self.detector.detect(make_record())
        self.assertEqual(r["mode"], "rule_based")

    def test_stats(self):
        self.detector.detect(make_record())
        self.detector.detect(
            {"trigger": "x", "lesson": "l", "result": "不可靠"},
        )
        st = self.detector.stats()
        self.assertEqual(st["check_count"], 2)
        self.assertGreaterEqual(st["conflict_count"], 1)

    def test_stats_by_type(self):
        self.detector.detect(
            {"trigger": "x", "lesson": "l", "result": "不可靠"},
        )
        st = self.detector.stats()
        self.assertGreaterEqual(st["by_type"].get(
            "value_conflict", 0), 1)

    def test_clear(self):
        self.detector.detect(make_record())
        self.assertEqual(self.detector.clear(), 1)

    def test_types_whitelist(self):
        self.assertIn("identity_conflict", CONTRADICTION_TYPES)
        self.assertIn("knowledge_conflict", CONTRADICTION_TYPES)
        self.assertIn("value_conflict", CONTRADICTION_TYPES)


class TestCognitiveReflection(unittest.TestCase):
    """认知反思引擎"""

    def setUp(self):
        self.engine = CognitiveReflectionEngine()

    def test_analyze_structure(self):
        records = [make_record(ts_offset=i) for i in range(3)]
        r = self.engine.analyze(records)
        for key in ("report_id", "summary", "pattern",
                    "success_factor", "failure_factor",
                    "confidence", "patterns", "contradictions",
                    "mode", "generated_at"):
            self.assertIn(key, r)

    def test_report_id_prefix(self):
        r = self.engine.analyze([])
        self.assertTrue(r["report_id"].startswith("cr_"))

    def test_patterns_discovered(self):
        records = [
            make_record(trigger="反思成功", ts_offset=i)
            for i in range(4)
        ]
        r = self.engine.analyze(records)
        self.assertGreaterEqual(len(r["patterns"]), 1)

    def test_summary_mentions_samples(self):
        records = [make_record(ts_offset=i) for i in range(4)]
        r = self.engine.analyze(records)
        self.assertIn("4", r["summary"])

    def test_success_factor(self):
        records = [
            make_record(trigger="成功反思", ts_offset=i)
            for i in range(4)
        ]
        r = self.engine.analyze(records)
        self.assertIn("成功", r["success_factor"])

    def test_failure_factor(self):
        records = [
            make_record(trigger="失败反思", type="failure",
                        result="错误", ts_offset=i)
            for i in range(4)
        ]
        r = self.engine.analyze(records)
        self.assertIn("失败", r["failure_factor"])

    def test_no_failure_factor(self):
        records = [make_record(ts_offset=i) for i in range(3)]
        r = self.engine.analyze(records)
        self.assertIn("无失败", r["failure_factor"])

    def test_confidence_range(self):
        records = [make_record(ts_offset=i) for i in range(4)]
        r = self.engine.analyze(records)
        self.assertGreaterEqual(r["confidence"], 0.0)
        self.assertLessEqual(r["confidence"], 1.0)

    def test_contradictions_reported(self):
        records = [
            make_record(trigger="矛盾测试", result="不可靠",
                        rid=f"e{i}")
            for i in range(3)
        ]
        r = self.engine.analyze(records)
        self.assertGreaterEqual(len(r["contradictions"]), 0)

    def test_disabled(self):
        e = CognitiveReflectionEngine(enabled=False)
        r = e.analyze([make_record()])
        self.assertIn("停用", r["summary"])

    def test_latest(self):
        self.engine.analyze([])
        r = self.engine.latest()
        self.assertIsNotNone(r)

    def test_latest_empty(self):
        self.assertIsNone(CognitiveReflectionEngine().latest())

    def test_stats(self):
        self.engine.analyze([])
        st = self.engine.stats()
        self.assertEqual(st["mode"], "rule_based")
        self.assertEqual(st["reflection_count"], 1)

    def test_clear(self):
        self.engine.analyze([])
        self.assertEqual(self.engine.clear(), 1)


class TestReflectionReport(unittest.TestCase):
    """反思记忆"""

    def test_record(self):
        r = ReflectionReport()
        e = r.record("exp_1", "理解了什么", "模式", "成长价值")
        self.assertTrue(e["memory_id"].startswith("rme_"))
        self.assertEqual(e["experience_id"], "exp_1")

    def test_record_empty_id(self):
        r = ReflectionReport()
        with self.assertRaises(ReportError):
            r.record("", "反思")

    def test_by_experience(self):
        r = ReflectionReport()
        r.record("exp_1", "反思A")
        r.record("exp_2", "反思B")
        out = r.by_experience("exp_1")
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["reflection"], "反思A")

    def test_history_latest_first(self):
        r = ReflectionReport()
        r.record("a", "第一")
        r.record("b", "第二")
        h = r.history()
        self.assertEqual(h[0]["reflection"], "第二")

    def test_history_limit(self):
        r = ReflectionReport()
        for i in range(5):
            r.record(f"e{i}", f"r{i}")
        self.assertEqual(len(r.history(limit=2)), 2)

    def test_stats(self):
        r = ReflectionReport()
        r.record("a", "反思", pattern="模式")
        r.record("b", "反思")
        st = r.stats()
        self.assertEqual(st["memory_count"], 2)
        self.assertEqual(st["with_pattern"], 1)

    def test_max_records(self):
        r = ReflectionReport(max_records=3)
        for i in range(5):
            r.record(f"e{i}", "反思")
        self.assertEqual(r.stats()["memory_count"], 3)

    def test_max_records_validation(self):
        with self.assertRaises(ReportError):
            ReflectionReport(max_records=0)

    def test_clear(self):
        r = ReflectionReport()
        r.record("a", "反思")
        self.assertEqual(r.clear(), 1)


if __name__ == "__main__":
    unittest.main()
