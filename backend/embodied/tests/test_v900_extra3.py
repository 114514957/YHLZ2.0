"""
YHLZ Embodied AI V9.0 - 研究引擎补充测试 3 (V9.0 Extra3)

覆盖 (生成式批量 + 服务矩阵):
    - 服务探索矩阵
    - 知识获取来源矩阵
    - 计划成本矩阵
"""
import unittest

from backend.embodied.companion.research_engine import (
    KnowledgeAcquisition,
    ResearchPlanner,
)
from backend.embodied.service import EmbodiedService


def setup_service(**extra):
    cfg = {
        "embodied_enabled": True,
        "companion_enabled": True,
    }
    cfg.update(extra)
    svc = EmbodiedService()
    svc.load_config(cfg)
    return svc


def seed_observations(svc):
    svc.companion_research_observe(
        "user_need", "提升伙伴体验", "user")
    svc.companion_research_observe(
        "knowledge_gap", "记忆长期保持", "graph")


# ── 服务探索矩阵 ────────────────────────────────────────────────
_SERVICE_GOALS = [
    "提升伙伴体验",
    "优化记忆管理",
    "增强互动温度",
]


class TestGeneratedServiceGoals(unittest.TestCase):
    """生成式: 服务目标"""
    pass


for _i, _goal in enumerate(_SERVICE_GOALS):
    def _make(goal=_goal):
        def test(self):
            svc = setup_service()
            seed_observations(svc)
            r = svc.companion_research_explore(
                goal, "用户价值: 温暖",
            )
            self.assertFalse(r["blocked"])
            self.assertGreaterEqual(len(r["results"]), 1)
            self.assertIn("creative_link", r)
            self.assertIn("hybrid", r)
        test.__name__ = f"test_svc_goal_{_i}"
        test.__doc__ = f"服务目标 {_goal[:6]}"
        return test
    setattr(TestGeneratedServiceGoals,
            _make().__name__, _make())


# ── 知识获取来源矩阵 ────────────────────────────────────────────
_SOURCE_CASES = [
    ("local", True, 0.9),
    ("user_authorized", True, 0.85),
    ("cloud", True, 0.7),
    ("tool", True, 0.75),
    ("unknown", False, 0.0),
]


class TestGeneratedSources(unittest.TestCase):
    """生成式: 来源"""
    pass


for _i, (_source, _reliable, _rel) in \
        enumerate(_SOURCE_CASES):
    def _make(source=_source, reliable=_reliable,
              rel=_rel):
        def test(self):
            acq = KnowledgeAcquisition()
            r = acq.acquire("问题", source)
            self.assertEqual(r["source"], source)
            self.assertEqual(r["source_reliable"],
                             reliable)
            self.assertEqual(r["reliability"], rel)
        test.__name__ = f"test_source_{_i}"
        test.__doc__ = f"来源 {_source}"
        return test
    setattr(TestGeneratedSources,
            _make().__name__, _make())


# ── 计划成本矩阵 ────────────────────────────────────────────────
_COST_CASES = [
    (0.9, "high"),
    (0.8, "high"),
    (0.7, "medium"),
    (0.5, "medium"),
    (0.4, "low"),
    (0.1, "low"),
]


class TestGeneratedCosts(unittest.TestCase):
    """生成式: 计划成本"""
    pass


for _i, (_importance, _cost) in enumerate(_COST_CASES):
    def _make(importance=_importance, cost=_cost):
        def test(self):
            plan = ResearchPlanner().plan(
                "问题", importance,
            )
            self.assertEqual(plan["estimated_cost"], cost)
        test.__name__ = f"test_cost_{_i}"
        test.__doc__ = f"成本 {_importance}"
        return test
    setattr(TestGeneratedCosts,
            _make().__name__, _make())


# ── 资源规划矩阵 ────────────────────────────────────────────────
_RESOURCE_CASES = [
    (0.9, ["local", "user_authorized", "cloud", "tool"]),
    (0.6, ["local", "user_authorized", "cloud"]),
    (0.3, ["local", "user_authorized"]),
]


class TestGeneratedResources(unittest.TestCase):
    """生成式: 资源规划"""
    pass


for _i, (_importance, _resources) in \
        enumerate(_RESOURCE_CASES):
    def _make(importance=_importance,
              resources=_resources):
        def test(self):
            plan = ResearchPlanner().plan(
                "问题", importance,
            )
            self.assertEqual(plan["resources"],
                             resources)
        test.__name__ = f"test_res_{_i}"
        test.__doc__ = f"资源 {_importance}"
        return test
    setattr(TestGeneratedResources,
            _make().__name__, _make())


# ── 服务统计矩阵 ────────────────────────────────────────────────
class TestServiceStats(unittest.TestCase):
    """服务统计"""

    def test_stats_after_explores(self):
        svc = setup_service()
        seed_observations(svc)
        svc.companion_research_explore("提升体验")
        svc.companion_research_explore("提升体验")
        stats = svc.companion_research_stats()
        self.assertEqual(stats["explore_count"], 2)
        self.assertIn("observation", stats)
        self.assertIn("audit", stats)

    def test_audit_after_explore(self):
        svc = setup_service()
        seed_observations(svc)
        svc.companion_research_explore("提升体验")
        report = svc.companion_research_audit()
        self.assertGreaterEqual(report["total"], 1)
        self.assertIn("by_method", report)
        self.assertIn("by_source", report)

    def test_questions_after_explore(self):
        svc = setup_service()
        seed_observations(svc)
        svc.companion_research_explore("提升体验")
        q = svc.companion_research_questions()
        self.assertGreaterEqual(len(q["questions"]), 1)


if __name__ == "__main__":
    unittest.main()
