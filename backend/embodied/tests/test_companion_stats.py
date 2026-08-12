"""
YHLZ Embodied AI V5.1 - 伙伴协同统计单元测试 (Companion Stats)

覆盖 (stats.py):
    - record: 委派记录 (组合/耗时/成功率/并行标记)
    - summary: 汇总 (总次数/成功率/平均耗时/并行比例/Top 组合/每 Agent)
    - 空统计: 全 0 默认
    - 环形上限: max_records 截断
    - 参数校验: max_records <= 0 → StatsError
    - 与 Main Agent 集成: handle 自动记录
"""
import unittest

from backend.embodied.companion import (
    CompanionStats,
    StatsError,
    CompanionRouter,
    SpecialistRegistry,
    TaskDelegator,
)


def ok_handler(request):
    return {"ok": True}


class TestCompanionStats(unittest.TestCase):
    """协同统计器"""

    def setUp(self):
        self.stats = CompanionStats(max_records=50)

    def test_record(self):
        """记录委派"""
        e = self.stats.record(["a", "b"], ok_count=2, total=2,
                              latency_ms=10.5, parallel=True)
        self.assertEqual(e["agents"], ["a", "b"])
        self.assertEqual(e["ok_count"], 2)
        self.assertEqual(e["latency_ms"], 10.5)
        self.assertTrue(e["parallel"])

    def test_summary_empty(self):
        """空统计全 0"""
        s = self.stats.summary()
        self.assertEqual(s["total_delegations"], 0)
        self.assertEqual(s["success_rate"], 0.0)
        self.assertEqual(s["avg_latency_ms"], 0.0)
        self.assertEqual(s["top_combinations"], [])
        self.assertEqual(s["per_agent"], {})
        self.assertEqual(s["mode"], "rule_based")

    def test_summary_counts(self):
        """汇总计数"""
        self.stats.record(["a"], ok_count=1, total=1, latency_ms=10.0)
        self.stats.record(["a", "b"], ok_count=2, total=2,
                          latency_ms=20.0, parallel=True)
        s = self.stats.summary()
        self.assertEqual(s["total_delegations"], 2)
        self.assertEqual(s["total_agents_invoked"], 3)
        self.assertEqual(s["success_rate"], 1.0)

    def test_summary_success_rate_partial(self):
        """部分成功率"""
        self.stats.record(["a"], ok_count=1, total=2, latency_ms=10.0)
        s = self.stats.summary()
        self.assertEqual(s["success_rate"], 0.5)

    def test_summary_avg_latency(self):
        """平均耗时"""
        self.stats.record(["a"], ok_count=1, total=1, latency_ms=10.0)
        self.stats.record(["a"], ok_count=1, total=1, latency_ms=30.0)
        s = self.stats.summary()
        self.assertEqual(s["avg_latency_ms"], 20.0)

    def test_parallel_ratio(self):
        """并行比例"""
        self.stats.record(["a"], ok_count=1, total=1, latency_ms=1.0)
        self.stats.record(["a", "b"], ok_count=2, total=2,
                          latency_ms=1.0, parallel=True)
        s = self.stats.summary()
        self.assertEqual(s["parallel_ratio"], 0.5)

    def test_top_combinations(self):
        """Top 组合 (按次数降序)"""
        self.stats.record(["a", "b"], ok_count=2, total=2, latency_ms=1.0)
        self.stats.record(["a", "b"], ok_count=2, total=2, latency_ms=1.0)
        self.stats.record(["c"], ok_count=1, total=1, latency_ms=1.0)
        s = self.stats.summary()
        self.assertEqual(s["top_combinations"][0]["count"], 2)
        self.assertEqual(set(s["top_combinations"][0]["agents"]),
                         {"a", "b"})

    def test_per_agent_stats(self):
        """每 Agent 统计"""
        self.stats.record(["a", "b"], ok_count=2, total=2, latency_ms=1.0)
        s = self.stats.summary()
        self.assertIn("a", s["per_agent"])
        self.assertIn("b", s["per_agent"])
        self.assertEqual(s["per_agent"]["a"]["invocations"], 1)

    def test_per_agent_success_rate(self):
        """每 Agent 成功率"""
        self.stats.record(["a", "b"], ok_count=1, total=2, latency_ms=1.0)
        self.stats.record(["a"], ok_count=1, total=1, latency_ms=1.0)
        s = self.stats.summary()
        self.assertGreaterEqual(s["per_agent"]["a"]["success_rate"], 0.5)

    def test_ring_limit(self):
        """环形上限截断"""
        stats = CompanionStats(max_records=3)
        for i in range(5):
            stats.record([f"a{i}"], ok_count=1, total=1, latency_ms=1.0)
        self.assertEqual(stats.count, 3)
        s = stats.summary()
        self.assertEqual(s["total_delegations"], 3)

    def test_clear(self):
        """清空"""
        self.stats.record(["a"], ok_count=1, total=1, latency_ms=1.0)
        self.assertEqual(self.stats.clear(), 1)
        self.assertEqual(self.stats.count, 0)

    def test_invalid_max_records(self):
        """max_records <= 0 → StatsError"""
        with self.assertRaises(StatsError):
            CompanionStats(max_records=0)

    def test_recent_listed(self):
        """近期记录"""
        self.stats.record(["a"], ok_count=1, total=1, latency_ms=1.0)
        s = self.stats.summary()
        self.assertEqual(len(s["recent"]), 1)

    def test_recent_newest_first(self):
        """近期记录最新在前"""
        self.stats.record(["a"], ok_count=1, total=1, latency_ms=1.0)
        self.stats.record(["b"], ok_count=1, total=1, latency_ms=1.0)
        s = self.stats.summary()
        self.assertEqual(s["recent"][0]["agents"], ["b"])

    def test_latency_rounding(self):
        """耗时保留 2 位小数"""
        e = self.stats.record(["a"], ok_count=1, total=1,
                              latency_ms=3.14159)
        self.assertEqual(e["latency_ms"], 3.14)

    def test_empty_agents_record(self):
        """空 Agent 组合记录不崩溃"""
        e = self.stats.record([], ok_count=0, total=0, latency_ms=1.0)
        self.assertEqual(e["agents"], [])
        s = self.stats.summary()
        self.assertEqual(s["total_delegations"], 1)


