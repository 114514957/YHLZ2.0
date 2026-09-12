"""
YHLZ Embodied AI V5.9 - 模拟引擎单元测试 (Simulation Engine)

覆盖 (simulation_engine.py):
    - 模拟结构: expected_result / risk_analysis / side_effects /
      feasibility / recommendation / confidence
    - 成功率规则 / 风险分析 / 副作用检测
    - 推荐: proceed / revise / abandon (阈值)
    - 查询 / 统计 / 异常
"""
import unittest

from backend.embodied.companion.creative import (
    RECOMMENDATIONS,
    SIDE_EFFECT_KEYWORDS,
    SimulationEngine,
    SimulationError,
)


def make_proposal(pid="cp_1", title="自动化重复需求",
                  idea="将重复需求封装为自动化流程",
                  reasoning="当前: 手动 → 理想: 自动", risk="low",
                  evidence=None):
    return {
        "proposal_id": pid,
        "title": title,
        "problem": "重复需求问题",
        "idea": idea,
        "reasoning": reasoning,
        "expected_value": "影响 high",
        "risk": risk,
        "confidence": 0.8,
        "source_type": "repetition",
        "path_type": "automation",
        "evidence": evidence if evidence is not None else [
            "exp_1", "exp_2",
        ],
        "opportunity_id": "opp_1",
        "status": "PENDING",
        "simulation": None,
        "created_at": 1000.0,
    }


def make_experience(trigger="重复需求", type="improvement",
                    result="成功", rid="exp_0"):
    return {
        "id": rid, "type": type, "trigger": trigger,
        "lesson": "l", "result": result,
    }


class TestSimulationInit(unittest.TestCase):
    """初始化与参数校验"""

    def test_default_init(self):
        s = SimulationEngine()
        self.assertIsNotNone(s)

    def test_proceed_rate_validation(self):
        with self.assertRaises(SimulationError):
            SimulationEngine(proceed_rate=1.5)

    def test_revise_rate_validation(self):
        with self.assertRaises(SimulationError):
            SimulationEngine(revise_rate=-0.1)

    def test_revise_less_than_proceed(self):
        with self.assertRaises(SimulationError):
            SimulationEngine(proceed_rate=0.4, revise_rate=0.6)

    def test_recommendations_whitelist(self):
        self.assertEqual(set(RECOMMENDATIONS),
                         {"proceed", "revise", "abandon"})

    def test_side_effect_keywords_nonempty(self):
        self.assertTrue(SIDE_EFFECT_KEYWORDS)


class TestSimulateStructure(unittest.TestCase):
    """模拟结果结构"""

    def setUp(self):
        self.engine = SimulationEngine()
        self.proposal = make_proposal()

    def test_simulate_structure(self):
        r = self.engine.simulate(self.proposal)
        for key in ("simulation_id", "proposal_id", "expected_result",
                    "risk_analysis", "side_effects", "feasibility",
                    "recommendation", "confidence", "mode",
                    "simulated_at"):
            self.assertIn(key, r)

    def test_sim_id_prefix(self):
        r = self.engine.simulate(self.proposal)
        self.assertTrue(r["simulation_id"].startswith("sim_"))

    def test_mode_rule_based(self):
        r = self.engine.simulate(self.proposal)
        self.assertEqual(r["mode"], "rule_based")

    def test_recommendation_valid(self):
        r = self.engine.simulate(self.proposal)
        self.assertIn(r["recommendation"], RECOMMENDATIONS)

    def test_feasibility_valid(self):
        r = self.engine.simulate(self.proposal)
        self.assertIn(r["feasibility"], ("high", "medium", "low"))

    def test_confidence_range(self):
        r = self.engine.simulate(self.proposal)
        self.assertGreaterEqual(r["confidence"], 0.0)
        self.assertLessEqual(r["confidence"], 1.0)

    def test_expected_result_mentions_rate(self):
        r = self.engine.simulate(self.proposal)
        self.assertIn("成功率", r["expected_result"])

    def test_side_effects_list(self):
        r = self.engine.simulate(self.proposal)
        self.assertIsInstance(r["side_effects"], list)

    def test_risk_analysis_nonempty(self):
        r = self.engine.simulate(self.proposal)
        self.assertTrue(r["risk_analysis"])

    def test_missing_proposal_id(self):
        with self.assertRaises(SimulationError):
            self.engine.simulate({})

    def test_none_proposal(self):
        with self.assertRaises(SimulationError):
            self.engine.simulate(None)


