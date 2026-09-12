"""
YHLZ Embodied AI V5.9 - 方案生成器单元测试 (Proposal Generator)

覆盖 (proposal_generator.py):
    - 方案结构: title / problem / idea / reasoning / expected_value /
      risk / confidence
    - 必须: 有来源 (evidence) / 有推理链 (reasoning) /
      有风险分析 (risk) / 有预期收益 (expected_value)
    - 标题规则 (路径类型)
    - 决策门槛: 只有 create 可生成
    - 上限 / 查询 / 统计 / 异常
"""
import unittest

from backend.embodied.companion.creative import (
    ProposalGenerationError,
    ProposalGenerator,
)


def make_opportunity(opp_id="opp_1", source_type="repetition",
                     trigger="重复需求", confidence=0.8,
                     evidence=None):
    if evidence is None:
        evidence = [f"exp_{i}" for i in range(3)]
    return {
        "opportunity_id": opp_id,
        "problem": f"{trigger}问题",
        "current_state": "手动处理",
        "desired_state": "自动处理",
        "gap": "缺乏自动化",
        "source_type": source_type,
        "trigger": trigger,
        "evidence": evidence,
        "confidence": confidence,
        "created_at": 1000.0,
    }


def make_reasoning(opp_id="opp_1", path_type="automation",
                   confidence=0.7):
    return {
        "reasoning_id": "rsn_1",
        "opportunity_id": opp_id,
        "current_state": "手动处理",
        "desired_state": "自动处理",
        "gap": "缺乏自动化",
        "paths": [
            {"path_id": "path_1", "type": path_type,
             "description": f"{path_type} 路径描述",
             "evidence": ["exp_1"], "confidence": 0.8},
        ],
        "confidence": confidence,
    }


def make_evaluation(opp_id="opp_1", decision="create",
                    value_score=0.75, risk="low"):
    return {
        "evaluation_id": "eval_1",
        "opportunity_id": opp_id,
        "value_score": value_score,
        "impact": "high",
        "frequency": "high",
        "benefit": "high",
        "feasibility": "high",
        "risk": risk,
        "dimensions": [
            {"name": "impact", "level": "high", "score": 0.9,
             "reason": "r"},
            {"name": "frequency", "level": "high", "score": 0.9,
             "reason": "r"},
            {"name": "benefit", "level": "high", "score": 0.9,
             "reason": "r"},
            {"name": "feasibility", "level": "high", "score": 0.9,
             "reason": "r"},
            {"name": "risk", "level": "low", "score": 0.1,
             "reason": "r"},
        ],
        "decision": decision,
        "decision_reason": "值得创造",
    }


class TestGeneratorInit(unittest.TestCase):
    """初始化与参数校验"""

    def test_default_init(self):
        g = ProposalGenerator()
        self.assertIsNotNone(g)

    def test_max_validation(self):
        with self.assertRaises(ProposalGenerationError):
            ProposalGenerator(max_proposals=0)

    def test_max_validation_negative(self):
        with self.assertRaises(ProposalGenerationError):
            ProposalGenerator(max_proposals=-5)


