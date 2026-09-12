"""
YHLZ Embodied AI V9.5 - 元认知引擎补充测试 12 (V9.5 Extra12)

覆盖 (生成式批量):
    - 服务矩阵
    - 反思扩展矩阵
"""
import unittest

from backend.embodied.companion.meta_cognition import (
    MetaCognitionEngine,
    ReflectionLoop,
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


# ── 服务矩阵 ────────────────────────────────────────────────────
_SVC_TASK_CASES = [
    "推理任务A",
    "记忆检索B",
    "互动决策C",
    "创造方案D",
    "研究任务E",
]


class TestGeneratedSvcTasks(unittest.TestCase):
    """生成式: 服务任务"""
    pass


for _i, _task in enumerate(_SVC_TASK_CASES):
    def _make(task=_task):
        def test(self):
            svc = setup_service()
            entry = svc.companion_meta_cognition_monitor(
                task, "deductive", 0.8,
            )
            self.assertEqual(entry["task"], task)
            r = svc.companion_meta_cognition_evaluate(
                entry, "根据数据, 因此正确",
            )
            self.assertGreaterEqual(r["score"], 0.5)
        test.__name__ = f"test_svctask_{_i}"
        test.__doc__ = f"服务任务 {_task[:6]}"
        return test
    setattr(TestGeneratedSvcTasks,
            _make().__name__, _make())


# ── 反思扩展矩阵 ────────────────────────────────────────────────
_REFLECT_EXT_CASES = [
    ("优化记忆检索", True),
    ("优化表达方式", True),
    ("优化创造流程", True),
    ("优化研究步骤", True),
    ("改进输出格式", True),
]


class TestGeneratedReflectExt(unittest.TestCase):
    """生成式: 反思扩展"""
    pass


for _i, (_adjustment, _ok) in enumerate(_REFLECT_EXT_CASES):
    def _make(adjustment=_adjustment, ok=_ok):
        def test(self):
            loop = ReflectionLoop()
            r = loop.reflect("经验", "分析", adjustment)
            self.assertEqual(r["validation"]["ok"], ok)
            self.assertEqual(r["update"], ok)
        test.__name__ = f"test_reflectext_{_i}"
        test.__doc__ = f"反思扩展 {_adjustment[:6]}"
        return test
    setattr(TestGeneratedReflectExt,
            _make().__name__, _make())


# ── 服务稳定矩阵 ────────────────────────────────────────────────
class TestServiceStable(unittest.TestCase):
    """服务稳定"""

    def test_repeat_monitor(self):
        svc = setup_service()
        for _ in range(10):
            r = svc.companion_meta_cognition_monitor("任务")
            self.assertIn("monitor_id", r)
        stats = svc.companion_meta_cognition_stats()
        self.assertEqual(stats["operation_count"], 10)

    def test_mixed_ops_stable(self):
        svc = setup_service()
        for i in range(5):
            svc.companion_meta_cognition_monitor(f"t{i}")
            svc.companion_meta_cognition_detect_error(
                "记错了", f"t{i}",
            )
            svc.companion_meta_cognition_verify(
                f"结论{i}", evidence="e",
            )
        stats = svc.companion_meta_cognition_stats()
        self.assertEqual(stats["operation_count"], 15)

    def test_stats_after_clear(self):
        svc = setup_service()
        svc.companion_meta_cognition_monitor("任务")
        svc.companion_meta_cognition.clear()
        stats = svc.companion_meta_cognition_stats()
        self.assertEqual(stats["operation_count"], 0)


# ── 引擎最终矩阵 ────────────────────────────────────────────────
class TestEngineMatrix2(unittest.TestCase):
    """引擎矩阵"""

    def test_error_patterns_after_many(self):
        engine = MetaCognitionEngine()
        for _ in range(3):
            engine.detect_error("记错了", "回忆")
        patterns = engine.error_patterns()
        self.assertEqual(
            patterns["patterns"][0]["occurrences"], 3)

    def test_memory_categories(self):
        engine = MetaCognitionEngine()
        for cat in ("cognitive_experience", "error_case",
                    "optimization_strategy"):
            r = engine.memory_save(
                f"内容_{cat}", cat, validated=True,
            )
            self.assertEqual(r["category"], cat)

    def test_audit_by_error(self):
        engine = MetaCognitionEngine()
        engine.detect_error("记错了")
        engine.detect_error("逻辑矛盾")
        report = engine.audit_report()
        self.assertIn("by_error", report)


if __name__ == "__main__":
    unittest.main()
