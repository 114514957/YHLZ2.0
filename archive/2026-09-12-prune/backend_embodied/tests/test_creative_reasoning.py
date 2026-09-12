"""
YHLZ Embodied AI V5.9 - 创造推理引擎单元测试 (Creative Reasoning Engine)

覆盖 (creative_reasoning_engine.py):
    - 路径推理: 来源类型映射 + 关键词补充
    - 5 种路径类型
    - 推理链结构: current_state / desired_state / gap / paths
    - 置信度 / 证据回溯
    - 查询 / 统计 / 异常
"""
import unittest

from backend.embodied.companion.creative import (
    PATH_KEYWORDS,
    PATH_TYPES,
    CreativeReasoningEngine,
    ReasoningError,
)


def make_opportunity(opp_id="opp_1", source_type="repetition",
                     trigger="重复需求", problem="重复需求问题",
                     gap="缺乏自动化", evidence=None,
                     confidence=0.8):
    """构造机会候选"""
    return {
        "opportunity_id": opp_id,
        "problem": problem,
        "current_state": "手动处理",
        "desired_state": "自动处理",
        "gap": gap,
        "source_type": source_type,
        "trigger": trigger,
        "evidence": evidence if evidence is not None else [
            "exp_1", "exp_2", "exp_3",
        ],
        "confidence": confidence,
        "created_at": 1000.0,
    }


class TestReasoningInit(unittest.TestCase):
    """初始化"""

    def test_default_init(self):
        r = CreativeReasoningEngine()
        self.assertIsNotNone(r)

    def test_path_types_whitelist(self):
        for t in ("automation", "optimization", "new_capability",
                  "personalization", "process_improvement"):
            self.assertIn(t, PATH_TYPES)

    def test_path_keywords_automation(self):
        self.assertTrue(any("重复" in k for k in PATH_KEYWORDS["automation"]))

    def test_path_keywords_optimization(self):
        self.assertTrue(any("失败" in k for k in PATH_KEYWORDS["optimization"]))

    def test_path_keywords_new(self):
        self.assertTrue(any("缺少" in k for k in PATH_KEYWORDS["new_capability"]))

    def test_path_keywords_personal(self):
        self.assertTrue(any("偏好" in k for k in PATH_KEYWORDS["personalization"]))

    def test_clear_empty(self):
        r = CreativeReasoningEngine()
        self.assertEqual(r.clear(), 0)


class TestReasonStructure(unittest.TestCase):
    """推理结果结构"""

    def setUp(self):
        self.engine = CreativeReasoningEngine()
        self.opp = make_opportunity()

    def test_reason_structure(self):
        r = self.engine.reason(self.opp)
        for key in ("reasoning_id", "opportunity_id", "current_state",
                    "desired_state", "gap", "paths", "confidence",
                    "mode", "reasoned_at"):
            self.assertIn(key, r)

    def test_reason_id_prefix(self):
        r = self.engine.reason(self.opp)
        self.assertTrue(r["reasoning_id"].startswith("rsn_"))

    def test_mode_rule_based(self):
        r = self.engine.reason(self.opp)
        self.assertEqual(r["mode"], "rule_based")

    def test_states_copied(self):
        r = self.engine.reason(self.opp)
        self.assertEqual(r["current_state"], "手动处理")
        self.assertEqual(r["desired_state"], "自动处理")
        self.assertEqual(r["gap"], "缺乏自动化")

    def test_at_least_one_path(self):
        r = self.engine.reason(self.opp)
        self.assertGreaterEqual(len(r["paths"]), 1)

    def test_paths_at_most_three(self):
        r = self.engine.reason(self.opp)
        self.assertLessEqual(len(r["paths"]), 3)

    def test_confidence_range(self):
        r = self.engine.reason(self.opp)
        self.assertGreaterEqual(r["confidence"], 0.0)
        self.assertLessEqual(r["confidence"], 1.0)

    def test_path_structure(self):
        r = self.engine.reason(self.opp)
        p = r["paths"][0]
        for key in ("path_id", "type", "description", "evidence",
                    "confidence"):
            self.assertIn(key, p)

    def test_path_evidence_backtrace(self):
        r = self.engine.reason(self.opp)
        for p in r["paths"]:
            self.assertEqual(len(p["evidence"]), 3)

    def test_missing_opportunity_id(self):
        with self.assertRaises(ReasoningError):
            self.engine.reason({})

    def test_none_opportunity(self):
        with self.assertRaises(ReasoningError):
            self.engine.reason(None)