class TestGenerateStructure(unittest.TestCase):
    """方案结构"""

    def setUp(self):
        self.generator = ProposalGenerator()
        self.opp = make_opportunity()
        self.rsn = make_reasoning()
        self.eval = make_evaluation()

    def test_proposal_structure(self):
        p = self.generator.generate(self.opp, self.rsn, self.eval)
        for key in ("proposal_id", "title", "problem", "idea",
                    "reasoning", "expected_value", "risk", "confidence",
                    "source_type", "path_type", "evidence",
                    "opportunity_id", "reasoning_id", "evaluation_id",
                    "status", "simulation", "created_at"):
            self.assertIn(key, p)

    def test_proposal_id_prefix(self):
        p = self.generator.generate(self.opp, self.rsn, self.eval)
        self.assertTrue(p["proposal_id"].startswith("cp_"))

    def test_title_from_repetition_automation(self):
        p = self.generator.generate(self.opp, self.rsn, self.eval)
        self.assertEqual(p["title"], "自动化重复需求")

    def test_title_optimization(self):
        opp = make_opportunity(source_type="failure", trigger="拾取失败")
        rsn = make_reasoning(path_type="optimization")
        p = self.generator.generate(opp, rsn, self.eval)
        self.assertEqual(p["title"], "优化拾取失败方案")

    def test_title_new_capability(self):
        opp = make_opportunity(trigger="语音识别")
        rsn = make_reasoning(path_type="new_capability")
        p = self.generator.generate(opp, rsn, self.eval)
        self.assertEqual(p["title"], "新增语音识别能力")

    def test_title_personalization(self):
        opp = make_opportunity(trigger="早安问候")
        rsn = make_reasoning(path_type="personalization")
        p = self.generator.generate(opp, rsn, self.eval)
        self.assertEqual(p["title"], "个性化早安问候服务")

    def test_title_process_improvement(self):
        opp = make_opportunity(trigger="任务执行")
        rsn = make_reasoning(path_type="process_improvement")
        p = self.generator.generate(opp, rsn, self.eval)
        self.assertEqual(p["title"], "改进任务执行流程")

    def test_problem_copied(self):
        p = self.generator.generate(self.opp, self.rsn, self.eval)
        self.assertEqual(p["problem"], "重复需求问题")

    def test_idea_contains_path_description(self):
        p = self.generator.generate(self.opp, self.rsn, self.eval)
        self.assertIn("automation 路径描述", p["idea"])

    def test_reasoning_chain(self):
        p = self.generator.generate(self.opp, self.rsn, self.eval)
        self.assertIn("当前:", p["reasoning"])
        self.assertIn("理想:", p["reasoning"])

    def test_expected_value_from_evaluation(self):
        p = self.generator.generate(self.opp, self.rsn, self.eval)
        self.assertIn("影响 high", p["expected_value"])
        self.assertIn("价值分 0.75", p["expected_value"])

    def test_risk_copied(self):
        p = self.generator.generate(self.opp, self.rsn, self.eval)
        self.assertEqual(p["risk"], "low")

    def test_risk_high(self):
        ev = make_evaluation(risk="high")
        p = self.generator.generate(self.opp, self.rsn, ev)
        self.assertEqual(p["risk"], "high")

    def test_evidence_backtrace(self):
        p = self.generator.generate(self.opp, self.rsn, self.eval)
        self.assertEqual(len(p["evidence"]), 3)

    def test_status_pending(self):
        p = self.generator.generate(self.opp, self.rsn, self.eval)
        self.assertEqual(p["status"], "PENDING")

    def test_simulation_none(self):
        p = self.generator.generate(self.opp, self.rsn, self.eval)
        self.assertIsNone(p["simulation"])

    def test_confidence_range(self):
        p = self.generator.generate(self.opp, self.rsn, self.eval)
        self.assertGreaterEqual(p["confidence"], 0.0)
        self.assertLessEqual(p["confidence"], 1.0)

    def test_confidence_combines_inputs(self):
        opp = make_opportunity(confidence=0.5)
        rsn = make_reasoning(confidence=0.5)
        ev = make_evaluation(value_score=0.5)
        p = self.generator.generate(opp, rsn, ev)
        self.assertAlmostEqual(p["confidence"], 0.5, places=2)

    def test_path_type_recorded(self):
        p = self.generator.generate(self.opp, self.rsn, self.eval)
        self.assertEqual(p["path_type"], "automation")

    def test_ids_backtrace(self):
        p = self.generator.generate(self.opp, self.rsn, self.eval)
        self.assertEqual(p["opportunity_id"], "opp_1")
        self.assertEqual(p["reasoning_id"], "rsn_1")
        self.assertEqual(p["evaluation_id"], "eval_1")


