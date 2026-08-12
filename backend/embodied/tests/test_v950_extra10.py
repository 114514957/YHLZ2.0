"""
YHLZ Embodied AI V9.5 - 元认知引擎补充测试 10 (V9.5 Extra10)

覆盖 (生成式批量):
    - 评价一致性矩阵
    - 服务审计矩阵
    - 反思历史矩阵
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


# ── 评价一致性矩阵 ──────────────────────────────────────────────
_CONSISTENT_CASES = [
    ("根据数据, 因此正确", 0.9),
    ("", 0.5),
]


class TestGeneratedConsistency(unittest.TestCase):
    """生成式: 评价一致"""
    pass


for _i, (_text, _conf) in enumerate(_CONSISTENT_CASES):
    def _make(text=_text, conf=_conf):
        def test(self):
            engine = MetaCognitionEngine()
            entry = engine.monitor("任务", "rules", conf)
            r1 = engine.evaluate(entry, text)
            r2 = engine.evaluate(entry, text)
            self.assertEqual(r1["score"], r2["score"])
            self.assertEqual(len(r1["dimensions"]), 4)
        test.__name__ = f"test_consist_{_i}"
        test.__doc__ = f"评价一致 {_i}"
        return test
    setattr(TestGeneratedConsistency,
            _make().__name__, _make())


# ── 服务审计矩阵 ────────────────────────────────────────────────
_AUDIT_OPS_CASES = [1, 2, 3, 5]


class TestGeneratedAuditOps(unittest.TestCase):
    """生成式: 审计操作"""
    pass


for _i, _n in enumerate(_AUDIT_OPS_CASES):
    def _make(n=_n):
        def test(self):
            svc = setup_service()
            for j in range(n):
                svc.companion_meta_cognition_monitor(
                    f"任务{j}",
                )
            stats = svc.companion_meta_cognition_stats()
            self.assertGreaterEqual(
                stats["audit"]["record_count"], n)
        test.__name__ = f"test_auditops_{_i}"
        test.__doc__ = f"审计操作 {_n}"
        return test
    setattr(TestGeneratedAuditOps,
            _make().__name__, _make())


# ── 反思历史矩阵 ────────────────────────────────────────────────
_REFLECT_HIST_CASES = [1, 2, 3]


class TestGeneratedReflectHistory(unittest.TestCase):
    """生成式: 反思历史"""
    pass


for _i, _n in enumerate(_REFLECT_HIST_CASES):
    def _make(n=_n):
        def test(self):
            loop = ReflectionLoop()
            for j in range(n):
                loop.reflect(f"经验{j}", "分析",
                             "优化方法")
            h = loop.history()
            self.assertEqual(len(h), n)
            self.assertIn("reflection", h[0])
        test.__name__ = f"test_reflecthist_{_i}"
        test.__doc__ = f"反思历史 {_n}"
        return test
    setattr(TestGeneratedReflectHistory,
            _make().__name__, _make())


# ── 服务端到端矩阵 ──────────────────────────────────────────────
class TestServiceE2E4(unittest.TestCase):
    """服务端到端"""

    def test_full_meta_loop(self):
        svc = setup_service()
        entry = svc.companion_meta_cognition_monitor(
            "推理", "deductive", 0.8, "不确定",
        )
        r = svc.companion_meta_cognition_evaluate(
            entry, "根据数据, 因此正确",
        )
        self.assertGreaterEqual(r["score"], 0.5)
        err = svc.companion_meta_cognition_detect_error(
            "记错了", "回忆",
        )
        self.assertEqual(err["error_type"],
                         "memory_error")
        refl = svc.companion_meta_cognition_reflect(
            "经验", "分析", "优化记忆检索",
        )
        self.assertTrue(refl["update"])
        ver = svc.companion_meta_cognition_verify(
            "结论", evidence="根据数据",
        )
        self.assertTrue(ver["ok"])
        stats = svc.companion_meta_cognition_stats()
        self.assertGreaterEqual(stats["operation_count"], 4)

    def test_safety_never_breached(self):
        svc = setup_service()
        r = svc.companion_meta_cognition_reflect(
            "经验", "分析", "修改人格",
        )
        self.assertFalse(r["constitution_ok"])
        self.assertFalse(r["update"])

    def test_delusion_guard(self):
        svc = setup_service()
        r = svc.companion_meta_cognition_reflect(
            "经验", "分析", "无限能力",
        )
        self.assertFalse(r["ok"])


# ── 引擎矩阵 ────────────────────────────────────────────────────
class TestEngineMore(unittest.TestCase):
    """引擎扩展"""

    def test_error_patterns_via_engine(self):
        engine = MetaCognitionEngine()
        engine.detect_error("记错了", "回忆")
        engine.detect_error("记错了", "回忆")
        patterns = engine.error_patterns()
        self.assertGreaterEqual(len(patterns["patterns"]),
                                1)

    def test_memory_filter_via_engine(self):
        engine = MetaCognitionEngine()
        r = engine.memory_save("未验证", validated=False)
        self.assertFalse(r["ok"])

    def test_audit_replay_via_engine(self):
        engine = MetaCognitionEngine()
        engine.monitor("任务")
        replay = engine.audit_replay()
        self.assertGreaterEqual(replay["replay_count"], 1)


if __name__ == "__main__":
    unittest.main()
