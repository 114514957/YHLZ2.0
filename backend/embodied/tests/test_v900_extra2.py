"""
YHLZ Embodied AI V9.0 - 研究引擎补充测试 2 (V9.0 Extra2)

覆盖 (生成式批量 + 门面矩阵):
    - 探索流程矩阵
    - 记忆过滤矩阵
    - 线程安全
"""
import threading
import unittest

from backend.embodied.companion.constitution import (
    ConstitutionEngine,
)
from backend.embodied.companion.research_engine import (
    ResearchEngine,
    ResearchMemory,
)


def make_engine(n=2):
    engine = ResearchEngine(
        constitution=ConstitutionEngine(),
    )
    for i in range(n):
        engine.observe("knowledge_gap", f"缺口{i}")
    engine.observe("user_need", "提升体验")
    return engine


# ── 探索流程矩阵 ────────────────────────────────────────────────
_GOAL_CASES = [
    "提升伙伴体验",
    "优化记忆管理",
    "增强互动温度",
    "探索创造方向",
]


class TestGeneratedExplore(unittest.TestCase):
    """生成式: 探索"""
    pass


for _i, _goal in enumerate(_GOAL_CASES):
    def _make(goal=_goal):
        def test(self):
            engine = make_engine()
            r = engine.explore(goal, "用户价值: 温暖")
            self.assertFalse(r["blocked"])
            self.assertGreaterEqual(len(r["results"]), 1)
            self.assertGreaterEqual(len(r["memories"]), 1)
        test.__name__ = f"test_explore_{_i}"
        test.__doc__ = f"探索 {_goal[:6]}"
        return test
    setattr(TestGeneratedExplore,
            _make().__name__, _make())


# ── 记忆过滤矩阵 ────────────────────────────────────────────────
_MEMORY_FILTER_CASES = [
    ("fact", True, True, True),
    ("fact", False, True, False),
    ("speculation", True, True, False),
    ("inference", True, False, False),
    ("evidence", True, True, True),
]


class TestGeneratedMemoryFilter(unittest.TestCase):
    """生成式: 记忆过滤"""
    pass


for _i, (_level, _validated, _constitution, _ok) in \
        enumerate(_MEMORY_FILTER_CASES):
    def _make(level=_level, validated=_validated,
              constitution=_constitution, ok=_ok):
        def test(self):
            memory = ResearchMemory()
            r = memory.save(
                "结论", "local", level=level,
                validated=validated,
                constitution_ok=constitution,
            )
            self.assertEqual(r.get("ok", True), ok)
        test.__name__ = f"test_memfilter_{_i}"
        test.__doc__ = f"记忆过滤 {_level}"
        return test
    setattr(TestGeneratedMemoryFilter,
            _make().__name__, _make())


# ── 观察批量矩阵 ────────────────────────────────────────────────
_GAP_CASES = [
    ["A"],
    ["A", "B"],
    ["A", "B", "C", "D"],
]


class TestGeneratedGaps(unittest.TestCase):
    """生成式: 缺口批量"""
    pass


for _i, _gaps in enumerate(_GAP_CASES):
    def _make(gaps=_gaps):
        def test(self):
            engine = ResearchEngine()
            n = engine.observe_gaps(gaps)
            self.assertEqual(n, len(gaps))
            stats = engine.stats()
            self.assertEqual(
                stats["observation"]["observation_count"],
                len(gaps))
        test.__name__ = f"test_gaps_{_i}"
        test.__doc__ = f"缺口 {len(_gaps)}"
        return test
    setattr(TestGeneratedGaps,
            _make().__name__, _make())


# ── 审计矩阵 ────────────────────────────────────────────────────
_AUDIT_SEQ_CASES = [1, 2, 3, 5]


class TestGeneratedAuditSeq(unittest.TestCase):
    """生成式: 审计序列"""
    pass


for _i, _n in enumerate(_AUDIT_SEQ_CASES):
    def _make(n=_n):
        def test(self):
            engine = make_engine()
            for _ in range(n):
                engine.explore("提升体验")
            report = engine.audit_report(limit=0)
            self.assertGreaterEqual(report["total"],
                                    n)
        test.__name__ = f"test_audit_seq_{_i}"
        test.__doc__ = f"审计序列 {_n}"
        return test
    setattr(TestGeneratedAuditSeq,
            _make().__name__, _make())


class TestThreadSafety(unittest.TestCase):
    """线程安全"""

    def test_concurrent_explore(self):
        engine = make_engine(4)
        errors = []

        def work():
            try:
                for _ in range(5):
                    engine.explore("提升体验")
            except Exception as e:  # pragma: no cover
                errors.append(e)

        threads = [threading.Thread(target=work)
                   for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        self.assertEqual(engine.stats()["explore_count"], 20)

    def test_concurrent_observe(self):
        engine = ResearchEngine()
        errors = []

        def work():
            try:
                for i in range(10):
                    engine.observe("knowledge_gap",
                                   f"缺口{i}")
            except Exception as e:  # pragma: no cover
                errors.append(e)

        threads = [threading.Thread(target=work)
                   for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        self.assertEqual(
            engine.stats()["observation"][
                "observation_count"], 40)


if __name__ == "__main__":
    unittest.main()
