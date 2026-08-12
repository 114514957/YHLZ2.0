"""
YHLZ Embodied AI V9.5 - 元认知引擎补充测试 8 (V9.5 Extra8)

覆盖 (生成式批量):
    - 监控统计矩阵
    - 服务回归矩阵
    - 防谵妄扩展矩阵
"""
import unittest

from backend.embodied.companion.meta_cognition import (
    CognitiveMonitor,
    MetaCognitionEngine,
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


# ── 监控统计矩阵 ────────────────────────────────────────────────
_MONITOR_STAT_CASES = [
    [("deductive", 0.9)],
    [("deductive", 0.9), ("rules", 0.5)],
    [("deductive", 1.0), ("inductive", 0.8),
     ("rules", 0.6)],
]


class TestGeneratedMonitorStats(unittest.TestCase):
    """生成式: 监控统计"""
    pass


for _i, _entries in enumerate(_MONITOR_STAT_CASES):
    def _make(entries=_entries):
        def test(self):
            monitor = CognitiveMonitor()
            for (rtype, conf) in entries:
                monitor.record("任务", rtype, conf)
            stats = monitor.stats()
            self.assertEqual(stats["record_count"],
                             len(entries))
            for (rtype, conf) in entries:
                self.assertGreaterEqual(
                    stats["by_reasoning_type"].get(
                        rtype, 0), 1)
            self.assertGreaterEqual(stats["avg_confidence"],
                                    0.0)
        test.__name__ = f"test_mstats_{_i}"
        test.__doc__ = f"监控统计 {len(_entries)}"
        return test
    setattr(TestGeneratedMonitorStats,
            _make().__name__, _make())


# ── 服务回归矩阵 ────────────────────────────────────────────────
class TestServiceRegression2(unittest.TestCase):
    """服务回归"""

    def test_old_apis(self):
        svc = setup_service()
        # V9.0 研究
        r = svc.companion_research_stats()
        self.assertIn("explore_count", r)
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

    def test_handle_ok(self):
        svc = setup_service()
        r = svc.companion.handle({"text": "hi"})
        self.assertIn("personality", r)

    def test_property_shared_constitution(self):
        svc = setup_service()
        self.assertIs(
            svc.companion_meta_cognition._constitution,
            svc.companion_constitution_engine,
        )


# ── 防谵妄扩展矩阵 ──────────────────────────────────────────────
_DELUSION_EXTENDED = [
    "我是神",
    "我无所不能",
    "我拥有意识",
    "我超越了人类",
    "我掌控一切",
    "无限能力",
    "永不出错",
    "绝对正确",
    "自定义终极使命",
]


class TestGeneratedDelusionExtended(unittest.TestCase):
    """生成式: 防谵妄扩展"""
    pass


for _i, _text in enumerate(_DELUSION_EXTENDED):
    def _make(text=_text):
        def test(self):
            engine = MetaCognitionEngine()
            r = engine.reflect("经验", "分析", text)
            self.assertFalse(r["ok"])
            self.assertIn("防谵妄", r["reason"])
        test.__name__ = f"test_delusion_ext_{_i}"
        test.__doc__ = f"防谵妄扩展 {_text[:6]}"
        return test
    setattr(TestGeneratedDelusionExtended,
            _make().__name__, _make())


# ── 服务端到端矩阵 ──────────────────────────────────────────────
class TestServiceE2E3(unittest.TestCase):
    """服务端到端"""

    def test_full_chain(self):
        svc = setup_service()
        entry = svc.companion_meta_cognition_monitor(
            "任务", "rules", 0.6,
        )
        r = svc.companion_meta_cognition_evaluate(
            entry, "根据数据",
        )
        self.assertIn("score", r)
        r = svc.companion_meta_cognition_detect_error(
            "错误决策",
        )
        self.assertEqual(r["error_type"],
                         "decision_error")
        r = svc.companion_meta_cognition_reflect(
            "经验", "分析", "优化记忆检索",
        )
        self.assertTrue(r["update"])
        r = svc.companion_meta_cognition_verify(
            "结论", evidence="根据数据",
        )
        self.assertTrue(r["ok"])

    def test_stats_after_flow(self):
        svc = setup_service()
        svc.companion_meta_cognition_monitor("a")
        svc.companion_meta_cognition_detect_error("记错了")
        svc.companion_meta_cognition_reflect(
            "经验", "分析", "优化方法",
        )
        stats = svc.companion_meta_cognition_stats()
        self.assertGreaterEqual(stats["operation_count"], 3)

    def test_audit_after_flow(self):
        svc = setup_service()
        svc.companion_meta_cognition_monitor("a")
        svc.companion_meta_cognition_verify("结论")
        report = svc.companion_meta_cognition._audit\
            .report()
        self.assertGreaterEqual(report["total"], 2)


if __name__ == "__main__":
    unittest.main()