class TestStatsIntegration(unittest.TestCase):
    """与 Main Agent / Service 集成"""

    def test_handle_records_stats(self):
        """handle 自动记录统计"""
        from backend.embodied.companion import MainCompanionAgent
        reg = SpecialistRegistry()
        reg.register_simple("perception_agent", "perception", ok_handler)
        reg.register_simple("long_horizon_agent", "long_horizon", ok_handler)
        router = CompanionRouter(reg)
        delegator = TaskDelegator(router)
        stats = CompanionStats()
        agent = MainCompanionAgent(
            registry=reg, router=router, delegator=delegator,
            personality="铁哥们", stats=stats,
        )
        agent.handle({"text": "扫描并整理"})
        agent.handle({"text": "扫描"})
        s = agent.stats()
        self.assertEqual(s["total_delegations"], 2)
        self.assertGreater(s["total_agents_invoked"], 0)

    def test_service_stats_api(self):
        """Service companion_stats API"""
        from backend.embodied.service import EmbodiedService
        svc = EmbodiedService()
        svc.load_config({
            "embodied_enabled": True, "companion_enabled": True,
        })
        svc.companion_handle({"text": "扫描"})
        st = svc.companion_stats()
        self.assertEqual(st["total_delegations"], 1)
        self.assertEqual(st["mode"], "rule_based")

    def test_stats_after_failures(self):
        """失败委派计入统计"""
        from backend.embodied.companion import MainCompanionAgent

        def boom(request):
            raise RuntimeError("boom")

        reg = SpecialistRegistry()
        reg.register_simple("perception_agent", "perception", boom)
        router = CompanionRouter(reg)
        delegator = TaskDelegator(router)
        stats = CompanionStats()
        agent = MainCompanionAgent(
            registry=reg, router=router, delegator=delegator,
            personality="铁哥们", stats=stats,
        )
        agent.handle({"text": "扫描"})
        s = agent.stats()
        self.assertEqual(s["total_delegations"], 1)
        self.assertEqual(s["success_rate"], 0.0)


if __name__ == "__main__":
    unittest.main()
