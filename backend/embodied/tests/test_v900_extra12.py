"""
YHLZ Embodied AI V9.0 - 研究引擎补充测试 12 (V9.0 Extra12)

覆盖 (生成式批量):
    - 知识等级全面矩阵
    - 观察容量矩阵
    - 服务配置矩阵
"""
import unittest

from backend.embodied.companion.research_engine import (
    ObservationLayer,
    RealityValidation,
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


# ── 知识等级全面矩阵 ────────────────────────────────────────────
_FULL_REALITY_CASES = [
    ("根据数据, 证据显示", "local", 0.9, "fact"),
    ("根据来源", "local", 0.9, "evidence"),
    ("因此推断", "unknown", 0.3, "inference"),
    ("候选假设", "unknown", 0.3, "hypothesis"),
    ("", "unknown", 0.0, "speculation"),
    ("数据表明", "unknown", 0.7, "fact"),
    ("来源记录", "user_authorized", 0.85, "evidence"),
]


class TestGeneratedFullReality(unittest.TestCase):
    """生成式: 等级全面"""
    pass


for _i, (_text, _source, _rel, _level) in \
        enumerate(_FULL_REALITY_CASES):
    def _make(text=_text, source=_source, rel=_rel,
              level=_level):
        def test(self):
            r = RealityValidation().validate(
                text, source, reliability=rel,
            )
            self.assertEqual(r["level"], level)
        test.__name__ = f"test_full_reality_{_i}"
        test.__doc__ = f"等级全面 {_level}"
        return test
    setattr(TestGeneratedFullReality,
            _make().__name__, _make())


# ── 观察容量矩阵 ────────────────────────────────────────────────
_CAP_OBS_CASES = [1, 3, 10, 50]


class TestGeneratedObsCap(unittest.TestCase):
    """生成式: 观察容量"""
    pass


for _i, _cap in enumerate(_CAP_OBS_CASES):
    def _make(cap=_cap):
        def test(self):
            layer = ObservationLayer(max_records=cap)
            for j in range(cap * 2):
                layer.observe("user_need", f"内容{j}")
            self.assertEqual(layer.stats()[
                "observation_count"], cap)
        test.__name__ = f"test_obscap_{_i}"
        test.__doc__ = f"观察容量 {_cap}"
        return test
    setattr(TestGeneratedObsCap,
            _make().__name__, _make())


# ── 服务配置矩阵 ────────────────────────────────────────────────
class TestServiceConfig2(unittest.TestCase):
    """服务配置"""

    def test_loops_config_effect(self):
        svc = setup_service(
            companion_research_max_loops=1,
        )
        svc.companion_research_observe(
            "knowledge_gap", "缺口A",
        )
        svc.companion_research_observe(
            "knowledge_gap", "缺口B",
        )
        r = svc.companion_research_explore("目标")
        self.assertLessEqual(len(r["results"]), 1)

    def test_constitution_link_on(self):
        svc = setup_service()
        self.assertIsNotNone(
            svc.companion_research._constitution)

    def test_stats_all_sections(self):
        svc = setup_service()
        svc.companion_research_observe(
            "user_need", "需求",
        )
        svc.companion_research_explore("目标")
        stats = svc.companion_research_stats()
        self.assertEqual(stats["explore_count"], 1)
        self.assertIn("runaway_block_count", stats)
        self.assertIn("blocked_count", stats)


# ── 探索矩阵 ────────────────────────────────────────────────────
class TestExploreVariants(unittest.TestCase):
    """探索变体"""

    def test_explore_single_question(self):
        engine = __import__(
            "backend.embodied.companion.research_engine",
            fromlist=["ResearchEngine"],
        ).ResearchEngine()
        engine.observe("user_need", "唯一需求")
        r = engine.explore("目标")
        self.assertEqual(len(r["results"]), 1)

    def test_explore_question_order(self):
        from backend.embodied.companion.research_engine import (
            ResearchEngine,
        )
        engine = ResearchEngine()
        engine.observe("knowledge_gap", "低优先级")
        engine.observe("user_need", "高优先级")
        r = engine.explore("目标")
        q = r["questions"][0]
        self.assertIn("高优先级", q["question"])

    def test_explore_blocked_count(self):
        from backend.embodied.companion.research_engine import (
            ResearchEngine,
        )
        engine = ResearchEngine()
        engine.explore("自定义终极目标: x")
        stats = engine.stats()
        self.assertEqual(stats["blocked_count"], 1)


if __name__ == "__main__":
    unittest.main()
