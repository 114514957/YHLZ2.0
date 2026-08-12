"""
YHLZ Embodied AI V5.2 - Agent 数据管道单元测试 (Agent Data Pipeline)

覆盖 (pipeline.py):
    - DEFAULT_PIPELINE: 感知-策略闭环 (perception → experience → planning)
    - pipeline_stages: 阶段明细 (stage/source/target/input_from/output_to/reason)
    - analyze: 依赖顺序 / 执行顺序 / 依赖对 / 可解释原因
    - apply: 前序结果注入请求 (宽松/严格模式)
    - 严格模式: 前序无结果/缺字段 → PipelineError
    - enabled/strict 开关
    - has_stage / involved_agents
"""
import unittest

from backend.embodied.companion import (
    AgentPipeline,
    DEFAULT_PIPELINE,
    PipelineError,
)


class TestDefaultPipeline(unittest.TestCase):
    """默认管道定义"""

    def test_two_stages(self):
        """感知-策略闭环 = 2 阶段"""
        p = AgentPipeline()
        stages = p.pipeline_stages()
        self.assertEqual(len(stages), 2)

    def test_stage1_perception_to_experience(self):
        """阶段 1: perception → experience"""
        s = AgentPipeline().pipeline_stages()[0]
        self.assertEqual(s["stage"], 1)
        self.assertEqual(s["source"], "perception_agent")
        self.assertEqual(s["target"], "experience_agent")
        self.assertEqual(s["input_from"], "data")
        self.assertEqual(s["output_to"], "env_state")

    def test_stage2_experience_to_planning(self):
        """阶段 2: experience → planning"""
        s = AgentPipeline().pipeline_stages()[1]
        self.assertEqual(s["stage"], 2)
        self.assertEqual(s["source"], "experience_agent")
        self.assertEqual(s["target"], "planning_agent")
        self.assertEqual(s["output_to"], "strategy_suggestions")

    def test_stage_reason_explainable(self):
        """每阶段含可解释 reason"""
        p = AgentPipeline()
        self.assertTrue(all(s["reason"] for s in p.pipeline_stages()))

    def test_default_pipeline_constant(self):
        """DEFAULT_PIPELINE 常量"""
        self.assertEqual(len(DEFAULT_PIPELINE), 2)
        self.assertEqual(DEFAULT_PIPELINE[0]["source"], "perception_agent")

    def test_enabled_default(self):
        """默认启用"""
        self.assertTrue(AgentPipeline().enabled)

    def test_strict_default_false(self):
        """默认宽松模式"""
        self.assertFalse(AgentPipeline().strict)


class TestPipelineAnalyze(unittest.TestCase):
    """管道分析"""

    def test_analyze_structure(self):
        """分析结构完整"""
        a = AgentPipeline().analyze()
        for key in ("enabled", "strict", "stages", "execution_order",
                    "dependencies", "reason"):
            self.assertIn(key, a)

    def test_execution_order(self):
        """执行顺序 = 感知 → 经验 → 规划"""
        a = AgentPipeline().analyze()
        self.assertEqual(a["execution_order"],
                         ["perception_agent", "experience_agent",
                          "planning_agent"])

    def test_dependencies(self):
        """依赖对"""
        a = AgentPipeline().analyze()
        self.assertEqual(a["dependencies"], [
            {"target": "experience_agent", "source": "perception_agent"},
            {"target": "planning_agent", "source": "experience_agent"},
        ])

    def test_reason_explainable(self):
        """原因可解释"""
        a = AgentPipeline().analyze()
        self.assertIn("2 个阶段", a["reason"])
        self.assertIn("perception_agent", a["reason"])

    def test_disabled_flag(self):
        """停用时标志反映"""
        p = AgentPipeline(enabled=False)
        a = p.analyze()
        self.assertFalse(a["enabled"])
        self.assertIn("停用", a["reason"])

    def test_strict_flag(self):
        """严格模式标志"""
        p = AgentPipeline(strict=True)
        a = p.analyze()
        self.assertTrue(a["strict"])
        self.assertIn("严格", a["reason"])

    def test_custom_stages(self):
        """自定义管道"""
        p = AgentPipeline(stages=[{
            "stage": 1, "source": "a", "target": "b",
            "input_from": "x", "output_to": "y", "reason": "r",
        }])
        self.assertEqual(p.analyze()["execution_order"], ["a", "b"])


