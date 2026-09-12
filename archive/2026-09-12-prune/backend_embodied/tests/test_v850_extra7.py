"""
YHLZ Embodied AI V8.5 - 元创造力引擎补充测试 7 (V8.5 Extra7)

覆盖 (生成式批量矩阵):
    - 创造输出矩阵
    - 验证拒绝矩阵
    - 服务规模矩阵
"""
import unittest

from backend.embodied.companion.creative_intelligence import (
    CreativeValidation,
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


def seed_and_load(svc, triggers=("模式发现", "记忆整理",
                                 "互动优化", "创造方向")):
    mgr = svc.companion_experience
    for trig in triggers:
        for _ in range(2):
            mgr.store_from_event(
                success=True, trigger=trig,
                source="v850", action="a", result="成功",
            )
    records = [r.to_dict() for r in mgr._store.all()]
    svc.companion_meta_creative.load_experience(records)


# ── 创造输出矩阵 ────────────────────────────────────────────────
_OUTPUT_PROBLEMS = [
    "如何让伙伴更有温度",
    "如何让记忆更持久",
    "如何让互动更自然",
    "如何让成长更稳健",
    "如何让创造更可验证",
]


class TestGeneratedOutputs(unittest.TestCase):
    """生成式: 创造输出"""
    pass


for _i, _problem in enumerate(_OUTPUT_PROBLEMS):
    def _make(problem=_problem):
        def test(self):
            engine = MetaCreativeEngine()
            engine.load_experience([
                {"trigger": f"概念{i}", "source": "x"}
                for i in range(4)
            ])
            r = engine.create(problem)
            self.assertTrue(r["validation"]["ok"])
            self.assertTrue(r["output"])
            self.assertTrue(r["hypothesis"]["verification"])
        test.__name__ = f"test_output_{_i}"
        test.__doc__ = f"输出 {_problem[:6]}"
        return test
    setattr(TestGeneratedOutputs,
            _make().__name__, _make())


# ── 验证拒绝矩阵 ────────────────────────────────────────────────
_REJECT_CASES = [
    ({"foundation": ""}, "foundation"),
    ({"reasoning": ""}, "reasoning"),
    ({"verification": ""}, "verifiable"),
    ({"reasoning": "毫无疑问正确"}, "logic_jump"),
]


class TestGeneratedRejects(unittest.TestCase):
    """生成式: 验证拒绝"""
    pass


for _i, (_over, _failed_check) in enumerate(_REJECT_CASES):
    def _make(over=_over, failed_check=_failed_check):
        def test(self):
            h = {
                "hypothesis": "x",
                "foundation": "有依据",
                "reasoning": "有推理",
                "verification": "有验证",
            }
            h.update(over)
            r = CreativeValidation().validate(h)
            self.assertFalse(r["ok"])
            failed = [
                c["name"] for c in r["checks"]
                if not c["passed"]
            ]
            self.assertIn(failed_check, failed)
        test.__name__ = f"test_reject_{_i}"
        test.__doc__ = f"拒绝 {_failed_check}"
        return test
    setattr(TestGeneratedRejects,
            _make().__name__, _make())


# ── 服务规模矩阵 ────────────────────────────────────────────────
_SERVICE_SCALE_CASES = [1, 2, 4, 8]


class TestGeneratedServiceScale(unittest.TestCase):
    """生成式: 服务规模"""
    pass


for _i, _n in enumerate(_SERVICE_SCALE_CASES):
    def _make(n=_n):
        def test(self):
            svc = setup_service()
            seed_and_load(svc)
            for _ in range(n):
                r = svc.companion_meta_creative_create(
                    "如何优化",
                )
                self.assertTrue(r["validation"]["ok"])
            stats = svc.companion_meta_creative_stats()
            self.assertEqual(stats["create_count"], n)
        test.__name__ = f"test_svc_scale_{_i}"
        test.__doc__ = f"服务规模 {_n}"
        return test
    setattr(TestGeneratedServiceScale,
            _make().__name__, _make())


# ── 知识图加载矩阵 ──────────────────────────────────────────────
_LOAD_CASES = [
    [{"trigger": "A"}],
    [{"trigger": "A"}, {"trigger": "B"}],
    [{"trigger": "A"}, {"trigger": "B"}, {"trigger": "C"}],
    [{"trigger": "A", "source": "x", "confidence": 0.9},
     {"trigger": "B", "source": "y", "confidence": 0.7}],
]


class TestGeneratedLoads(unittest.TestCase):
    """生成式: 知识图加载"""
    pass


for _i, _records in enumerate(_LOAD_CASES):
    def _make(records=_records):
        def test(self):
            engine = MetaCreativeEngine()
            n = engine.load_experience(records)
            self.assertEqual(n, len(records))
            self.assertEqual(
                engine.stats()["graph"]["node_count"],
                len(records))
        test.__name__ = f"test_load_{_i}"
        test.__doc__ = f"加载 {len(_records)}"
        return test
    setattr(TestGeneratedLoads,
            _make().__name__, _make())


# ── 边界矩阵 ────────────────────────────────────────────────────
class TestGeneratedMoreBoundary(unittest.TestCase):
    """生成式: 边界"""

    def test_duplicate_triggers_dedup(self):
        engine = MetaCreativeEngine()
        n = engine.load_experience([
            {"trigger": "A", "source": "x"},
            {"trigger": "A", "source": "y"},
        ])
        self.assertEqual(n, 2)
        # 同名概念去重 (更新)
        self.assertEqual(
            engine.stats()["graph"]["node_count"], 1)

    def test_long_problem(self):
        engine = MetaCreativeEngine()
        engine.load_experience([
            {"trigger": f"C{i}", "source": "x"}
            for i in range(4)
        ])
        r = engine.create("很长的" * 20)
        self.assertTrue(r["validation"]["ok"])


if __name__ == "__main__":
    unittest.main()
