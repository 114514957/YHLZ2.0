"""
YHLZ Embodied AI V9.5 - 元认知引擎补充测试 7 (V9.5 Extra7)

覆盖 (生成式批量 + 服务配置):
    - 验证全面矩阵
    - 服务配置矩阵
    - 反思统计矩阵
"""
import unittest

from backend.embodied.companion.meta_cognition import (
    MetaCognitionEngine,
    ReflectionLoop,
    SelfVerification,
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


# ── 验证全面矩阵 ────────────────────────────────────────────────
_VERIFY_FULL_CASES = [
    ("根据数据, 因此正确", "证据", "推理", 0.9, "fact"),
    ("结论", "根据数据", "", 0.6, "inference"),
    ("候选", "", "", 0.8, "hypothesis"),
    ("", "", "", 0.1, "uncertain"),
    ("推测", "", "因此", 0.4, "inference"),
    ("数据表明", "", "", 0.9, "inference"),
]


class TestGeneratedVerifyFull(unittest.TestCase):
    """生成式: 验证全面"""
    pass


for _i, (_conclusion, _evidence, _reasoning, _conf,
         _ctype) in enumerate(_VERIFY_FULL_CASES):
    def _make(conclusion=_conclusion, evidence=_evidence,
              reasoning=_reasoning, conf=_conf,
              ctype=_ctype):
        def test(self):
            r = SelfVerification().verify(
                conclusion, evidence, reasoning, conf,
            )
            self.assertEqual(r["conclusion_type"], ctype)
            self.assertEqual(r["ok"], ctype != "uncertain")
        test.__name__ = f"test_vfull_{_i}"
        test.__doc__ = f"验证全面 {_ctype}"
        return test
    setattr(TestGeneratedVerifyFull,
            _make().__name__, _make())


# ── 服务配置矩阵 ────────────────────────────────────────────────
class TestServiceConfig2(unittest.TestCase):
    """服务配置"""

    def test_enabled_default(self):
        svc = setup_service()
        engine = svc.companion_meta_cognition
        self.assertTrue(engine.stats()["enabled"])

    def test_disabled_monitor(self):
        svc = setup_service(
            companion_meta_cognition_enabled=False,
        )
        r = svc.companion_meta_cognition_monitor("任务")
        self.assertFalse(r["ok"])
        self.assertIn("停用", r["reason"])

    def test_constitution_link_on(self):
        svc = setup_service()
        self.assertIsNotNone(
            svc.companion_meta_cognition._constitution)

    def test_stats_shape(self):
        svc = setup_service()
        svc.companion_meta_cognition_monitor("任务")
        stats = svc.companion_meta_cognition_stats()
        for key in ("monitor", "evaluator", "detector",
                    "reflection", "verification", "memory",
                    "audit"):
            self.assertIn(key, stats)


# ── 反思统计矩阵 ────────────────────────────────────────────────
_REFLECT_STAT_CASES = [
    [("优化方法", True)],
    [("优化方法", True), ("修改使命", False)],
    [("优化方法", True), ("优化表达", True),
     ("修改使命", False)],
]


class TestGeneratedReflectStats(unittest.TestCase):
    """生成式: 反思统计"""
    pass


for _i, _entries in enumerate(_REFLECT_STAT_CASES):
    def _make(entries=_entries):
        def test(self):
            from backend.embodied.companion.constitution import (
                ConstitutionEngine,
            )
            loop = ReflectionLoop(
                constitution=ConstitutionEngine(),
            )
            for (adjustment, ok) in entries:
                loop.reflect("经验", "分析", adjustment)
            stats = loop.stats()
            self.assertEqual(stats["reflection_count"],
                             len(entries))
            self.assertEqual(
                stats["update_count"],
                sum(1 for _, ok in entries if ok))
        test.__name__ = f"test_reflectstats_{_i}"
        test.__doc__ = f"反思统计 {len(_entries)}"
        return test
    setattr(TestGeneratedReflectStats,
            _make().__name__, _make())


# ── 服务端到端矩阵 ──────────────────────────────────────────────
class TestServiceE2E2(unittest.TestCase):
    """服务端到端"""

    def test_full_flow_service(self):
        svc = setup_service()
        entry = svc.companion_meta_cognition_monitor(
            "任务", "deductive", 0.8,
        )
        r = svc.companion_meta_cognition_evaluate(
            entry, "根据数据",
        )
        self.assertIn("score", r)
        r = svc.companion_meta_cognition_detect_error(
            "记错了",
        )
        self.assertEqual(r["error_type"], "memory_error")
        r = svc.companion_meta_cognition_reflect(
            "经验", "分析", "优化记忆检索",
        )
        self.assertTrue(r["update"])
        r = svc.companion_meta_cognition_verify(
            "结论", evidence="根据数据",
        )
        self.assertTrue(r["ok"])

    def test_delusion_service(self):
        svc = setup_service()
        r = svc.companion_meta_cognition_reflect(
            "经验", "分析", "我掌控一切",
        )
        self.assertFalse(r["ok"])

    def test_audit_replay_service(self):
        svc = setup_service()
        svc.companion_meta_cognition_monitor("任务")
        replay = svc.companion_meta_cognition._audit\
            .replay()
        self.assertGreaterEqual(replay["replay_count"], 1)


# ── 引擎矩阵 ────────────────────────────────────────────────────
class TestEngineMatrix(unittest.TestCase):
    """引擎矩阵"""

    def test_clear_then_reuse(self):
        engine = MetaCognitionEngine()
        engine.monitor("任务")
        engine.clear()
        r = engine.monitor("新任务")
        self.assertIn("monitor_id", r)

    def test_memory_after_ops(self):
        engine = MetaCognitionEngine()
        engine.reflect("经验", "分析", "优化方法")
        r = engine.memory_save("经验", validated=True)
        self.assertEqual(r["category"],
                         "cognitive_experience")

    def test_operation_count_accumulate(self):
        engine = MetaCognitionEngine()
        engine.monitor("a")
        engine.monitor("b")
        engine.monitor("c")
        engine.monitor("d")
        self.assertEqual(engine.stats()[
            "operation_count"], 4)


if __name__ == "__main__":
    unittest.main()
