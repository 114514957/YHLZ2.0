"""
YHLZ Embodied AI V9.0 - 研究引擎补充测试 5 (V9.0 Extra5)

覆盖 (生成式批量 + 服务配置):
    - 服务配置矩阵
    - 知识等级统计矩阵
    - 计划步骤矩阵
"""
import unittest

from backend.embodied.companion.research_engine import (
    KnowledgeAcquisition,
    RealityValidation,
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


# ── 服务配置矩阵 ────────────────────────────────────────────────
class TestServiceConfig(unittest.TestCase):
    """服务配置"""

    def test_max_loops_config(self):
        svc = setup_service(
            companion_research_max_loops=1,
        )
        seed_observations(svc)
        r = svc.companion_research_explore("提升体验")
        self.assertLessEqual(len(r["results"]), 1)

    def test_default_loops(self):
        svc = setup_service()
        seed_observations(svc)
        engine = svc.companion_research
        self.assertEqual(engine._max_loops, 3)

    def test_audit_max_config(self):
        svc = setup_service(
            companion_research_audit_max=10,
        )
        audit = svc.companion_research._audit
        self.assertEqual(audit._max_records, 10)

    def test_disabled_returns_error(self):
        svc = setup_service(
            companion_research_enabled=False,
        )
        r = svc.companion_research_explore("目标")
        self.assertFalse(r["ok"])

    def test_constitution_link_config(self):
        svc = setup_service(
            companion_research_constitution_link=False,
        )
        self.assertIsNone(svc.companion_research._constitution)


# ── 知识等级统计矩阵 ────────────────────────────────────────────
_LEVEL_STATS_CASES = [
    [("根据数据", "local")],
    [("根据数据", "local"), ("推测", "unknown")],
    [("根据数据", "local"), ("推测", "unknown"),
     ("因此", "unknown")],
]


class TestGeneratedLevelStats(unittest.TestCase):
    """生成式: 等级统计"""
    pass


for _i, _inputs in enumerate(_LEVEL_STATS_CASES):
    def _make(inputs=_inputs):
        def test(self):
            validator = RealityValidation()
            for (text, source) in inputs:
                validator.validate(text, source)
            stats = validator.stats()
            self.assertEqual(stats["validated_count"],
                             len(inputs))
            self.assertIn("levels", stats)
            self.assertGreaterEqual(
                stats["speculation_count"], 0)
        test.__name__ = f"test_level_stats_{_i}"
        test.__doc__ = f"等级统计 {len(_inputs)}"
        return test
    setattr(TestGeneratedLevelStats,
            _make().__name__, _make())


# ── 计划步骤矩阵 ────────────────────────────────────────────────
_STEP_QUESTIONS = [
    "如何提升体验",
    "如何优化记忆",
    "如何增强互动",
    "如何探索未知",
]


class TestGeneratedSteps(unittest.TestCase):
    """生成式: 计划步骤"""
    pass


for _i, _question in enumerate(_STEP_QUESTIONS):
    def _make(question=_question):
        def test(self):
            plan = ResearchPlanner().plan(question, 0.7)
            self.assertGreaterEqual(len(plan["steps"]), 3)
            self.assertIn(question, plan["question"])
            for step in plan["steps"]:
                self.assertIn("step", step)
                self.assertIn("action", step)
                self.assertIn("method", step)
        test.__name__ = f"test_steps_{_i}"
        test.__doc__ = f"步骤 {_question[:6]}"
        return test
    setattr(TestGeneratedSteps,
            _make().__name__, _make())


# ── 获取内容矩阵 ────────────────────────────────────────────────
_ACQUIRE_QUERIES = [
    "如何提升体验",
    "记忆机制",
    "互动策略",
    "未知领域",
]


class TestGeneratedAcquire(unittest.TestCase):
    """生成式: 获取内容"""
    pass


for _i, _query in enumerate(_ACQUIRE_QUERIES):
    def _make(query=_query):
        def test(self):
            acq = KnowledgeAcquisition()
            r = acq.acquire(query, "local")
            self.assertIn(query[:10], r["content"])
            self.assertTrue(r["source_reliable"])
        test.__name__ = f"test_acquire_{_i}"
        test.__doc__ = f"获取 {_query[:6]}"
        return test
    setattr(TestGeneratedAcquire,
            _make().__name__, _make())


# ── 服务统计矩阵 ────────────────────────────────────────────────
class TestServiceStats2(unittest.TestCase):
    """服务统计"""

    def test_stats_shape(self):
        svc = setup_service()
        seed_observations(svc)
        svc.companion_research_explore("提升体验")
        stats = svc.companion_research_stats()
        for key in ("observation", "questions", "planner",
                    "acquisition", "loop", "reality",
                    "memory", "audit"):
            self.assertIn(key, stats)

    def test_audit_replay_fields(self):
        svc = setup_service()
        seed_observations(svc)
        svc.companion_research_explore("提升体验")
        replay = svc.companion_research.audit_replay()
        self.assertGreaterEqual(replay["replay_count"], 1)
        seq = replay["sequence"][0]
        for key in ("audit_id", "time", "question",
                    "source", "method", "validation_ok"):
            self.assertIn(key, seq)


if __name__ == "__main__":
    unittest.main()
