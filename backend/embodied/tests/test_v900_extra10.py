"""
YHLZ Embodied AI V9.0 - 研究引擎补充测试 10 (V9.0 Extra10)

覆盖 (生成式批量 + 服务回归):
    - 知识获取记录矩阵
    - 服务回归矩阵
    - 稳定性矩阵
"""
import unittest

from backend.embodied.companion.research_engine import (
    KnowledgeAcquisition,
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


# ── 知识获取记录矩阵 ────────────────────────────────────────────
_ACQUIRE_SEQ_CASES = [1, 2, 4, 8]


class TestGeneratedAcquireSeq(unittest.TestCase):
    """生成式: 获取序列"""
    pass


for _i, _n in enumerate(_ACQUIRE_SEQ_CASES):
    def _make(n=_n):
        def test(self):
            acq = KnowledgeAcquisition()
            for j in range(n):
                acq.acquire(f"问题{j}", "local")
            stats = acq.stats()
            self.assertEqual(stats["record_count"], n)
            self.assertEqual(stats["by_source"]["local"], n)
        test.__name__ = f"test_acqseq_{_i}"
        test.__doc__ = f"获取序列 {_n}"
        return test
    setattr(TestGeneratedAcquireSeq,
            _make().__name__, _make())


# ── 服务回归矩阵 ────────────────────────────────────────────────
class TestServiceRegression(unittest.TestCase):
    """服务回归"""

    def test_old_api_compat(self):
        svc = setup_service()
        # V8.5 创造
        r = svc.companion_meta_creative_stats()
        self.assertIn("create_count", r)
        # V8.0 宪法
        r = svc.companion_constitution_review({
            "module": "m", "action_text": "正常",
            "change": {},
        })
        self.assertEqual(r["decision"], "allow")
        # V7.0 表达
        r = svc.companion_presence_update("success")
        self.assertEqual(r["expression"], "高兴")
        # V6.8 HIL
        r = svc.companion_hybrid_route(
            {"type": "identity_query"},
        )
        self.assertEqual(r["route"], "LOCAL")

    def test_handle_still_works(self):
        svc = setup_service()
        r = svc.companion.handle({"text": "hi"})
        self.assertIn("personality", r)

    def test_creative_feeds_from_research(self):
        svc = setup_service()
        seed_observations(svc)
        svc.companion_research_explore("提升体验")
        stats = svc.companion_meta_creative.stats()
        self.assertGreaterEqual(
            stats["graph"]["node_count"], 1)


# ── 稳定性矩阵 ──────────────────────────────────────────────────
class TestStability(unittest.TestCase):
    """稳定性"""

    def test_many_explores(self):
        engine = ResearchEngine()
        engine.observe("user_need", "需求")
        for _ in range(10):
            r = engine.explore("提升体验")
            self.assertFalse(r["blocked"])

    def test_mixed_operations(self):
        engine = ResearchEngine()
        engine.observe("user_need", "需求")
        for _ in range(5):
            engine.explore("提升体验")
            engine.observe("knowledge_gap", "新缺口")
        stats = engine.stats()
        self.assertEqual(stats["explore_count"], 5)
        self.assertGreaterEqual(
            stats["observation"]["observation_count"], 6)

    def test_repeat_same_goal(self):
        engine = ResearchEngine()
        engine.observe("user_need", "需求")
        results = []
        for _ in range(3):
            r = engine.explore("同一个目标")
            self.assertFalse(r["blocked"])
            results.append(len(r["results"]))
        self.assertGreaterEqual(min(results), 1)


# ── 引擎最终矩阵 ────────────────────────────────────────────────
class TestEngineFinal(unittest.TestCase):
    """引擎最终"""

    def test_clear_then_reuse(self):
        engine = ResearchEngine()
        engine.observe("user_need", "需求")
        engine.explore("目标")
        engine.clear()
        engine.observe("user_need", "新需求")
        r = engine.explore("新目标")
        self.assertFalse(r["blocked"])

    def test_stats_mode(self):
        engine = ResearchEngine()
        self.assertEqual(engine.stats()["mode"],
                         "rule_based")

    def test_audit_full_record(self):
        engine = ResearchEngine()
        engine.observe("user_need", "需求")
        engine.explore("目标")
        report = engine.audit_report(limit=0)
        entry = report["recent"][0]
        for key in ("audit_id", "time", "question",
                    "source", "method", "result",
                    "validation"):
            self.assertIn(key, entry)


if __name__ == "__main__":
    unittest.main()