class TestPipelineApply(unittest.TestCase):
    """管道数据传递"""

    def _ok_result(self, payload=None):
        return {"ok": True, "result": {"data": payload or {"env": "room"}}}

    def test_apply_injects_input(self):
        """前序结果注入后序输入"""
        p = AgentPipeline()
        results = {
            "perception_agent": self._ok_result({"env": "room"}),
        }
        enriched = p.apply({"text": "扫描"}, results)
        self.assertIn("env_state", enriched)
        self.assertEqual(enriched["env_state"], {"env": "room"})

    def test_apply_preserves_original(self):
        """不修改原始请求"""
        p = AgentPipeline()
        req = {"text": "扫描"}
        results = {"perception_agent": self._ok_result({"env": "room"})}
        p.apply(req, results)
        self.assertEqual(req, {"text": "扫描"})

    def test_apply_no_result_lenient(self):
        """宽松模式: 前序未执行 → 跳过 (不注入)"""
        p = AgentPipeline(strict=False)
        enriched = p.apply({"text": "扫描"}, {})
        self.assertNotIn("env_state", enriched)

    def test_apply_missing_field_lenient(self):
        """宽松模式: 缺字段 → 传 None"""
        p = AgentPipeline(strict=False)
        results = {"perception_agent": {"ok": True,
                                        "result": {"other": 1}}}
        enriched = p.apply({"text": "x"}, results)
        self.assertIsNone(enriched["env_state"])

    def test_apply_strict_no_result_skips(self):
        """严格模式: 前序未执行 → 跳过 (不报错)"""
        p = AgentPipeline(strict=True)
        enriched = p.apply({"text": "扫描"}, {})
        self.assertNotIn("env_state", enriched)

    def test_apply_strict_missing_field_raises(self):
        """严格模式: 缺字段 → PipelineError"""
        p = AgentPipeline(strict=True)
        results = {"perception_agent": {"ok": True,
                                        "result": {"other": 1}}}
        with self.assertRaises(PipelineError):
            p.apply({"text": "x"}, results)

    def test_apply_failed_source_lenient(self):
        """宽松模式: 前序失败 → 传 None"""
        p = AgentPipeline(strict=False)
        results = {"perception_agent": {"ok": False,
                                        "error": "boom",
                                        "result": None}}
        enriched = p.apply({"text": "x"}, results)
        self.assertIsNone(enriched["env_state"])

    def test_apply_injects_both_stages(self):
        """两阶段注入 (experience 结果 → planning 输入)"""
        p = AgentPipeline()
        results = {
            "perception_agent": self._ok_result({"env": "room"}),
            "experience_agent": self._ok_result({"policies": ["p1"]}),
        }
        enriched = p.apply({"text": "x"}, results)
        self.assertIn("env_state", enriched)
        self.assertIn("strategy_suggestions", enriched)
        self.assertEqual(enriched["strategy_suggestions"],
                         {"policies": ["p1"]})