class TestSuccessRate(unittest.TestCase):
    """成功率与推荐"""

    def test_proceed_high_success(self):
        s = SimulationEngine()
        exps = [
            make_experience(result="成功", rid=f"e{i}")
            for i in range(10)
        ]
        r = s.simulate(make_proposal(), exps)
        self.assertEqual(r["recommendation"], "proceed")
        self.assertEqual(r["feasibility"], "high")

    def test_abandon_low_success(self):
        s = SimulationEngine(proceed_rate=0.9, revise_rate=0.85)
        exps = [
            make_experience(type="failure", result="错误", rid=f"e{i}")
            for i in range(10)
        ]
        r = s.simulate(make_proposal(), exps)
        self.assertEqual(r["recommendation"], "abandon")
        self.assertEqual(r["feasibility"], "low")

    def test_revise_middle(self):
        s = SimulationEngine(proceed_rate=0.9, revise_rate=0.3)
        exps = (
            [make_experience(result="成功", rid=f"s{i}")
             for i in range(4)]
            + [make_experience(type="failure", result="错误",
                               rid=f"f{i}")
               for i in range(6)]
        )
        r = s.simulate(make_proposal(), exps)
        self.assertEqual(r["recommendation"], "revise")
        self.assertEqual(r["feasibility"], "medium")

    def test_no_experience_conservative(self):
        s = SimulationEngine(proceed_rate=0.5)
        r = s.simulate(make_proposal(), [])
        self.assertIn(r["recommendation"], RECOMMENDATIONS)

    def test_no_experience_default_rate(self):
        s = SimulationEngine()
        r = s.simulate(make_proposal(), [])
        self.assertEqual(r["recommendation"], "revise")

    def test_risk_penalty_lowers_recommendation(self):
        """高风险降低有效成功率"""
        s = SimulationEngine(proceed_rate=0.65)
        exps = (
            [make_experience(result="成功", rid=f"s{i}")
             for i in range(6)]
            + [make_experience(type="failure", result="错误",
                               rid=f"f{i}")
               for i in range(4)]
        )
        r = s.simulate(make_proposal(risk="high"), exps)
        self.assertNotEqual(r["recommendation"], "proceed")

    def test_related_experience_priority(self):
        """相关情境经验优先"""
        s = SimulationEngine()
        exps = (
            [make_experience(trigger="重复需求", result="成功",
                             rid=f"r{i}")
             for i in range(5)]
            + [make_experience(trigger="其他", result="成功",
                               rid=f"o{i}")
               for i in range(5)]
        )
        r = s.simulate(make_proposal(), exps)
        self.assertEqual(r["recommendation"], "proceed")

    def test_confidence_grows_with_samples(self):
        s = SimulationEngine()
        r1 = s.simulate(make_proposal(), [
            make_experience(result="成功") for _ in range(2)
        ])
        r2 = s.simulate(make_proposal(), [
            make_experience(result="成功") for _ in range(10)
        ])
        self.assertGreaterEqual(r2["confidence"], r1["confidence"])


class TestRiskAnalysis(unittest.TestCase):
    """风险分析"""

    def test_no_failures_low_risk(self):
        s = SimulationEngine()
        exps = [
            make_experience(result="成功", rid=f"e{i}")
            for i in range(5)
        ]
        r = s.simulate(make_proposal(), exps)
        self.assertIn("风险低", r["risk_analysis"])

    def test_high_failure_ratio_high_risk(self):
        s = SimulationEngine()
        exps = (
            [make_experience(type="failure", result="错误",
                             rid=f"f{i}")
             for i in range(8)]
            + [make_experience(result="成功", rid=f"s{i}")
               for i in range(2)]
        )
        r = s.simulate(make_proposal(), exps)
        self.assertIn("高风险", r["risk_analysis"])

    def test_medium_failure_ratio(self):
        s = SimulationEngine()
        exps = (
            [make_experience(type="failure", result="错误",
                             rid=f"f{i}")
             for i in range(3)]
            + [make_experience(result="成功", rid=f"s{i}")
               for i in range(7)]
        )
        r = s.simulate(make_proposal(), exps)
        self.assertIn("中风险", r["risk_analysis"])

    def test_risk_analysis_mentions_trigger(self):
        s = SimulationEngine()
        exps = [
            make_experience(type="failure", result="错误",
                            trigger="超时", rid=f"f{i}")
            for i in range(6)
        ]
        r = s.simulate(make_proposal(), exps)
        self.assertIn("超时", r["risk_analysis"])


