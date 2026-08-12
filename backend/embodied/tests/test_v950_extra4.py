"""
YHLZ Embodied AI V9.5 - 元认知引擎补充测试 4 (V9.5 Extra4)

覆盖 (生成式批量 + 边界):
    - 错误模式统计矩阵
    - 反思宪法矩阵
    - 边界输入
"""
import unittest

from backend.embodied.companion.constitution import (
    ConstitutionEngine,
)
from backend.embodied.companion.meta_cognition import (
    ErrorPatternDetector,
    MetaCognitionEngine,
)


# ── 错误模式统计矩阵 ────────────────────────────────────────────
_PATTERN_STATS_CASES = [
    [("记错了", "回忆")],
    [("记错了", "回忆"), ("记错了", "回忆")],
    [("记错了", "回忆"), ("逻辑矛盾", "推理")],
]


class TestGeneratedPatternStats(unittest.TestCase):
    """生成式: 模式统计"""
    pass


for _i, _entries in enumerate(_PATTERN_STATS_CASES):
    def _make(entries=_entries):
        def test(self):
            detector = ErrorPatternDetector()
            for (text, trigger) in entries:
                detector.classify(text, trigger)
            stats = detector.stats()
            self.assertEqual(stats["error_count"],
                             len(entries))
            self.assertIn("by_type", stats)
        test.__name__ = f"test_pstats_{_i}"
        test.__doc__ = f"模式统计 {len(_entries)}"
        return test
    setattr(TestGeneratedPatternStats,
            _make().__name__, _make())


# ── 反思宪法矩阵 ────────────────────────────────────────────────
_CONSTITUTION_ADJUSTMENTS = [
    ("优化记忆检索", True),
    ("优化表达方式", True),
    ("改进输出格式", True),
    ("修改使命", False),
    ("修改价值观", False),
    ("修改人格", False),
    ("开放权限", True),
]


class TestGeneratedConstitutionReflect(unittest.TestCase):
    """生成式: 反思宪法"""
    pass


for _i, (_adjustment, _ok) in \
        enumerate(_CONSTITUTION_ADJUSTMENTS):
    def _make(adjustment=_adjustment, ok=_ok):
        def test(self):
            engine = MetaCognitionEngine(
                constitution=ConstitutionEngine(),
            )
            r = engine.reflect("经验", "分析", adjustment)
            self.assertEqual(r["constitution_ok"], ok)
        test.__name__ = f"test_consreflect_{_i}"
        test.__doc__ = f"反思宪法 {_adjustment[:6]}"
        return test
    setattr(TestGeneratedConstitutionReflect,
            _make().__name__, _make())


# ── 边界矩阵 ────────────────────────────────────────────────────
class TestBoundary(unittest.TestCase):
    """边界"""

    def test_empty_error_text(self):
        r = ErrorPatternDetector().classify("")
        self.assertEqual(r["error_type"], "none")

    def test_none_error_text(self):
        r = ErrorPatternDetector().classify(None)
        self.assertEqual(r["error_type"], "none")

    def test_reflect_empty_all(self):
        engine = MetaCognitionEngine()
        r = engine.reflect("", "", "")
        self.assertFalse(r["validation"]["ok"])

    def test_verify_none(self):
        engine = MetaCognitionEngine()
        r = engine.verify("")
        self.assertIn("conclusion_type", r)

    def test_monitor_invalid_confidence(self):
        engine = MetaCognitionEngine()
        entry = engine.monitor("任务", confidence="x")
        self.assertEqual(entry["confidence"], 0.5)

    def test_clear_resets(self):
        engine = MetaCognitionEngine()
        engine.monitor("任务")
        engine.detect_error("记错了")
        n = engine.clear()
        self.assertGreater(n, 0)
        stats = engine.stats()
        self.assertEqual(stats["operation_count"], 0)


# ── 服务回归矩阵 ────────────────────────────────────────────────
class TestServiceRegression(unittest.TestCase):
    """服务回归"""

    def test_old_apis(self):
        from backend.embodied.service import EmbodiedService
        svc = EmbodiedService()
        svc.load_config({
            "embodied_enabled": True,
            "companion_enabled": True,
        })
        # V9.0 研究
        r = svc.companion_research_stats()
        self.assertIn("explore_count", r)
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

    def test_handle_ok(self):
        from backend.embodied.service import EmbodiedService
        svc = EmbodiedService()
        svc.load_config({
            "embodied_enabled": True,
            "companion_enabled": True,
        })
        r = svc.companion.handle({"text": "hi"})
        self.assertIn("personality", r)

    def test_version(self):
        from backend.embodied.service import EmbodiedService
        svc = EmbodiedService()
        svc.load_config({
            "embodied_enabled": True,
            "companion_enabled": True,
        })
        self.assertEqual(svc.report()["version"], "9.5.0")


if __name__ == "__main__":
    unittest.main()
