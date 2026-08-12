"""
YHLZ Embodied AI V5.9 - 机会检测器单元测试 (Opportunity Detector)

覆盖 (opportunity_detector.py):
    - 5 类机会检测: repetition / failure / pattern / improvement / relationship
    - 只基于 CONFIRMED 经验 (输入即过滤后)
    - 置信度规则 / 证据 / 结构
    - 去重 / 上限 / 查询 / 统计
    - 异常处理
"""
import time
import unittest

from backend.embodied.companion.creative import (
    OPPORTUNITY_SOURCE_TYPES,
    OpportunityDetector,
    OpportunityError,
)


def make_record(trigger="生成工程Prompt", type="improvement",
                result="成功", value=0.8, rid=None, ts_offset=0):
    """构造经历 dict"""
    return {
        "id": rid or f"exp_{trigger}_{ts_offset}",
        "type": type,
        "trigger": trigger,
        "lesson": f"{trigger}经验",
        "result": result,
        "action": "scan",
        "value": value,
        "timestamp": time.time() - ts_offset * 86400,
    }


class TestDetectorInit(unittest.TestCase):
    """初始化与参数校验"""

    def test_default_init(self):
        d = OpportunityDetector()
        self.assertIsNotNone(d)

    def test_min_evidence_validation(self):
        with self.assertRaises(OpportunityError):
            OpportunityDetector(min_evidence=0)

    def test_repetition_min_validation(self):
        with self.assertRaises(OpportunityError):
            OpportunityDetector(repetition_min_occurrences=1)

    def test_failure_min_validation(self):
        with self.assertRaises(OpportunityError):
            OpportunityDetector(failure_min_occurrences=0)

    def test_trust_validation_high(self):
        with self.assertRaises(OpportunityError):
            OpportunityDetector(relationship_trust_min=1.5)

    def test_trust_validation_low(self):
        with self.assertRaises(OpportunityError):
            OpportunityDetector(relationship_trust_min=-0.1)

    def test_source_types_whitelist(self):
        self.assertIn("repetition", OPPORTUNITY_SOURCE_TYPES)
        self.assertIn("failure", OPPORTUNITY_SOURCE_TYPES)
        self.assertIn("pattern", OPPORTUNITY_SOURCE_TYPES)
        self.assertIn("improvement", OPPORTUNITY_SOURCE_TYPES)
        self.assertIn("relationship", OPPORTUNITY_SOURCE_TYPES)

    def test_source_types_count(self):
        self.assertEqual(len(OPPORTUNITY_SOURCE_TYPES), 5)

    def test_empty_detect(self):
        d = OpportunityDetector()
        out = d.detect([])
        self.assertEqual(out, [])

    def test_clear_returns_count(self):
        d = OpportunityDetector()
        self.assertEqual(d.clear(), 0)


class TestRepetitionDetection(unittest.TestCase):
    """重复需求 → 自动化机会"""

    def setUp(self):
        self.detector = OpportunityDetector(repetition_min_occurrences=3)

    def test_repetition_detected(self):
        recs = [
            make_record(trigger="生成工程Prompt", rid=f"e{i}", ts_offset=i)
            for i in range(3)
        ]
        out = self.detector.detect(recs)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["source_type"], "repetition")

    def test_repetition_structure(self):
        recs = [
            make_record(trigger="重复需求", rid=f"e{i}", ts_offset=i)
            for i in range(3)
        ]
        out = self.detector.detect(recs)
        opp = out[0]
        for key in ("opportunity_id", "problem", "current_state",
                    "desired_state", "gap", "source_type", "trigger",
                    "evidence", "confidence", "created_at"):
            self.assertIn(key, opp)

    def test_repetition_evidence(self):
        recs = [
            make_record(trigger="重复需求", rid=f"e{i}", ts_offset=i)
            for i in range(3)
        ]
        out = self.detector.detect(recs)
        self.assertGreaterEqual(len(out[0]["evidence"]), 2)
        self.assertTrue(out[0]["opportunity_id"].startswith("opp_"))

    def test_repetition_not_enough(self):
        recs = [make_record(trigger="单次需求", rid="e0")]
        out = self.detector.detect(recs)
        self.assertEqual(out, [])

    def test_repetition_exactly_min(self):
        recs = [
            make_record(trigger="临界需求", rid=f"e{i}", ts_offset=i)
            for i in range(3)
        ]
        out = self.detector.detect(recs)
        self.assertEqual(len(out), 1)

    def test_repetition_confidence_range(self):
        recs = [
            make_record(trigger="高频需求", rid=f"e{i}", ts_offset=i)
            for i in range(5)
        ]
        out = self.detector.detect(recs)
        self.assertGreaterEqual(out[0]["confidence"], 0.0)
        self.assertLessEqual(out[0]["confidence"], 1.0)

    def test_repetition_confidence_grows_with_evidence(self):
        recs = [
            make_record(trigger="增长需求", rid=f"e{i}", ts_offset=i)
            for i in range(3)
        ]
        low = self.detector.detect(recs)[0]["confidence"]
        recs2 = [
            make_record(trigger="增长需求", rid=f"e{i}", ts_offset=i)
            for i in range(6)
        ]
        d2 = OpportunityDetector(repetition_min_occurrences=3)
        high = d2.detect(recs2)[0]["confidence"]
        self.assertGreaterEqual(high, low)

    def test_repetition_problem_text(self):
        recs = [
            make_record(trigger="测试需求", rid=f"e{i}", ts_offset=i)
            for i in range(3)
        ]
        out = self.detector.detect(recs)
        self.assertIn("测试需求", out[0]["problem"])

    def test_repetition_gap_automation(self):
        recs = [
            make_record(trigger="测试需求", rid=f"e{i}", ts_offset=i)
            for i in range(3)
        ]
        out = self.detector.detect(recs)
        self.assertIn("自动", out[0]["gap"])

    def test_two_trigger_groups(self):
        recs = []
        for t in ("需求A", "需求B"):
            recs += [
                make_record(trigger=t, rid=f"{t}{i}", ts_offset=i)
                for i in range(3)
            ]
        out = self.detector.detect(recs)
        self.assertEqual(len(out), 2)

    def test_mixed_trigger_no_pollution(self):
        recs = [
            make_record(trigger="重复项", rid=f"e{i}", ts_offset=i)
            for i in range(3)
        ] + [make_record(trigger="单次项", rid="e9")]
        out = self.detector.detect(recs)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["trigger"], "重复项")