class TestSideEffects(unittest.TestCase):
    """副作用检测"""

    def test_effect_keyword_detected(self):
        s = SimulationEngine()
        proposal = make_proposal(idea="将流程覆盖旧方案")
        r = s.simulate(proposal, [])
        self.assertTrue(any("覆盖" in e for e in r["side_effects"]))

    def test_effect_conflict_detected(self):
        s = SimulationEngine()
        proposal = make_proposal(idea="删除旧接口实现")
        r = s.simulate(proposal, [])
        self.assertTrue(any("删除" in e for e in r["side_effects"]))

    def test_no_effect_clean(self):
        s = SimulationEngine()
        proposal = make_proposal(idea="新增便捷模板")
        r = s.simulate(proposal, [
            make_experience(result="成功"),
        ])
        self.assertFalse(
            any(k in proposal["idea"] for k in SIDE_EFFECT_KEYWORDS),
        )

    def test_no_evidence_warning(self):
        s = SimulationEngine()
        proposal = make_proposal(evidence=[])
        r = s.simulate(proposal, [])
        self.assertTrue(any("证据" in e for e in r["side_effects"]))

    def test_effects_at_most_five(self):
        s = SimulationEngine()
        proposal = make_proposal(
            idea="删除覆盖冲突失败禁用降级",
            reasoning="覆盖冲突失败禁用降级",
            title="删除覆盖冲突失败禁用降级",
        )
        r = s.simulate(proposal, [])
        self.assertLessEqual(len(r["side_effects"]), 5)

    def test_effect_from_reasoning(self):
        s = SimulationEngine()
        proposal = make_proposal(reasoning="此改动与旧经验冲突")
        r = s.simulate(proposal, [])
        self.assertTrue(any("冲突" in e for e in r["side_effects"]))


class TestQueryAndStats(unittest.TestCase):
    """查询与统计"""

    def setUp(self):
        self.engine = SimulationEngine()
        self.result = self.engine.simulate(
            make_proposal(),
            [make_experience(result="成功") for _ in range(5)],
        )

    def test_get_by_id(self):
        r = self.engine.get(self.result["simulation_id"])
        self.assertEqual(r["proposal_id"], "cp_1")

    def test_get_missing(self):
        self.assertIsNone(self.engine.get("sim_nonexist"))

    def test_by_proposal(self):
        results = self.engine.by_proposal("cp_1")
        self.assertEqual(len(results), 1)

    def test_by_proposal_none(self):
        self.assertEqual(self.engine.by_proposal("cp_x"), [])

    def test_stats_structure(self):
        st = self.engine.stats()
        for key in ("mode", "simulation_count", "by_recommendation",
                    "by_feasibility", "risk_found_count"):
            self.assertIn(key, st)

    def test_stats_count(self):
        self.engine.simulate(make_proposal(pid="cp_2"), [])
        self.assertEqual(self.engine.stats()["simulation_count"], 2)

    def test_stats_risk_found(self):
        self.engine.simulate(
            make_proposal(pid="cp_3", idea="删除旧接口"),
            [],
        )
        self.assertGreaterEqual(self.engine.stats()["risk_found_count"], 1)

    def test_clear(self):
        self.engine.clear()
        self.assertEqual(self.engine.stats()["simulation_count"], 0)

    def test_get_after_clear(self):
        self.engine.clear()
        self.assertIsNone(self.engine.get(self.result["simulation_id"]))


class TestEdgeCases(unittest.TestCase):
    """边界情况"""

    def test_simulate_does_not_mutate(self):
        s = SimulationEngine()
        proposal = make_proposal()
        before = dict(proposal)
        s.simulate(proposal, [])
        self.assertEqual(proposal, before)

    def test_experiences_none(self):
        s = SimulationEngine()
        r = s.simulate(make_proposal(), None)
        self.assertIn(r["recommendation"], RECOMMENDATIONS)

    def test_many_experiences(self):
        s = SimulationEngine()
        exps = [
            make_experience(result="成功", rid=f"e{i}")
            for i in range(50)
        ]
        r = s.simulate(make_proposal(), exps)
        self.assertIn(r["recommendation"], RECOMMENDATIONS)

    def test_high_risk_proposal_risk_analysis(self):
        s = SimulationEngine()
        exps = [
            make_experience(type="failure", result="错误", rid=f"f{i}")
            for i in range(3)
        ]
        r = s.simulate(make_proposal(risk="high"), exps)
        self.assertTrue(r["risk_analysis"])


if __name__ == "__main__":
    unittest.main()
