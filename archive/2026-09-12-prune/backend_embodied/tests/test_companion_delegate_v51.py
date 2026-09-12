"""
YHLZ Embodied AI V5.1 - 并发委派与超时控制单元测试 (Parallel Delegation & Timeout)

覆盖 (delegate.py V5.1):
    - 并发委派: 多 Agent 并行 (dispatched_parallel=True), 结果顺序稳定
    - 单 Agent: 顺序执行 (dispatched_parallel=False)
    - 超时控制: 慢 Agent 超时 → timeout 错误 (不阻塞整体)
    - 耗时统计: total_latency_ms / per_agent_latency_ms
    - 参数校验: workers/timeout <= 0 → DelegateError
    - 结果按路由顺序归位 (并发不乱序)
"""
import time
import unittest

from backend.embodied.companion import (
    DelegateError,
    CompanionRouter,
    SpecialistRegistry,
    TaskDelegator,
)


def ok_handler(request):
    return {"echo": request.get("text", "")}


def slow_handler(request):
    time.sleep(0.2)
    return {"done": True}


def make_delegator(workers=4, timeout=10.0, agents=None, slow=False):
    reg = SpecialistRegistry()
    for name, cap in (agents or [
        ("perception_agent", "perception"),
        ("reasoning_agent", "reasoning"),
        ("experience_agent", "experience"),
        ("long_horizon_agent", "long_horizon"),
    ]):
        reg.register_simple(name, cap, slow_handler if slow else ok_handler)
    router = CompanionRouter(reg)
    return TaskDelegator(router, timeout=timeout, workers=workers)


class TestParallelDelegation(unittest.TestCase):
    """并发委派"""

    def test_parallel_flag_multi(self):
        """多 Agent → dispatched_parallel=True"""
        d = make_delegator()
        r = d.delegate({"text": "扫描并整理"})
        self.assertTrue(r["dispatched_parallel"])
        self.assertGreaterEqual(len(r["assigned_agents"]), 2)

    def test_sequential_flag_single(self):
        """单 Agent → dispatched_parallel=False"""
        d = make_delegator()
        r = d.delegate({"text": "扫描"})
        self.assertFalse(r["dispatched_parallel"])
        self.assertEqual(len(r["assigned_agents"]), 1)

    def test_results_ordered(self):
        """并发结果按路由顺序归位"""
        d = make_delegator()
        r = d.delegate({"text": "扫描并整理"})
        assigned = r["assigned_agents"]
        result_agents = [x["agent"] for x in r["results"]]
        self.assertEqual(result_agents, assigned)

    def test_parallel_results_ok(self):
        """并发全部成功"""
        d = make_delegator()
        r = d.delegate({"text": "扫描并整理"})
        self.assertTrue(r["aggregated"]["all_ok"])
        self.assertEqual(r["aggregated"]["ok_count"],
                         r["aggregated"]["total"])

    def test_parallel_latency_measured(self):
        """总耗时与每 Agent 耗时"""
        d = make_delegator()
        r = d.delegate({"text": "扫描并整理"})
        self.assertGreaterEqual(r["total_latency_ms"], 0)
        self.assertEqual(len(r["per_agent_latency_ms"]),
                         len(r["assigned_agents"]))
        self.assertTrue(all("latency_ms" in x
                            for x in r["per_agent_latency_ms"]))

    def test_parallel_faster_than_sequential(self):
        """并发总耗时 < 串行总耗时 (慢 Agent)"""
        d = make_delegator(slow=True)  # 4 个 Agent 各 0.2s
        r = d.delegate({"text": "扫描并整理规划治理"})
        # 并发下总耗时应远小于 4×0.2=0.8s
        self.assertLess(r["total_latency_ms"], 700)

    def test_explainable_parallel(self):
        """原因含执行模式 (V5.2: 管道或并行)"""
        d = make_delegator()
        r = d.delegate({"text": "扫描并整理"})
        reason = r["explainable_reason"]
        self.assertTrue("并行" in reason or "管道" in reason)
        self.assertIn("总耗时", reason)

    def test_single_latency(self):
        """单 Agent 耗时在 reason"""
        d = make_delegator()
        r = d.delegate({"text": "扫描"})
        self.assertIn("ms", r["explainable_reason"])


class TestTimeout(unittest.TestCase):
    """超时控制"""

    def test_timeout_marks_error(self):
        """超时 → 错误标记 (不阻塞整体)"""
        d = make_delegator(timeout=0.05, slow=True)
        r = d.delegate({"text": "扫描"})
        self.assertEqual(len(r["results"]), 1)
        self.assertFalse(r["results"][0]["ok"])
        self.assertIn("超时", r["results"][0]["error"])

    def test_timeout_partial(self):
        """部分超时: 快 Agent 成功 + 慢 Agent 超时"""
        reg = SpecialistRegistry()
        reg.register_simple("fast", "perception", ok_handler)
        reg.register_simple("slow", "long_horizon", slow_handler)
        router = CompanionRouter(reg)
        d = TaskDelegator(router, timeout=0.05, workers=2)
        r = d.delegate({"text": "扫描并整理"})
        by_agent = {x["agent"]: x for x in r["results"]}
        self.assertTrue(by_agent["fast"]["ok"])
        self.assertFalse(by_agent["slow"]["ok"])
        self.assertIn("超时", by_agent["slow"]["error"])

    def test_no_timeout_normal(self):
        """正常速度不超时"""
        d = make_delegator(timeout=5.0)
        r = d.delegate({"text": "扫描"})
        self.assertTrue(r["results"][0]["ok"])

    def test_timeout_reason_marked(self):
        """超时 Agent 在汇总标记失败"""
        d = make_delegator(timeout=0.05, slow=True)
        r = d.delegate({"text": "扫描"})
        agg = r["aggregated"]
        self.assertEqual(agg["fail_count"], 1)
        self.assertEqual(agg["ok_count"], 0)


class TestValidation(unittest.TestCase):
    """参数校验"""

    def test_invalid_workers_raises(self):
        """workers <= 0 → DelegateError"""
        reg = SpecialistRegistry()
        router = CompanionRouter(reg)
        with self.assertRaises(DelegateError):
            TaskDelegator(router, workers=0)

    def test_invalid_timeout_raises(self):
        """timeout <= 0 → DelegateError"""
        reg = SpecialistRegistry()
        router = CompanionRouter(reg)
        with self.assertRaises(DelegateError):
            TaskDelegator(router, timeout=0)

    def test_thresholds_include_workers(self):
        """阈值含 workers"""
        d = make_delegator(workers=3)
        th = d.thresholds()
        self.assertEqual(th["workers"], 3)
        self.assertEqual(th["timeout"], 10.0)

    def test_shutdown(self):
        """关闭线程池不报错"""
        d = make_delegator()
        d.delegate({"text": "扫描"})
        d.shutdown()


if __name__ == "__main__":
    unittest.main()
