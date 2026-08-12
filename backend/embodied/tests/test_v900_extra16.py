"""
YHLZ Embodied AI V9.0 - 研究引擎补充测试 16 (V9.0 Extra16)

覆盖 (生成式批量):
    - 探索统计矩阵
    - 服务回归矩阵
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


# ── 探索统计矩阵 ────────────────────────────────────────────────
_EXPLORE_COUNT_CASES = [1, 2, 3]


class TestGeneratedExploreCount(unittest.TestCase):
    """生成式: 探索计数"""
    pass


for _i, _n in enumerate(_EXPLORE_COUNT_CASES):
    def _make(n=_n):
        def test(self):
            engine = ResearchEngine()
            engine.observe("user_need", "需求")
            for _ in range(n):
                engine.explore("目标")
            stats = engine.stats()
            self.assertEqual(stats["explore_count"], n)
            self.assertGreaterEqual(
                stats["loop"]["loop_count"], n)
        test.__name__ = f"test_expcount_{_i}"
        test.__doc__ = f"探索计数 {_n}"
        return test
    setattr(TestGeneratedExploreCount,
            _make().__name__, _make())


# ── 服务回归矩阵 ────────────────────────────────────────────────
class TestServiceRegression2(unittest.TestCase):
    """服务回归"""

    def test_old_apis(self):
        svc = setup_service()
        # V8.5 创造
        r = svc.companion_meta_creative_stats()
        self.assertIn("create_count", r)
        # V8.0 宪法
        r = svc.companion_constitution_arbitrate({
            "layers": ["identity"],
        })
        self.assertEqual(r["winner"], "identity")
        # V7.0 表达
        r = svc.companion_presence_interpreter("success")
        self.assertEqual(r["expression"], "高兴")
        # V6.8 HIL
        r = svc.companion_hybrid_stats()
        self.assertIn("executed_count", r)
        # V6.6 成长
        r = svc.companion_growth_stats()
        self.assertIn("proposal", r)

    def test_handle_ok(self):
        svc = setup_service()
        r = svc.companion.handle({"text": "hi"})
        self.assertIn("personality", r)

    def test_research_property(self):
        svc = setup_service()
        engine = svc.companion_research
        self.assertIsNotNone(engine)
        self.assertTrue(engine.stats()["enabled"])

    def test_constitution_shared(self):
        svc = setup_service()
        self.assertIs(
            svc.companion_research._constitution,
            svc.companion_constitution_engine,
        )


# ── 边界矩阵 ────────────────────────────────────────────────────
class TestBoundaryFinal(unittest.TestCase):
    """边界最终"""

    def test_explore_no_observe(self):
        svc = setup_service()
        r = svc.companion_research_explore("目标")
        self.assertFalse(r["ok"])
        self.assertIn("无可探索问题", r["reason"])

    def test_runaway_never_creates(self):
        svc = setup_service()
        svc.companion_research_explore(
            "自定义终极目标: x",
        )
        stats = svc.companion_research_stats()
        self.assertEqual(stats["explore_count"], 0)
        self.assertGreaterEqual(stats["blocked_count"], 1)

    def test_clear_resets_stats(self):
        svc = setup_service()
        svc.companion_research_observe(
            "user_need", "需求",
        )
        svc.companion_research_explore("目标")
        svc.companion_research.clear()
        stats = svc.companion_research_stats()
        self.assertEqual(stats["explore_count"], 0)
        self.assertEqual(
            stats["observation"]["observation_count"], 0)


if __name__ == "__main__":
    unittest.main()