class TestPathInference(unittest.TestCase):
    """路径推理规则"""

    def test_repetition_primary_automation(self):
        r = CreativeReasoningEngine()
        opp = make_opportunity(source_type="repetition")
        result = r.reason(opp)
        self.assertEqual(result["paths"][0]["type"], "automation")

    def test_failure_primary_optimization(self):
        r = CreativeReasoningEngine()
        opp = make_opportunity(source_type="failure")
        result = r.reason(opp)
        self.assertEqual(result["paths"][0]["type"], "optimization")

    def test_pattern_primary_process(self):
        r = CreativeReasoningEngine()
        opp = make_opportunity(source_type="pattern")
        result = r.reason(opp)
        self.assertEqual(result["paths"][0]["type"],
                         "process_improvement")

    def test_relationship_primary_personalization(self):
        r = CreativeReasoningEngine()
        opp = make_opportunity(source_type="relationship")
        result = r.reason(opp)
        self.assertEqual(result["paths"][0]["type"], "personalization")

    def test_improvement_primary_process(self):
        r = CreativeReasoningEngine()
        opp = make_opportunity(source_type="improvement")
        result = r.reason(opp)
        self.assertEqual(result["paths"][0]["type"],
                         "process_improvement")

    def test_keyword_automation_extra_path(self):
        r = CreativeReasoningEngine()
        opp = make_opportunity(
            source_type="improvement", problem="重复手工操作",
        )
        result = r.reason(opp)
        types = [p["type"] for p in result["paths"]]
        self.assertIn("automation", types)

    def test_keyword_optimization_extra_path(self):
        r = CreativeReasoningEngine()
        opp = make_opportunity(
            source_type="repetition", problem="频繁失败需要重试",
        )
        result = r.reason(opp)
        types = [p["type"] for p in result["paths"]]
        self.assertIn("optimization", types)

    def test_keyword_new_extra_path(self):
        r = CreativeReasoningEngine()
        opp = make_opportunity(
            source_type="pattern", gap="缺少能力",
        )
        result = r.reason(opp)
        types = [p["type"] for p in result["paths"]]
        self.assertIn("new_capability", types)

    def test_keyword_personal_extra_path(self):
        r = CreativeReasoningEngine()
        opp = make_opportunity(
            source_type="repetition", trigger="用户偏好功能",
        )
        result = r.reason(opp)
        types = [p["type"] for p in result["paths"]]
        self.assertIn("personalization", types)

    def test_no_duplicate_primary(self):
        r = CreativeReasoningEngine()
        opp = make_opportunity(source_type="repetition")
        result = r.reason(opp)
        types = [p["type"] for p in result["paths"]]
        self.assertEqual(types.count("automation"), 1)

    def test_primary_confidence_higher(self):
        r = CreativeReasoningEngine()
        opp = make_opportunity(
            source_type="repetition",
            problem="重复失败需要重试",
        )
        result = r.reason(opp)
        primary = result["paths"][0]
        others = [p for p in result["paths"][1:]
                  if p["type"] != primary["type"]]
        for p in others:
            self.assertLessEqual(p["confidence"],
                                 primary["confidence"])

    def test_no_evidence_still_reasons(self):
        r = CreativeReasoningEngine()
        opp = make_opportunity(evidence=[])
        result = r.reason(opp)
        self.assertGreaterEqual(len(result["paths"]), 1)