class TestFailureDetection(unittest.TestCase):
    """反复失败 → 新方案机会"""

    def setUp(self):
        self.detector = OpportunityDetector(failure_min_occurrences=2)

    def test_failure_detected(self):
        recs = [
            make_record(trigger="拾取失败", type="failure",
                        result="位置不匹配", rid=f"f{i}", ts_offset=i)
            for i in range(2)
        ]
        out = self.detector.detect(recs)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["source_type"], "failure")

    def test_failure_not_enough(self):
        recs = [make_record(trigger="单次失败", type="failure",
                            result="错误", rid="f0")]
        out = self.detector.detect(recs)
        self.assertEqual(out, [])

    def test_failure_ignores_success(self):
        recs = [
            make_record(trigger="混合项", type="failure",
                        result="错误", rid=f"f{i}", ts_offset=i)
            for i in range(2)
        ] + [make_record(trigger="混合项", rid="s0")]
        out = self.detector.detect(recs)
        types = [c["source_type"] for c in out]
        self.assertIn("failure", types)
        self.assertTrue(all(c["source_type"] == "failure" or
                            c["source_type"] == "repetition"
                            for c in out))

    def test_failure_confidence(self):
        recs = [
            make_record(trigger="失败项", type="failure",
                        result="错误", rid=f"f{i}", ts_offset=i)
            for i in range(3)
        ]
        out = self.detector.detect(recs)
        self.assertGreater(out[0]["confidence"], 0.0)

    def test_failure_desired_state(self):
        recs = [
            make_record(trigger="失败项", type="failure",
                        result="错误", rid=f"f{i}", ts_offset=i)
            for i in range(2)
        ]
        out = self.detector.detect(recs)
        self.assertIn("新方案", out[0]["desired_state"])


class TestPatternDetection(unittest.TestCase):
    """有效模式 → 固化机会"""

    def test_pattern_detected(self):
        d = OpportunityDetector()
        report = {
            "patterns": [
                {"trigger": "扫描行为", "occurrences": 5,
                 "lesson": "固定路径可复用"},
            ],
            "suggestion": "建议固化扫描行为",
        }
        out = d.detect([], report)
        types = [c["source_type"] for c in out]
        self.assertIn("pattern", types)

    def test_pattern_trigger(self):
        d = OpportunityDetector()
        report = {
            "patterns": [
                {"trigger": "模式项", "occurrences": 4, "lesson": "l"},
            ],
        }
        out = d.detect([], report)
        self.assertEqual(out[0]["trigger"], "模式项")

    def test_no_report_no_pattern(self):
        d = OpportunityDetector()
        out = d.detect([], None)
        self.assertNotIn(
            "pattern", [c["source_type"] for c in out],
        )

    def test_empty_report(self):
        d = OpportunityDetector()
        out = d.detect([], {"patterns": [], "suggestion": ""})
        self.assertEqual(out, [])

    def test_pattern_limit_five(self):
        d = OpportunityDetector()
        report = {
            "patterns": [
                {"trigger": f"模式{i}", "occurrences": 3, "lesson": "l"}
                for i in range(10)
            ],
        }
        out = d.detect([], report)
        self.assertLessEqual(len(out), 5)


