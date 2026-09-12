"""
YHLZ Embodied AI V9.0 - 研究引擎补充测试 8 (V9.0 Extra8)

覆盖 (生成式批量 + 服务):
    - 服务探索重复矩阵
    - 知识等级边界矩阵
    - 审计容量矩阵
"""
import unittest

from backend.embodied.companion.research_engine import (
    RealityValidation,
    ResearchAudit,
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


# ── 服务探索重复矩阵 ────────────────────────────────────────────
_REPEAT_CASES = [1, 2, 3, 5]


class TestGeneratedServiceRepeat(unittest.TestCase):
    """生成式: 服务重复"""
    pass


for _i, _n in enumerate(_REPEAT_CASES):
    def _make(n=_n):
        def test(self):
            svc = setup_service()
            seed_observations(svc)
            for _ in range(n):
                r = svc.companion_research_explore(
                    "提升体验",
                )
                self.assertFalse(r["blocked"])
            stats = svc.companion_research_stats()
            self.assertEqual(stats["explore_count"], n)
        test.__name__ = f"test_svc_repeat_{_i}"
        test.__doc__ = f"服务重复 {_n}"
        return test
    setattr(TestGeneratedServiceRepeat,
            _make().__name__, _make())


# ── 知识等级边界矩阵 ────────────────────────────────────────────
_REALITY_EDGE_CASES = [
    ("", "", "speculation"),
    ("根据", "", "evidence"),
    ("数据", "unknown", "hypothesis"),
    ("因此", "unknown", "inference"),
    ("根据数据", "local", "fact"),
]


class TestGeneratedRealityEdge(unittest.TestCase):
    """生成式: 等级边界"""
    pass


for _i, (_text, _source, _level) in \
        enumerate(_REALITY_EDGE_CASES):
    def _make(text=_text, source=_source, level=_level):
        def test(self):
            r = RealityValidation().validate(text, source)
            self.assertEqual(r["level"], level)
        test.__name__ = f"test_redge_{_i}"
        test.__doc__ = f"等级边界 {_level}"
        return test
    setattr(TestGeneratedRealityEdge,
            _make().__name__, _make())


# ── 审计容量矩阵 ────────────────────────────────────────────────
_CAP_CASES = [1, 5, 20]


class TestGeneratedAuditCap(unittest.TestCase):
    """生成式: 审计容量"""
    pass


for _i, _cap in enumerate(_CAP_CASES):
    def _make(cap=_cap):
        def test(self):
            audit = ResearchAudit(max_records=cap)
            for j in range(cap * 2):
                audit.record(question=f"q{j}",
                             source="local",
                             method="loop")
            self.assertEqual(audit.stats()[
                "record_count"], cap)
        test.__name__ = f"test_audit_cap_{_i}"
        test.__doc__ = f"审计容量 {_cap}"
        return test
    setattr(TestGeneratedAuditCap,
            _make().__name__, _make())


# ── 引擎边界矩阵 ────────────────────────────────────────────────
class TestEngineBoundary(unittest.TestCase):
    """引擎边界"""

    def test_max_loops_respected(self):
        engine = ResearchEngine(max_loops_per_explore=1)
        for i in range(5):
            engine.observe("knowledge_gap", f"缺口{i}")
        r = engine.explore("目标")
        self.assertLessEqual(len(r["results"]), 1)

    def test_loop_limit_construct(self):
        with self.assertRaises(Exception):
            ResearchEngine(max_loops_per_explore=0)

    def test_audit_records_per_result(self):
        engine = ResearchEngine()
        engine.observe("user_need", "需求")
        engine.explore("目标")
        stats = engine.stats()["audit"]
        self.assertGreaterEqual(stats["record_count"], 1)


# ── 服务最终矩阵 ────────────────────────────────────────────────
class TestServiceFinal2(unittest.TestCase):
    """服务最终"""

    def test_research_stats_sections(self):
        svc = setup_service()
        seed_observations(svc)
        svc.companion_research_explore("提升体验")
        stats = svc.companion_research_stats()
        for key in ("observation", "questions", "planner",
                    "acquisition", "loop", "reality",
                    "memory", "audit"):
            self.assertIn(key, stats)

    def test_audit_after_flow(self):
        svc = setup_service()
        seed_observations(svc)
        svc.companion_research_explore("提升体验")
        report = svc.companion_research_audit(limit=0)
        self.assertGreaterEqual(report["total"], 1)
        self.assertIn("recent", report)


if __name__ == "__main__":
    unittest.main()