class TestGenerateGuards(unittest.TestCase):
    """生成门槛"""

    def setUp(self):
        self.generator = ProposalGenerator()

    def test_reject_non_create(self):
        opp = make_opportunity()
        rsn = make_reasoning()
        ev = make_evaluation(decision="defer")
        with self.assertRaises(ProposalGenerationError):
            self.generator.generate(opp, rsn, ev)

    def test_reject_decision(self):
        opp = make_opportunity()
        rsn = make_reasoning()
        ev = make_evaluation(decision="reject")
        with self.assertRaises(ProposalGenerationError):
            self.generator.generate(opp, rsn, ev)

    def test_missing_opportunity(self):
        with self.assertRaises(ProposalGenerationError):
            self.generator.generate({}, make_reasoning(),
                                    make_evaluation())

    def test_missing_reasoning(self):
        with self.assertRaises(ProposalGenerationError):
            self.generator.generate(make_opportunity(), {},
                                    make_evaluation())

    def test_missing_evaluation(self):
        with self.assertRaises(ProposalGenerationError):
            self.generator.generate(make_opportunity(),
                                    make_reasoning(), {})

    def test_max_proposals(self):
        g = ProposalGenerator(max_proposals=1)
        g.generate(make_opportunity(), make_reasoning(),
                   make_evaluation())
        with self.assertRaises(ProposalGenerationError):
            g.generate(make_opportunity(opp_id="opp_2"),
                       make_reasoning(opp_id="opp_2"),
                       make_evaluation(opp_id="opp_2"))

    def test_none_inputs(self):
        with self.assertRaises(ProposalGenerationError):
            self.generator.generate(None, None, None)


class TestQueryAndStats(unittest.TestCase):
    """查询与统计"""

    def setUp(self):
        self.generator = ProposalGenerator()
        self.prop = self.generator.generate(
            make_opportunity(), make_reasoning(), make_evaluation(),
        )

    def test_get_by_id(self):
        p = self.generator.get(self.prop["proposal_id"])
        self.assertEqual(p["title"], "自动化重复需求")

    def test_get_missing(self):
        self.assertIsNone(self.generator.get("cp_nonexist"))

    def test_by_opportunity(self):
        ps = self.generator.by_opportunity("opp_1")
        self.assertEqual(len(ps), 1)

    def test_by_opportunity_none(self):
        self.assertEqual(self.generator.by_opportunity("opp_x"), [])

    def test_stats_structure(self):
        st = self.generator.stats()
        for key in ("mode", "proposal_count", "by_source_type",
                    "by_risk"):
            self.assertIn(key, st)

    def test_stats_count(self):
        self.generator.generate(
            make_opportunity(opp_id="opp_2", trigger="另一需求"),
            make_reasoning(opp_id="opp_2"),
            make_evaluation(opp_id="opp_2"),
        )
        self.assertEqual(self.generator.stats()["proposal_count"], 2)

    def test_stats_by_risk(self):
        ev = make_evaluation(risk="high")
        self.generator.generate(
            make_opportunity(opp_id="opp_3", trigger="高风险"),
            make_reasoning(opp_id="opp_3"),
            ev,
        )
        st = self.generator.stats()
        self.assertGreaterEqual(st["by_risk"].get("high", 0), 1)

    def test_clear(self):
        self.generator.clear()
        self.assertEqual(self.generator.stats()["proposal_count"], 0)

    def test_get_after_clear(self):
        self.generator.clear()
        self.assertIsNone(self.generator.get(self.prop["proposal_id"]))


class TestEdgeCases(unittest.TestCase):
    """边界情况"""

    def test_empty_evidence(self):
        g = ProposalGenerator()
        opp = make_opportunity(evidence=[])
        p = g.generate(opp, make_reasoning(), make_evaluation())
        self.assertEqual(p["evidence"], [])

    def test_generate_does_not_mutate(self):
        g = ProposalGenerator()
        opp = make_opportunity()
        before = dict(opp)
        g.generate(opp, make_reasoning(), make_evaluation())
        self.assertEqual(opp, before)

    def test_no_paths_reasoning(self):
        g = ProposalGenerator()
        rsn = make_reasoning()
        rsn["paths"] = []
        p = g.generate(make_opportunity(), rsn, make_evaluation())
        self.assertEqual(p["path_type"], "process_improvement")

    def test_generated_copies(self):
        g = ProposalGenerator()
        p = g.generate(make_opportunity(), make_reasoning(),
                       make_evaluation())
        p["title"] = "已修改"
        stored = g.get(p["proposal_id"])
        self.assertNotEqual(stored["title"], "已修改")

    def test_unknown_source_type(self):
        g = ProposalGenerator()
        opp = make_opportunity(source_type="unknown_type")
        p = g.generate(opp, make_reasoning(), make_evaluation())
        self.assertTrue(p["proposal_id"].startswith("cp_"))


if __name__ == "__main__":
    unittest.main()