class TestConfidence(unittest.TestCase):
    """推理置信度"""

    def test_confidence_from_opportunity(self):
        r = CreativeReasoningEngine()
        opp = make_opportunity(confidence=0.5)
        result = r.reason(opp)
        self.assertLessEqual(result["confidence"], 0.5 * 0.8 + 0.2)

    def test_high_conf_opp_higher_result(self):
        r = CreativeReasoningEngine()
        opp_low = make_opportunity(confidence=0.2)
        opp_high = make_opportunity(confidence=0.9)
        low = r.reason(opp_low)["confidence"]
        high = r.reason(opp_high)["confidence"]
        self.assertGreater(high, low)

    def test_path_confidence_range(self):
        r = CreativeReasoningEngine()
        result = r.reason(make_opportunity())
        for p in result["paths"]:
            self.assertGreaterEqual(p["confidence"], 0.05)
            self.assertLessEqual(p["confidence"], 0.95)

    def test_confidence_cap(self):
        r = CreativeReasoningEngine()
        opp = make_opportunity(confidence=1.0,
                               evidence=[f"e{i}" for i in range(10)])
        result = r.reason(opp)
        self.assertLessEqual(result["confidence"], 0.98)


class TestQueryAndStats(unittest.TestCase):
    """查询与统计"""

    def setUp(self):
        self.engine = CreativeReasoningEngine()
        self.result = self.engine.reason(make_opportunity())

    def test_get_by_id(self):
        r = self.engine.get(self.result["reasoning_id"])
        self.assertEqual(r["opportunity_id"], "opp_1")

    def test_get_missing(self):
        self.assertIsNone(self.engine.get("rsn_nonexist"))

    def test_by_opportunity(self):
        results = self.engine.by_opportunity("opp_1")
        self.assertEqual(len(results), 1)

    def test_by_opportunity_none(self):
        self.assertEqual(self.engine.by_opportunity("opp_x"), [])

    def test_stats_structure(self):
        st = self.engine.stats()
        for key in ("mode", "reasoning_count", "avg_paths",
                    "by_path_type"):
            self.assertIn(key, st)

    def test_stats_count(self):
        self.engine.reason(make_opportunity(opp_id="opp_2"))
        self.assertEqual(self.engine.stats()["reasoning_count"], 2)

    def test_stats_by_path_type(self):
        st = self.engine.stats()
        self.assertIn("automation", st["by_path_type"])

    def test_clear(self):
        self.engine.clear()
        self.assertEqual(self.engine.stats()["reasoning_count"], 0)

    def test_get_after_clear(self):
        self.engine.clear()
        self.assertIsNone(self.engine.get(self.result["reasoning_id"]))


class TestEdgeCases(unittest.TestCase):
    """边界情况"""

    def test_no_path_keywords_fallback(self):
        r = CreativeReasoningEngine()
        opp = make_opportunity(
            source_type="failure", trigger="X", problem="Y",
            gap="Z",
        )
        result = r.reason(opp)
        self.assertEqual(result["paths"][0]["type"], "optimization")

    def test_long_trigger_ok(self):
        r = CreativeReasoningEngine()
        opp = make_opportunity(trigger="长" * 100)
        result = r.reason(opp)
        self.assertGreaterEqual(len(result["paths"]), 1)

    def test_reason_does_not_mutate(self):
        r = CreativeReasoningEngine()
        opp = make_opportunity()
        before = dict(opp)
        r.reason(opp)
        self.assertEqual(opp, before)

    def test_empty_evidence_path(self):
        r = CreativeReasoningEngine()
        opp = make_opportunity(evidence=[])
        result = r.reason(opp)
        for p in result["paths"]:
            self.assertEqual(p["evidence"], [])


if __name__ == "__main__":
    unittest.main()
