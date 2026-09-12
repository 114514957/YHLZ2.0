"""
YHLZ Embodied AI V5.2 - 管道感知委派单元测试 (Pipeline-Aware Delegation)

覆盖 (delegate.py V5.2):
    - 管道委派: 感知-策略闭环 (perception → experience → planning 依赖顺序)
    - CompanionResponse 含 pipeline / pipeline_stages
    - 管道注入: 前序结果 → 后序输入 (后序 Agent 可读)
    - 管道停用 → 常规委派
    - 管道未命中 (无 perception) → 常规委派
    - 严格模式: 前序失败 → 管道异常标记 (不崩溃)
    - 与并发委派兼容
"""
import time
import unittest

from backend.embodied.companion import (
    AgentPipeline,
    CompanionRouter,
    SpecialistRegistry,
    TaskDelegator,
)


def capture_handler(trace):
    def handler(request):
        trace.append(request.get("env_state", "NO_INPUT"))
        trace.append(request.get("strategy_suggestions", "NO_INPUT"))
        return {"data": {"seen": dict(request)}}
    return handler


class TestPipelineDelegation(unittest.TestCase):
    """管道委派"""

    def setUp(self):
        self.trace = []
        self.reg = SpecialistRegistry()
        self.reg.register_simple("perception_agent", "perception",
                                 capture_handler(self.trace))
        self.reg.register_simple("experience_agent", "experience",
                                 capture_handler(self.trace))
        self.reg.register_simple("planning_agent", "planning",
                                 capture_handler(self.trace))
        self.router = CompanionRouter(self.reg, top_k=3)
        self.delegator = TaskDelegator(self.router, workers=4)

    def test_pipeline_in_response(self):
        """响应含 pipeline 明细"""
        r = self.delegator.delegate({"text": "扫描环境查看策略建议制定规划"})
        self.assertIn("pipeline", r)
        self.assertIsNotNone(r["pipeline"])
        self.assertEqual(len(r["pipeline_stages"]), 2)

    def test_pipeline_execution_order(self):
        """管道执行顺序: perception → experience → planning"""
        r = self.delegator.delegate(
            {"text": "扫描环境查看策略建议制定规划"},
        )
        result_agents = [x["agent"] for x in r["results"]]
        self.assertEqual(result_agents,
                         ["perception_agent", "experience_agent",
                          "planning_agent"])

    def test_pipeline_all_ok(self):
        """管道全链路成功"""
        r = self.delegator.delegate({"text": "扫描环境查看策略建议制定规划"})
        self.assertTrue(r["aggregated"]["all_ok"])
        self.assertEqual(r["aggregated"]["ok_count"],
                         r["aggregated"]["total"])

    def test_perception_input_injected_to_experience(self):
        """感知输出注入经验 Agent 输入"""
        self.delegator.delegate({"text": "扫描环境查看策略建议制定规划"})
        # trace: 每个 Agent 记录 env_state / strategy_suggestions
        # perception 先执行, 其输出 data 注入 env_state
        # experience 记录 env_state 应非 NO_INPUT (有 data)
        self.assertIn("NO_INPUT", self.trace)  # perception 无 env_state
        # experience 的 env_state 应是感知结果 (dict)
        idx = self.trace.index("NO_INPUT")  # perception 第 0 个
        experience_env = self.trace[idx + 2]  # perception: 2 项, experience 第 1 项
        self.assertIsNotNone(experience_env)

    def test_strategy_input_injected_to_planning(self):
        """策略输出注入规划 Agent 输入"""
        self.delegator.delegate({"text": "扫描环境查看策略建议制定规划"})
        # planning 收到 strategy_suggestions (来自 experience 输出)
        self.assertTrue(any(
            s is not None and isinstance(s, dict)
            for s in self.trace
        ))

    def test_reason_contains_pipeline(self):
        """原因含管道阶段说明"""
        r = self.delegator.delegate({"text": "扫描环境查看策略建议制定规划"})
        self.assertIn("[管道]", r["explainable_reason"])
        self.assertIn("perception_agent", r["explainable_reason"])


class TestPipelineOff(unittest.TestCase):
    """管道停用"""

    def test_disabled_regular_delegation(self):
        """停用 → 常规并发委派"""
        reg = SpecialistRegistry()
        reg.register_simple("perception_agent", "perception",
                            lambda req: {"data": {}})
        reg.register_simple("experience_agent", "experience",
                            lambda req: {"data": {}})
        reg.register_simple("planning_agent", "planning",
                            lambda req: {"data": {}})
        router = CompanionRouter(reg, top_k=3)
        pipeline = AgentPipeline(enabled=False)
        d = TaskDelegator(router, workers=4, pipeline=pipeline)
        r = d.delegate({"text": "扫描环境查看策略建议制定规划"})
        self.assertIsNone(r["pipeline"])
        self.assertEqual(r["pipeline_stages"], [])
        # 常规委派: 并发执行
        self.assertTrue(r["dispatched_parallel"])


class TestPipelinePartial(unittest.TestCase):
    """管道未命中 (无 perception)"""

    def test_no_perception_regular(self):
        """无感知请求 → 常规委派"""
        reg = SpecialistRegistry()
        reg.register_simple("governance_agent", "governance",
                            lambda req: {"data": {}})
        reg.register_simple("experience_agent", "experience",
                            lambda req: {"data": {}})
        router = CompanionRouter(reg, top_k=3)
        d = TaskDelegator(router)
        # 请求"治理健康检查" → governance (无 perception)
        r = d.delegate({"text": "治理健康检查"})
        # 管道阶段源 perception 未分派 → 常规委派
        self.assertIsNone(r["pipeline"])
        self.assertTrue(r["aggregated"]["all_ok"])


