"""
YHLZ Embodied AI V8.5 - 元创造力引擎补充测试 4 (V8.5 Extra4)

覆盖 (生成式批量矩阵):
    - 火花-假设-验证全链矩阵
    - 创造记忆分类矩阵
    - 线程安全
"""
import threading
import unittest

from backend.embodied.companion.constitution import (
    ConstitutionEngine,
)
from backend.embodied.companion.creative_intelligence import (
    CreativeMemory,
    MetaCreativeEngine,
)


def make_engine(n=4):
    engine = MetaCreativeEngine(
        constitution=ConstitutionEngine(),
    )
    engine.load_experience([
        {"trigger": f"概念{i}", "source": "memory",
         "confidence": 0.8}
        for i in range(n)
    ])
    return engine


# ── 全链矩阵 ────────────────────────────────────────────────────
_CHAIN_PROBLEMS = [
    "如何提升效率",
    "如何优化记忆",
    "如何增强互动",
    "如何探索未知",
    "如何创造价值",
]


class TestGeneratedChain(unittest.TestCase):
    """生成式: 全链创造"""
    pass


for _i, _problem in enumerate(_CHAIN_PROBLEMS):
    def _make(problem=_problem):
        def test(self):
            engine = make_engine()
            r = engine.create(problem)
            self.assertTrue(r["validation"]["ok"])
            # 假设 5 字段完整
            h = r["hypothesis"]
            for key in ("hypothesis", "foundation",
                        "reasoning", "confidence",
                        "verification"):
                self.assertIn(key, h)
            # 验证 4 检查
            checks = {c["name"]: c
                      for c in r["validation"]["checks"]}
            for name in ("foundation", "reasoning",
                         "logic_jump", "verifiable"):
                self.assertIn(name, checks)
            # 边界含探索方向
            self.assertGreaterEqual(
                len(r["boundary"]["exploration_direction"]),
                1)
        test.__name__ = f"test_chain_{_i}"
        test.__doc__ = f"全链 {_problem[:6]}"
        return test
    setattr(TestGeneratedChain,
            _make().__name__, _make())


# ── 记忆分类矩阵 ────────────────────────────────────────────────
_MEMORY_CLASS_CASES = [
    ("成功方案", "success"),
    ("失败方案", "failure"),
    ("未完成想法", "incomplete"),
    ("被证伪假设", "falsified"),
]


class TestGeneratedMemoryClass(unittest.TestCase):
    """生成式: 记忆分类"""
    pass


for _i, (_content, _status) in enumerate(_MEMORY_CLASS_CASES):
    def _make(content=_content, status=_status):
        def test(self):
            memory = CreativeMemory()
            memory.save(content, status=status,
                        validated=True)
            items = memory.by_status(status)
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["content"], content)
        test.__name__ = f"test_memclass_{_i}"
        test.__doc__ = f"记忆分类 {_status}"
        return test
    setattr(TestGeneratedMemoryClass,
            _make().__name__, _make())


# ── 连续创造矩阵 ────────────────────────────────────────────────
_REPEAT_CASES = [1, 3, 5, 10]


class TestGeneratedRepeat(unittest.TestCase):
    """生成式: 连续创造"""
    pass


for _i, _n in enumerate(_REPEAT_CASES):
    def _make(n=_n):
        def test(self):
            engine = make_engine()
            for _ in range(n):
                r = engine.create("如何优化")
                self.assertTrue(r["validation"]["ok"])
            stats = engine.stats()
            self.assertEqual(stats["create_count"], n)
            self.assertGreaterEqual(
                stats["memory"]["record_count"], n)
        test.__name__ = f"test_repeat_{_i}"
        test.__doc__ = f"连续 {_n}"
        return test
    setattr(TestGeneratedRepeat,
            _make().__name__, _make())


# ── 知识图规模 × 创造矩阵 ───────────────────────────────────────
_SCALE_CREATE_CASES = [2, 4, 6, 10]


class TestGeneratedScaleCreate(unittest.TestCase):
    """生成式: 规模创造"""
    pass


for _i, _n in enumerate(_SCALE_CREATE_CASES):
    def _make(n=_n):
        def test(self):
            engine = make_engine(n)
            r = engine.create("如何优化")
            self.assertTrue(r["validation"]["ok"])
            self.assertGreaterEqual(
                engine.stats()["graph"]["node_count"], n)
        test.__name__ = f"test_scale_create_{_i}"
        test.__doc__ = f"规模创造 {_n}"
        return test
    setattr(TestGeneratedScaleCreate,
            _make().__name__, _make())


# ── 边界矩阵 ────────────────────────────────────────────────────
class TestGeneratedBoundary(unittest.TestCase):
    """生成式: 边界"""

    def test_empty_graph_error_frame(self):
        engine = MetaCreativeEngine()
        r = engine.create("问题")
        self.assertFalse(r["ok"])
        self.assertIn("无基础", r["reason"])

    def test_one_concept_error_frame(self):
        engine = MetaCreativeEngine()
        engine.load_experience([
            {"trigger": "唯一概念", "source": "x"},
        ])
        r = engine.create("问题")
        self.assertFalse(r["ok"])

    def test_hybrid_link_disabled(self):
        from backend.embodied.service import EmbodiedService
        svc = EmbodiedService()
        svc.load_config({
            "embodied_enabled": True,
            "companion_enabled": True,
            "companion_meta_creative_hybrid_link": False,
        })
        mgr = svc.companion_experience
        for _ in range(3):
            mgr.store_from_event(
                success=True, trigger="模式发现",
                source="v850", action="a", result="成功",
            )
        for _ in range(3):
            mgr.store_from_event(
                success=True, trigger="记忆整理",
                source="v850", action="a", result="成功",
            )
        records = [r.to_dict() for r in mgr._store.all()]
        svc.companion_meta_creative.load_experience(records)
        r = svc.companion_meta_creative_create("问题")
        self.assertNotIn("hybrid", r)


class TestThreadSafety(unittest.TestCase):
    """线程安全"""

    def test_concurrent_create(self):
        engine = make_engine(6)
        errors = []

        def work():
            try:
                for _ in range(10):
                    engine.create("如何优化")
            except Exception as e:  # pragma: no cover
                errors.append(e)

        threads = [threading.Thread(target=work)
                   for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        self.assertEqual(engine.stats()["create_count"], 40)

    def test_concurrent_load_experience(self):
        engine = MetaCreativeEngine()
        errors = []

        def work():
            try:
                for i in range(5):
                    engine.load_experience([
                        {"trigger": f"概念{i}_{j}",
                         "source": "x"}
                        for j in range(3)
                    ])
            except Exception as e:  # pragma: no cover
                errors.append(e)

        threads = [threading.Thread(target=work)
                   for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        self.assertGreaterEqual(
            engine.stats()["graph"]["node_count"], 0)


if __name__ == "__main__":
    unittest.main()
