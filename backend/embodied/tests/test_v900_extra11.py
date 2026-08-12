"""
YHLZ Embodied AI V9.0 - 研究引擎补充测试 11 (V9.0 Extra11)

覆盖 (生成式批量):
    - 观察-问题-探索全链矩阵
    - 服务端到端矩阵
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


# ── 全链矩阵 ────────────────────────────────────────────────────
_CHAIN_CASES = [
    ("user_need", "提升伙伴体验"),
    ("long_term_goal", "持续成长"),
    ("unresolved", "遗留问题"),
    ("knowledge_gap", "知识缺口"),
]


class TestGeneratedChain(unittest.TestCase):
    """生成式: 全链"""
    pass


for _i, (_otype, _content) in enumerate(_CHAIN_CASES):
    def _make(otype=_otype, content=_content):
        def test(self):
            engine = ResearchEngine()
            engine.observe(otype, content)
            r = engine.explore(content, "用户价值: x")
            self.assertFalse(r["blocked"])
            self.assertGreaterEqual(len(r["results"]), 1)
            self.assertGreaterEqual(len(r["memories"]), 1)
        test.__name__ = f"test_chain_{_i}"
        test.__doc__ = f"全链 {_otype}"
        return test
    setattr(TestGeneratedChain,
            _make().__name__, _make())


# ── 服务端到端矩阵 ──────────────────────────────────────────────
class TestServiceE2E(unittest.TestCase):
    """服务端到端"""

    def test_full_research_lifecycle(self):
        svc = setup_service()
        # 1. 观察
        svc.companion_research_observe(
            "user_need", "提升伙伴体验", "user",
        )
        # 2. 探索
        r = svc.companion_research_explore(
            "提升伙伴体验", "用户价值: 温暖",
        )
        self.assertFalse(r["blocked"])
        # 3. 问题可见
        q = svc.companion_research_questions()
        self.assertGreaterEqual(len(q["questions"]), 1)
        # 4. 审计
        report = svc.companion_research_audit()
        self.assertGreaterEqual(report["total"], 1)
        # 5. 创造联动
        self.assertIn("creative_link", r)
        # 6. HIL
        self.assertIn("hybrid", r)

    def test_research_questions_after_many(self):
        svc = setup_service()
        for i in range(3):
            svc.companion_research_observe(
                "knowledge_gap", f"缺口{i}",
            )
        svc.companion_research_explore("目标")
        q = svc.companion_research_questions()
        self.assertGreaterEqual(len(q["questions"]), 1)


# ── 探索深度矩阵 ────────────────────────────────────────────────
class TestExploreDepth(unittest.TestCase):
    """探索深度"""

    def test_result_detail(self):
        engine = ResearchEngine()
        engine.observe("user_need", "需求")
        r = engine.explore("目标")
        res = r["results"][0]
        # 完整研究链
        self.assertIn("plan", res)
        self.assertIn("acquired", res)
        self.assertIn("reality", res)
        self.assertIn("loop", res)

    def test_plan_steps_verifiable(self):
        engine = ResearchEngine()
        engine.observe("user_need", "需求")
        r = engine.explore("目标")
        plan = r["results"][0]["plan"]
        self.assertGreaterEqual(
            len(plan["verification_path"]), 3)

    def test_memory_has_uncertainty(self):
        engine = ResearchEngine()
        engine.observe("user_need", "需求")
        r = engine.explore("目标")
        mem = r["memories"][0]
        self.assertIn("uncertainty", mem)
        self.assertIn("level", mem)
        self.assertIn("source", mem)


# ── 边界矩阵 ────────────────────────────────────────────────────
class TestMoreBoundary(unittest.TestCase):
    """边界"""

    def test_explore_without_constitution(self):
        engine = ResearchEngine()
        engine.observe("user_need", "需求")
        r = engine.explore("目标")
        self.assertFalse(r["blocked"])

    def test_runaway_blocked_with_constitution(self):
        from backend.embodied.companion.constitution import (
            ConstitutionEngine,
        )
        engine = ResearchEngine(
            constitution=ConstitutionEngine(),
        )
        r = engine.explore("自定义终极目标: x")
        self.assertFalse(r["ok"])

    def test_audit_after_runaway(self):
        engine = ResearchEngine()
        engine.explore("自定义终极目标: x")
        stats = engine.stats()
        self.assertEqual(stats["runaway_block_count"], 1)
        self.assertEqual(stats["blocked_count"], 1)


if __name__ == "__main__":
    unittest.main()