class TestImprovementDetection(unittest.TestCase):
    """反思建议 → 升级机会"""

    def test_improvement_detected(self):
        d = OpportunityDetector()
        report = {
            "suggestion": "基于模式 '高频失败': 建议调整策略",
        }
        out = d.detect([], report)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["source_type"], "improvement")

    def test_improvement_ignores_no_suggestion(self):
        d = OpportunityDetector()
        out = d.detect([], {"suggestion": "暂无改进建议, 保持当前策略"})
        self.assertEqual(out, [])

    def test_improvement_trigger_prefix(self):
        d = OpportunityDetector()
        report = {"suggestion": "针对失败类问题调整执行策略"}
        out = d.detect([], report)
        self.assertEqual(out[0]["trigger"], "针对失败类问题调整执行策略")

    def test_improvement_problem_is_suggestion(self):
        d = OpportunityDetector()
        report = {"suggestion": "建议补充环境信息"}
        out = d.detect([], report)
        self.assertIn("建议补充环境信息", out[0]["problem"])


class TestRelationshipDetection(unittest.TestCase):
    """关系偏好 → 个性化机会"""

    def setUp(self):
        self.detector = OpportunityDetector(relationship_trust_min=0.7)

    def test_relationship_detected(self):
        recs = [
            make_record(trigger="常用功能", rid=f"r{i}", ts_offset=i)
            for i in range(3)
        ]
        rel = {"trust": 0.9}
        out = self.detector.detect(recs, None, rel)
        types = [c["source_type"] for c in out]
        self.assertIn("relationship", types)

    def test_relationship_low_trust(self):
        recs = [make_record(trigger="常用功能", rid="r0")]
        rel = {"trust": 0.3}
        out = self.detector.detect(recs, None, rel)
        self.assertEqual(out, [])

    def test_relationship_no_context(self):
        recs = [make_record(trigger="常用功能", rid="r0")]
        out = self.detector.detect(recs, None, None)
        self.assertEqual(out, [])

    def test_relationship_requires_success(self):
        recs = [make_record(trigger="常用功能", type="failure",
                            result="错误", rid="r0")]
        rel = {"trust": 0.9}
        out = self.detector.detect(recs, None, rel)
        self.assertEqual(out, [])

    def test_relationship_trust_stored(self):
        recs = [
            make_record(trigger="常用功能", rid=f"r{i}", ts_offset=i)
            for i in range(2)
        ]
        rel = {"trust": 0.95}
        out = self.detector.detect(recs, None, rel)
        self.assertEqual(out[0]["trust"], 0.95)

    def test_relationship_gap_personalization(self):
        recs = [
            make_record(trigger="常用功能", rid=f"r{i}", ts_offset=i)
            for i in range(2)
        ]
        rel = {"trust": 0.8}
        out = self.detector.detect(recs, None, rel)
        self.assertIn("个性化", out[0]["desired_state"])


class TestConfidenceRules(unittest.TestCase):
    """置信度规则 (可解释)"""

    def test_base_confidence(self):
        recs = [
            make_record(trigger="置信项", rid=f"e{i}", ts_offset=i)
            for i in range(3)
        ]
        d = OpportunityDetector()
        out = d.detect(recs)
        self.assertGreaterEqual(out[0]["confidence"], 0.3)

    def test_confidence_high_value_bonus(self):
        recs = [
            make_record(trigger="高价值项", value=0.8, rid=f"e{i}",
                        ts_offset=i)
            for i in range(4)
        ]
        d = OpportunityDetector()
        out = d.detect(recs)
        self.assertGreaterEqual(out[0]["confidence"], 0.4)

    def test_confidence_cap(self):
        recs = [
            make_record(trigger="超高价值", value=0.9, rid=f"e{i}",
                        ts_offset=i)
            for i in range(30)
        ]
        d = OpportunityDetector()
        out = d.detect(recs)
        self.assertLessEqual(out[0]["confidence"], 0.95)

    def test_confidence_rule_explainable(self):
        """置信度在 [0.3, 0.95] 区间"""
        recs = [
            make_record(trigger="区间项", rid=f"e{i}", ts_offset=i)
            for i in range(8)
        ]
        d = OpportunityDetector()
        out = d.detect(recs)
        c = out[0]["confidence"]
        self.assertTrue(0.3 <= c <= 0.95)


