"""
YHLZ Embodied AI V9.0 - 研究引擎补充测试 14 (V9.0 Extra14)

覆盖 (生成式批量):
    - 服务矩阵
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


# ── 服务矩阵 ────────────────────────────────────────────────────
_SVC_GOALS = [
    "提升伙伴体验",
    "优化记忆管理",
    "增强互动温度",
    "探索创造方向",
]


class TestGeneratedSvcGoals(unittest.TestCase):
    """生成式: 服务目标"""
    pass


for _i, _goal in enumerate(_SVC_GOALS):
    def _make(goal=_goal):
        def test(self):
            svc = setup_service()
            svc.companion_research_observe(
                "user_need", goal, "user",
            )
            r = svc.companion_research_explore(
                goal, "用户价值: x",
            )
            self.assertFalse(r["blocked"])
            self.assertGreaterEqual(len(r["results"]), 1)
        test.__name__ = f"test_svcgoals_{_i}"
        test.__doc__ = f"服务目标 {_goal[:6]}"
        return test
    setattr(TestGeneratedSvcGoals,
            _make().__name__, _make())


# ── 引擎矩阵 ────────────────────────────────────────────────────
class TestEngineMore(unittest.TestCase):
    """引擎扩展"""

    def test_explore_after_clear(self):
        engine = ResearchEngine()
        engine.observe("user_need", "需求")
        engine.explore("目标")
        engine.clear()
        engine.observe("user_need", "新需求")
        r = engine.explore("新目标")
        self.assertFalse(r["blocked"])

    def test_questions_accumulate(self):
        engine = ResearchEngine()
        engine.observe("user_need", "需求1")
        engine.explore("目标1")
        engine.observe("knowledge_gap", "缺口2")
        engine.explore("目标2")
        q = engine.questions()
        self.assertGreaterEqual(len(q["questions"]), 1)

    def test_audit_accumulates(self):
        engine = ResearchEngine()
        engine.observe("user_need", "需求")
        engine.explore("目标1")
        engine.explore("目标2")
        report = engine.audit_report(limit=0)
        self.assertGreaterEqual(report["total"], 2)


# ── 观察矩阵 ────────────────────────────────────────────────────
class TestObserveMore(unittest.TestCase):
    """观察扩展"""

    def test_observe_after_explore(self):
        engine = ResearchEngine()
        engine.observe("user_need", "需求")
        engine.explore("目标")
        obs = engine.observe("knowledge_gap", "新缺口")
        self.assertEqual(obs["type"], "knowledge_gap")

    def test_observe_source_recorded(self):
        engine = ResearchEngine()
        obs = engine.observe("user_need", "需求",
                             "user_profile")
        self.assertEqual(obs["source"], "user_profile")

    def test_observations_all(self):
        engine = ResearchEngine()
        engine.observe("user_need", "a")
        engine.observe("user_need", "b")
        obs = engine._observation.observations()
        self.assertEqual(len(obs), 2)


# ── 稳定性矩阵 ──────────────────────────────────────────────────
class TestStability2(unittest.TestCase):
    """稳定性"""

    def test_ten_explores_stable(self):
        engine = ResearchEngine()
        engine.observe("user_need", "需求")
        for _ in range(10):
            r = engine.explore("目标")
            self.assertFalse(r["blocked"])
        self.assertEqual(engine.stats()["explore_count"], 10)

    def test_mixed_ops_no_error(self):
        engine = ResearchEngine()
        for i in range(5):
            engine.observe("user_need", f"需求{i}")
            engine.explore(f"目标{i}")
            engine.explore("自定义终极目标: x")
        stats = engine.stats()
        self.assertEqual(stats["explore_count"], 5)
        self.assertGreaterEqual(stats["blocked_count"], 5)


if __name__ == "__main__":
    unittest.main()