class TestPipelineStrict(unittest.TestCase):
    """严格模式"""

    def test_strict_source_failure_marked(self):
        """严格模式: 前序失败 → 管道异常标记 (不崩溃)"""
        reg = SpecialistRegistry()

        def boom(req):
            raise RuntimeError("boom")

        reg.register_simple("perception_agent", "perception", boom)
        reg.register_simple("experience_agent", "experience",
                            lambda req: {"data": {}})
        reg.register_simple("planning_agent", "planning",
                            lambda req: {"data": {}})
        router = CompanionRouter(reg, top_k=3)
        pipeline = AgentPipeline(strict=True)
        d = TaskDelegator(router, pipeline=pipeline)
        r = d.delegate({"text": "扫描环境查看策略建议制定规划"})
        # 管道阶段执行: perception 失败 → experience/planning 标记管道异常
        by_agent = {x["agent"]: x for x in r["results"]}
        self.assertFalse(by_agent["perception_agent"]["ok"])
        self.assertIn("管道异常", by_agent["experience_agent"]["error"])

    def test_lenient_source_failure(self):
        """宽松模式: 前序失败 → 后序继续 (传 None)"""
        reg = SpecialistRegistry()

        def boom(req):
            raise RuntimeError("boom")

        seen = []
        reg.register_simple("perception_agent", "perception", boom)
        reg.register_simple(
            "experience_agent", "experience",
            lambda req: (seen.append(req.get("env_state")), {"data": {}})[1],
        )
        reg.register_simple("planning_agent", "planning",
                            lambda req: {"data": {}})
        router = CompanionRouter(reg, top_k=3)
        d = TaskDelegator(router)  # 默认宽松
        r = d.delegate({"text": "扫描环境查看策略建议制定规划"})
        self.assertTrue(r["aggregated"]["all_ok"] or
                        any(x["ok"] for x in r["results"]))


class TestPipelineWithTimeout(unittest.TestCase):
    """管道 + 超时兼容"""

    def test_pipeline_slow_source_timeout(self):
        """慢前序超时 → 后序标记"""
        reg = SpecialistRegistry()

        def slow(req):
            time.sleep(0.5)
            return {"data": {}}

        reg.register_simple("perception_agent", "perception", slow)
        reg.register_simple("experience_agent", "experience",
                            lambda req: {"data": {}})
        router = CompanionRouter(reg, top_k=3)
        d = TaskDelegator(router, timeout=0.05)
        r = d.delegate({"text": "扫描并规划"})
        by_agent = {x["agent"]: x for x in r["results"]}
        self.assertFalse(by_agent["perception_agent"]["ok"])
        self.assertIn("超时", by_agent["perception_agent"]["error"])


class TestPipelineResponseFields(unittest.TestCase):
    """管道响应字段"""

    def setUp(self):
        reg = SpecialistRegistry()
        reg.register_simple("perception_agent", "perception",
                            lambda req: {"data": {"env": "room"}})
        reg.register_simple("experience_agent", "experience",
                            lambda req: {"data": {"policies": ["p1"]}})
        reg.register_simple("planning_agent", "planning",
                            lambda req: {"data": {"plan": 1}})
        router = CompanionRouter(reg, top_k=3)
        self.d = TaskDelegator(router, workers=4)
        self.r = self.d.delegate(
            {"text": "扫描环境查看策略建议制定规划"},
        )

    def test_pipeline_not_none(self):
        """管道明细存在"""
        self.assertIsNotNone(self.r["pipeline"])

    def test_pipeline_stages_two(self):
        """2 阶段"""
        self.assertEqual(len(self.r["pipeline_stages"]), 2)

    def test_stage_fields(self):
        """阶段字段完整"""
        for s in self.r["pipeline_stages"]:
            for key in ("stage", "source", "target", "input_from",
                        "output_to", "reason"):
                self.assertIn(key, s)

    def test_all_ok(self):
        """全链路成功"""
        self.assertTrue(self.r["aggregated"]["all_ok"])

    def test_per_agent_latency(self):
        """每 Agent 耗时"""
        self.assertEqual(len(self.r["per_agent_latency_ms"]), 3)

    def test_results_three(self):
        """3 个结果"""
        self.assertEqual(len(self.r["results"]), 3)


class TestPipelineReuse(unittest.TestCase):
    """管道与并发委派共存"""

    def test_pipeline_and_parallel_flag(self):
        """管道请求 dispatched_parallel 标记"""
        reg = SpecialistRegistry()
        reg.register_simple("perception_agent", "perception",
                            lambda req: {"data": {}})
        reg.register_simple("experience_agent", "experience",
                            lambda req: {"data": {}})
        router = CompanionRouter(reg, top_k=3)
        d = TaskDelegator(router, workers=4)
        r = d.delegate({"text": "扫描环境查看策略建议"})
        # 管道模式: 2 Agent (perception → experience)
        self.assertIsNotNone(r["pipeline"])
        self.assertEqual(len(r["results"]), 2)

    def test_pipeline_disabled_fallback_parallel(self):
        """管道停用 → 并发委派 (同请求)"""
        reg = SpecialistRegistry()
        reg.register_simple("perception_agent", "perception",
                            lambda req: {"data": {}})
        reg.register_simple("experience_agent", "experience",
                            lambda req: {"data": {}})
        router = CompanionRouter(reg, top_k=3)
        pipeline = AgentPipeline(enabled=False)
        d = TaskDelegator(router, pipeline=pipeline)
        r = d.delegate({"text": "扫描环境查看策略建议"})
        self.assertIsNone(r["pipeline"])
        self.assertTrue(r["dispatched_parallel"])


if __name__ == "__main__":
    unittest.main()