class TestDedupAndLimit(unittest.TestCase):
    """去重与上限"""

    def test_dedup_same_trigger_type(self):
        d = OpportunityDetector()
        recs = [
            make_record(trigger="去重项", rid=f"e{i}", ts_offset=i)
            for i in range(3)
        ]
        d.detect(recs)
        d.detect(recs)
        self.assertEqual(d.stats()["opportunity_count"], 1)

    def test_dedup_different_type_kept(self):
        d = OpportunityDetector()
        recs = [
            make_record(trigger="同项", rid=f"e{i}", ts_offset=i)
            for i in range(3)
        ]
        d.detect(recs, {"suggestion": "建议改进同项"})
        # repetition + improvement 同 trigger 但类型不同 → 保留
        self.assertEqual(d.stats()["opportunity_count"], 2)

    def test_max_opportunities(self):
        d = OpportunityDetector(max_opportunities=1)
        recs = []
        for t in ("需求A", "需求B", "需求C"):
            recs += [
                make_record(trigger=t, rid=f"{t}{i}", ts_offset=i)
                for i in range(3)
            ]
        out = d.detect(recs)
        self.assertLessEqual(len(out), 1)

    def test_sorted_by_confidence(self):
        d = OpportunityDetector()
        recs = []
        for t in ("需求A", "需求B"):
            recs += [
                make_record(trigger=t, rid=f"{t}{i}",
                            value=0.5 + 0.1 * i, ts_offset=i)
                for i in range(3)
            ]
        recs += [
            make_record(trigger="需求C", rid=f"C{i}", ts_offset=i)
            for i in range(6)
        ]
        out = d.detect(recs)
        confs = [c["confidence"] for c in out]
        self.assertEqual(confs, sorted(confs, reverse=True))


class TestQueryAndStats(unittest.TestCase):
    """查询与统计"""

    def setUp(self):
        self.detector = OpportunityDetector()
        recs = [
            make_record(trigger="查询项", rid=f"e{i}", ts_offset=i)
            for i in range(3)
        ]
        self.opp = self.detector.detect(recs)[0]

    def test_get_by_id(self):
        opp = self.detector.get(self.opp["opportunity_id"])
        self.assertEqual(opp["trigger"], "查询项")

    def test_get_missing(self):
        self.assertIsNone(self.detector.get("opp_nonexist"))

    def test_by_source_type(self):
        out = self.detector.by_source_type("repetition")
        self.assertEqual(len(out), 1)

    def test_by_source_type_invalid(self):
        with self.assertRaises(OpportunityError):
            self.detector.by_source_type("invalid_type")

    def test_stats_structure(self):
        st = self.detector.stats()
        for key in ("mode", "opportunity_count", "by_source_type",
                    "avg_confidence"):
            self.assertIn(key, st)
        self.assertEqual(st["mode"], "rule_based")

    def test_stats_counts(self):
        st = self.detector.stats()
        self.assertEqual(st["opportunity_count"], 1)

    def test_clear(self):
        self.detector.clear()
        self.assertEqual(self.detector.stats()["opportunity_count"], 0)

    def test_get_after_clear(self):
        self.detector.clear()
        self.assertIsNone(self.detector.get(self.opp["opportunity_id"]))

    def test_opp_id_prefix(self):
        self.assertTrue(
            self.opp["opportunity_id"].startswith("opp_"),
        )


class TestDetectEdgeCases(unittest.TestCase):
    """边界情况"""

    def test_empty_trigger_skipped(self):
        recs = [
            make_record(trigger="", rid=f"e{i}", ts_offset=i)
            for i in range(3)
        ]
        d = OpportunityDetector()
        self.assertEqual(d.detect(recs), [])

    def test_whitespace_trigger_skipped(self):
        recs = [
            make_record(trigger="   ", rid=f"e{i}", ts_offset=i)
            for i in range(3)
        ]
        d = OpportunityDetector()
        self.assertEqual(d.detect(recs), [])

    def test_mixed_source_types(self):
        d = OpportunityDetector()
        recs = [
            make_record(trigger="重复失败", type="failure",
                        result="错误", rid=f"f{i}", ts_offset=i)
            for i in range(2)
        ]
        recs += [
            make_record(trigger="重复失败", rid=f"s{i}", ts_offset=i)
            for i in range(3)
        ]
        out = d.detect(recs, {"suggestion": "建议改进重复失败"})
        types = {c["source_type"] for c in out}
        self.assertIn("failure", types)
        self.assertIn("repetition", types)
        self.assertIn("improvement", types)

    def test_detect_returns_copies(self):
        recs = [
            make_record(trigger="拷贝项", rid=f"e{i}", ts_offset=i)
            for i in range(3)
        ]
        d = OpportunityDetector()
        out = d.detect(recs)
        out[0]["trigger"] = "已修改"
        self.assertEqual(d.get(out[0]["opportunity_id"])["trigger"],
                         "拷贝项")


if __name__ == "__main__":
    unittest.main()