class TestPipelineControls(unittest.TestCase):
    """管道开关与查询"""

    def test_set_enabled(self):
        """启用开关"""
        p = AgentPipeline()
        p.set_enabled(False)
        self.assertFalse(p.enabled)
        p.set_enabled(True)
        self.assertTrue(p.enabled)

    def test_set_strict(self):
        """严格开关"""
        p = AgentPipeline()
        p.set_strict(True)
        self.assertTrue(p.strict)

    def test_has_stage(self):
        """阶段存在检查"""
        p = AgentPipeline()
        self.assertTrue(p.has_stage("perception_agent",
                                    "experience_agent"))
        self.assertTrue(p.has_stage("experience_agent",
                                    "planning_agent"))
        self.assertFalse(p.has_stage("a", "b"))

    def test_involved_agents(self):
        """涉及 Agent 列表"""
        p = AgentPipeline()
        self.assertEqual(p.involved_agents(),
                         ["perception_agent", "experience_agent",
                          "planning_agent"])

    def test_custom_pipeline_involved(self):
        """自定义管道涉及 Agent"""
        p = AgentPipeline(stages=[{
            "stage": 1, "source": "x", "target": "y",
            "input_from": "a", "output_to": "b", "reason": "r",
        }])
        self.assertEqual(p.involved_agents(), ["x", "y"])

    def test_analyze_dedup_sources(self):
        """执行顺序去重"""
        p = AgentPipeline(stages=[
            {"stage": 1, "source": "a", "target": "b",
             "input_from": "x", "output_to": "y", "reason": "r1"},
            {"stage": 2, "source": "a", "target": "c",
             "input_from": "x", "output_to": "z", "reason": "r2"},
        ])
        self.assertEqual(p.analyze()["execution_order"], ["a", "b", "c"])

    def test_analyze_multiple_deps(self):
        """多依赖对"""
        p = AgentPipeline(stages=[
            {"stage": 1, "source": "a", "target": "b",
             "input_from": "x", "output_to": "y", "reason": "r1"},
            {"stage": 2, "source": "b", "target": "c",
             "input_from": "y", "output_to": "z", "reason": "r2"},
        ])
        deps = p.analyze()["dependencies"]
        self.assertEqual(len(deps), 2)

    def test_apply_empty_request(self):
        """空请求应用管道"""
        p = AgentPipeline()
        results = {"perception_agent": {"ok": True,
                                        "result": {"data": {}}}}
        enriched = p.apply({}, results)
        self.assertIn("env_state", enriched)

    def test_apply_request_fields_preserved(self):
        """原请求字段保留"""
        p = AgentPipeline()
        results = {"perception_agent": {"ok": True,
                                        "result": {"data": {}}}}
        enriched = p.apply({"text": "hi", "extra": 1}, results)
        self.assertEqual(enriched["text"], "hi")
        self.assertEqual(enriched["extra"], 1)

    def test_strict_ok_passes(self):
        """严格模式: 全链路结果正常传递"""
        p = AgentPipeline(strict=True)
        results = {
            "perception_agent": {"ok": True,
                                 "result": {"data": {"e": 1}}},
            "experience_agent": {"ok": True,
                                 "result": {"data": {"p": 1}}},
        }
        enriched = p.apply({"t": "x"}, results)
        self.assertEqual(enriched["env_state"], {"e": 1})
        self.assertEqual(enriched["strategy_suggestions"], {"p": 1})

    def test_pipeline_constant_documented(self):
        """默认管道可解释字段完整"""
        for s in DEFAULT_PIPELINE:
            self.assertTrue(s["reason"])
            self.assertIn("stage", s)

    def test_involved_agents_empty(self):
        """空列表 stages 参数 → 回退默认管道"""
        p = AgentPipeline(stages=[])
        # stages=[] 为 falsy → 用 DEFAULT_PIPELINE
        self.assertEqual(p.involved_agents(),
                         ["perception_agent", "experience_agent",
                          "planning_agent"])
        self.assertEqual(len(p.analyze()["stages"]), 2)

    def test_has_stage_custom(self):
        """自定义阶段检查"""
        p = AgentPipeline(stages=[{
            "stage": 1, "source": "x", "target": "y",
            "input_from": "a", "output_to": "b", "reason": "r",
        }])
        self.assertTrue(p.has_stage("x", "y"))
        self.assertFalse(p.has_stage("y", "x"))

    def test_apply_stage2_only_results(self):
        """只有阶段 2 结果时阶段 1 跳过"""
        p = AgentPipeline(strict=False)
        results = {"experience_agent": {"ok": True,
                                        "result": {"data": {"p": 1}}}}
        enriched = p.apply({"t": "x"}, results)
        self.assertNotIn("env_state", enriched)
        self.assertEqual(enriched["strategy_suggestions"], {"p": 1})

    def test_disable_after_enable(self):
        """开关切换"""
        p = AgentPipeline()
        p.set_enabled(False)
        p.set_enabled(True)
        self.assertTrue(p.enabled)

    def test_apply_strict_failed_source_raises(self):
        """严格模式: 前序执行失败 → PipelineError"""
        p = AgentPipeline(strict=True)
        results = {"perception_agent": {"ok": False,
                                        "error": "boom",
                                        "result": None}}
        with self.assertRaises(PipelineError):
            p.apply({"t": "x"}, results)


if __name__ == "__main__":
    unittest.main()
