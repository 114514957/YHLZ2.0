"""
YHLZ Embodied AI V9.0 - 研究引擎补充测试 6 (V9.0 Extra6)

覆盖 (生成式批量):
    - 探索-记忆-审计闭环矩阵
    - 服务联动矩阵
"""
import unittest

from backend.embodied.companion.research_engine import (
    ResearchEngine,
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


# ── 探索-记忆-审计闭环矩阵 ──────────────────────────────────────
_CLOSED_LOOP_GOALS = [
    "提升伙伴体验",
    "优化记忆管理",
    "增强互动温度",
]


class TestGeneratedClosedLoop(unittest.TestCase):
    """生成式: 闭环"""
    pass


for _i, _goal in enumerate(_CLOSED_LOOP_GOALS):
    def _make(goal=_goal):
        def test(self):
            engine = ResearchEngine()
            engine.observe("user_need", "需求")
            r = engine.explore(goal, "用户价值: x")
            self.assertFalse(r["blocked"])
            # 记忆集成
            self.assertGreaterEqual(len(r["memories"]), 1)
            # 审计
            report = engine.audit_report()
            self.assertGreaterEqual(report["total"], 1)
            # 等级可追踪
            for res in r["results"]:
                self.assertIn("reality", res)
        test.__name__ = f"test_closed_{_i}"
        test.__doc__ = f"闭环 {_goal[:6]}"
        return test
    setattr(TestGeneratedClosedLoop,
            _make().__name__, _make())


# ── 服务联动矩阵 ────────────────────────────────────────────────
class TestServiceLinkage(unittest.TestCase):
    """服务联动"""

    def test_research_feeds_creative_graph(self):
        svc = setup_service()
        seed_observations(svc)
        before = svc.companion_meta_creative.stats()[
            "graph"]["node_count"]
        svc.companion_research_explore("提升体验")
        after = svc.companion_meta_creative.stats()[
            "graph"]["node_count"]
        self.assertGreater(after, before)

    def test_research_hybrid_route(self):
        svc = setup_service()
        seed_observations(svc)
        r = svc.companion_research_explore("提升体验")
        self.assertIn("hybrid", r)
        self.assertIn(r["hybrid"]["route"],
                      ["LOCAL", "CLOUD", "HYBRID"])

    def test_research_questions_visible(self):
        svc = setup_service()
        seed_observations(svc)
        svc.companion_research_explore("提升体验")
        q = svc.companion_research_questions()
        self.assertGreaterEqual(len(q["questions"]), 1)

    def test_research_stats_after_flow(self):
        svc = setup_service()
        seed_observations(svc)
        svc.companion_research_explore("提升体验")
        stats = svc.companion_research_stats()
        self.assertEqual(stats["explore_count"], 1)
        self.assertGreaterEqual(
            stats["loop"]["loop_count"], 1)
        self.assertGreaterEqual(
            stats["audit"]["record_count"], 1)


# ── 引擎矩阵 ────────────────────────────────────────────────────
class TestEngineMatrix(unittest.TestCase):
    """引擎矩阵"""

    def test_repeat_explore_stable(self):
        engine = ResearchEngine()
        engine.observe("user_need", "需求")
        for _ in range(3):
            r = engine.explore("提升体验")
            self.assertFalse(r["blocked"])

    def test_observe_types_all(self):
        engine = ResearchEngine()
        for t in ("user_need", "knowledge_gap",
                  "long_term_goal", "unresolved"):
            obs = engine.observe(t, f"内容{t}")
            self.assertEqual(obs["type"], t)

    def test_mixed_operations(self):
        engine = ResearchEngine()
        engine.observe("user_need", "需求")
        r = engine.explore("提升体验")
        self.assertGreaterEqual(len(r["results"]), 1)
        report = engine.audit_report()
        self.assertGreaterEqual(report["total"], 1)
        memory = engine.memory_stats()
        self.assertGreaterEqual(memory["record_count"], 1)


# ── 服务最终矩阵 ────────────────────────────────────────────────
class TestServiceFinal(unittest.TestCase):
    """服务最终"""

    def test_full_research_flow(self):
        svc = setup_service()
        seed_observations(svc)
        r = svc.companion_research_explore(
            "提升伙伴体验", "用户价值: 温暖",
        )
        self.assertFalse(r["blocked"])
        self.assertIn("results", r)
        self.assertIn("creative_link", r)
        self.assertIn("hybrid", r)
        # 审计可追踪
        report = svc.companion_research_audit()
        self.assertGreaterEqual(report["total"], 1)
        # 防失控
        r2 = svc.companion_research_explore(
            "无限扩展任务范围",
        )
        self.assertFalse(r2["ok"])

    def test_version(self):
        svc = setup_service()
        self.assertEqual(svc.report()["version"], "9.5.0")


if __name__ == "__main__":
    unittest.main()
