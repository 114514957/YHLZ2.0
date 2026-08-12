"""
YHLZ Embodied AI V8.5 - 元创造力引擎补充测试 14 (V8.5 Extra14)

覆盖 (生成式批量矩阵):
    - 知识图-创造闭环矩阵
    - 服务回归矩阵
"""
import unittest

from backend.embodied.companion.creative_intelligence import (
    MetaCreativeEngine,
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


def seed_and_load(svc):
    mgr = svc.companion_experience
    for trig in ("模式发现", "记忆整理"):
        for _ in range(2):
            mgr.store_from_event(
                success=True, trigger=trig,
                source="v850", action="a", result="成功",
            )
    records = [r.to_dict() for r in mgr._store.all()]
    svc.companion_meta_creative.load_experience(records)


# ── 知识图-创造闭环矩阵 ─────────────────────────────────────────
_LOOP_PROBLEMS = [
    "如何提升效率",
    "如何优化记忆",
    "如何增强互动",
    "如何探索未知",
]


class TestGeneratedLoopCreate(unittest.TestCase):
    """生成式: 闭环创造"""
    pass


for _i, _problem in enumerate(_LOOP_PROBLEMS):
    def _make(problem=_problem):
        def test(self):
            engine = MetaCreativeEngine()
            engine.load_experience([
                {"trigger": f"C{j}", "source": "x"}
                for j in range(5)
            ])
            r = engine.create(problem)
            self.assertTrue(r["validation"]["ok"])
            # 知识图有内容
            self.assertGreaterEqual(
                engine.stats()["graph"]["node_count"], 5)
            # 火花有依据
            for s in r["sparks"]:
                self.assertTrue(s["basis"])
        test.__name__ = f"test_loop_create_{_i}"
        test.__doc__ = f"闭环创造 {_problem[:6]}"
        return test
    setattr(TestGeneratedLoopCreate,
            _make().__name__, _make())


# ── 服务回归矩阵 ────────────────────────────────────────────────
class TestServiceRegression(unittest.TestCase):
    """服务回归"""

    def test_version_850(self):
        svc = setup_service()
        self.assertEqual(
            svc.report()["version"], "9.5.0")

    def test_old_api_compat(self):
        svc = setup_service()
        # V8.0 宪法 API
        r = svc.companion_constitution_review({
            "module": "m", "action_text": "正常",
            "change": {},
        })
        self.assertEqual(r["decision"], "allow")
        # V7.0 表达 API
        r = svc.companion_presence_update("success")
        self.assertEqual(r["expression"], "高兴")
        # V6.8 HIL API
        r = svc.companion_hybrid_route(
            {"type": "identity_query"},
        )
        self.assertEqual(r["route"], "LOCAL")
        # V6.6 成长 API
        r = svc.companion_growth_stats()
        self.assertIn("proposal", r)

    def test_handle_still_works(self):
        svc = setup_service()
        r = svc.companion.handle({"text": "hi"})
        self.assertIn("personality", r)
        self.assertIn("growth_cycle_check", r)

    def test_service_memory_filter(self):
        svc = setup_service()
        seed_and_load(svc)
        svc.companion_meta_creative.create("问题")
        r = svc.companion_meta_creative.memory_save(
            "新想法", status="incomplete", validated=True,
        )
        self.assertEqual(r["status"], "incomplete")
        stats = svc.companion_meta_creative.memory_stats()
        self.assertGreaterEqual(stats["record_count"], 2)


# ── 稳定矩阵 ────────────────────────────────────────────────────
class TestStability(unittest.TestCase):
    """稳定"""

    def test_many_creates_no_error(self):
        engine = MetaCreativeEngine()
        engine.load_experience([
            {"trigger": f"C{i}", "source": "x"}
            for i in range(6)
        ])
        for _ in range(20):
            r = engine.create("如何优化")
            self.assertTrue(r["validation"]["ok"])

    def test_mixed_operations(self):
        engine = MetaCreativeEngine()
        engine.load_experience([
            {"trigger": f"C{i}", "source": "x"}
            for i in range(4)
        ])
        for _ in range(5):
            engine.create("问题")
            engine.collaborate("人类", "AI")
            engine.memory_save("x", validated=True)
        stats = engine.stats()
        self.assertEqual(stats["create_count"], 5)
        self.assertGreaterEqual(
            stats["collaborative"]["collab_count"], 5)


if __name__ == "__main__":
    unittest.main()
