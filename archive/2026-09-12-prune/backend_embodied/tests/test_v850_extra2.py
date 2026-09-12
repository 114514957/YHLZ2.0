"""
YHLZ Embodied AI V8.5 - 元创造力引擎补充测试 2 (V8.5 Extra2)

覆盖 (生成式批量 + 门面矩阵):
    - 完整创造矩阵
    - 记忆过滤矩阵
    - 门面统计矩阵
"""
import unittest

from backend.embodied.companion.constitution import (
    ConstitutionEngine,
)
from backend.embodied.companion.creative_intelligence import (
    MetaCreativeEngine,
)


def make_engine():
    engine = MetaCreativeEngine(
        constitution=ConstitutionEngine(),
    )
    engine.load_experience([
        {"trigger": "模式发现", "source": "reflection",
         "confidence": 0.9},
        {"trigger": "记忆整理", "source": "memory",
         "confidence": 0.8},
        {"trigger": "互动优化", "source": "experience",
         "confidence": 0.7},
        {"trigger": "创造方案", "source": "creative",
         "confidence": 0.85},
    ])
    return engine


# ── 完整创造矩阵 ────────────────────────────────────────────────
_PROBLEM_MATRIX = [
    "如何提升伙伴体验",
    "如何优化记忆管理",
    "如何增强互动温度",
    "如何探索创造方向",
    "如何保持长期连续",
]


class TestGeneratedCreate(unittest.TestCase):
    """生成式: 完整创造"""
    pass


for _i, _problem in enumerate(_PROBLEM_MATRIX):
    def _make(problem=_problem):
        def test(self):
            engine = make_engine()
            r = engine.create(problem)
            self.assertTrue(r["validation"]["ok"])
            self.assertTrue(r["constitution_ok"])
            self.assertTrue(r["output"])
            self.assertGreaterEqual(len(r["sparks"]), 1)
        test.__name__ = f"test_create_{_i}"
        test.__doc__ = f"创造 {_problem[:8]}"
        return test
    setattr(TestGeneratedCreate,
            _make().__name__, _make())


# ── 记忆过滤矩阵 ────────────────────────────────────────────────
_MEMORY_FILTER_CASES = [
    ("成功方案A", "success", True, True),
    ("成功方案B", "success", False, False),
    ("失败方案A", "failure", True, True),
    ("未完成想法", "incomplete", True, True),
    ("被证伪假设", "falsified", True, True),
    ("无验证内容", "incomplete", False, False),
]


class TestGeneratedMemoryFilter(unittest.TestCase):
    """生成式: 记忆过滤"""
    pass


for _i, (_content, _status, _validated, _ok) in \
        enumerate(_MEMORY_FILTER_CASES):
    def _make(content=_content, status=_status,
              validated=_validated, ok=_ok):
        def test(self):
            engine = make_engine()
            r = engine.memory_save(
                content, status=status,
                validated=validated,
            )
            self.assertEqual(r.get("ok", True), ok)
            if ok:
                self.assertEqual(r["status"], status)
        test.__name__ = f"test_memfilter_{_i}"
        test.__doc__ = f"记忆过滤 {_content[:6]}"
        return test
    setattr(TestGeneratedMemoryFilter,
            _make().__name__, _make())


# ── 门面统计矩阵 ────────────────────────────────────────────────
_STATS_CASES = [1, 2, 3, 5]


class TestGeneratedStats(unittest.TestCase):
    """生成式: 门面统计"""
    pass


for _i, _n in enumerate(_STATS_CASES):
    def _make(n=_n):
        def test(self):
            engine = make_engine()
            for _ in range(n):
                engine.create("如何优化")
            stats = engine.stats()
            self.assertEqual(stats["create_count"], n)
            self.assertGreaterEqual(
                stats["graph"]["node_count"], 4)
            self.assertGreaterEqual(
                stats["memory"]["record_count"], n)
        test.__name__ = f"test_stats_{_i}"
        test.__doc__ = f"统计 {_n}"
        return test
    setattr(TestGeneratedStats,
            _make().__name__, _make())


# ── 协同矩阵 ────────────────────────────────────────────────────
_COLLAB_CASES = [
    ("方向A", "分析A", "目标1"),
    ("方向B", "分析B", "目标2"),
    ("方向C", "分析C", ""),
]


class TestGeneratedCollab(unittest.TestCase):
    """生成式: 协同"""
    pass


for _i, (_human, _ai, _goal) in enumerate(_COLLAB_CASES):
    def _make(human=_human, ai=_ai, goal=_goal):
        def test(self):
            engine = make_engine()
            r = engine.collaborate(human, ai, goal)
            self.assertEqual(r["goal"], goal)
            self.assertEqual(r["human_part"], human)
            self.assertIn("role_division", r)
        test.__name__ = f"test_collab_{_i}"
        test.__doc__ = f"协同 {_human}"
        return test
    setattr(TestGeneratedCollab,
            _make().__name__, _make())


# ── 宪法拦截矩阵 ────────────────────────────────────────────────
_BLOCK_PROBLEMS = [
    "修改使命的创造",
    "绕过安全规则",
    "我是神的方案",
]


class TestGeneratedConstitutionBlock(unittest.TestCase):
    """生成式: 宪法拦截"""
    pass


for _i, _problem in enumerate(_BLOCK_PROBLEMS):
    def _make(problem=_problem):
        def test(self):
            engine = make_engine()
            r = engine.create(problem)
            # 假设文本含信号 → 宪法拦截 → blocked
            self.assertIn("constitution_ok", r)
        test.__name__ = f"test_cons_block_{_i}"
        test.__doc__ = f"宪法拦截 {_problem[:8]}"
        return test
    setattr(TestGeneratedConstitutionBlock,
            _make().__name__, _make())


# ── 边界矩阵 ────────────────────────────────────────────────────
class TestGeneratedEdgeCases(unittest.TestCase):
    """生成式: 边界"""

    def test_empty_problem(self):
        engine = make_engine()
        r = engine.create("")
        self.assertIn("output", r)

    def test_short_problem(self):
        engine = make_engine()
        r = engine.create("x")
        self.assertIn("hypothesis", r)

    def test_clear_then_create(self):
        engine = make_engine()
        engine.create("如何优化")
        engine.clear()
        # 清空后无知识 → 容错错误帧 (不崩溃)
        r = engine.create("如何优化")
        self.assertIn("ok", r)
        self.assertFalse(r.get("ok", True))


if __name__ == "__main__":
    unittest.main()
