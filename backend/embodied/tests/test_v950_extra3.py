"""
YHLZ Embodied AI V9.5 - 元认知引擎补充测试 3 (V9.5 Extra3)

覆盖 (生成式批量 + 服务矩阵):
    - 服务操作矩阵
    - 评价评分矩阵
    - 监控容量矩阵
"""
import unittest

from backend.embodied.companion.meta_cognition import (
    CognitiveMonitor,
    ReasoningEvaluator,
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


# ── 服务操作矩阵 ────────────────────────────────────────────────
_SVC_TASKS = [
    "推理任务",
    "记忆检索",
    "互动决策",
    "创造方案",
]


class TestGeneratedSvcOps(unittest.TestCase):
    """生成式: 服务操作"""
    pass


for _i, _task in enumerate(_SVC_TASKS):
    def _make(task=_task):
        def test(self):
            svc = setup_service()
            entry = svc.companion_meta_cognition_monitor(
                task, "rules", 0.7,
            )
            self.assertEqual(entry["task"], task)
            r = svc.companion_meta_cognition_evaluate(
                entry, "根据数据",
            )
            self.assertIn("score", r)
        test.__name__ = f"test_svc_op_{_i}"
        test.__doc__ = f"服务操作 {_task[:6]}"
        return test
    setattr(TestGeneratedSvcOps,
            _make().__name__, _make())


# ── 评价评分矩阵 ────────────────────────────────────────────────
_SCORE_CASES = [
    (1.0, "根据数据", "有不确定性", 0.9),
    (0.5, "", "", 0.3),
    (0.9, "毫无疑问", "", 0.3),
]


class TestGeneratedScores(unittest.TestCase):
    """生成式: 评分"""
    pass


for _i, (_conf, _text, _unc, _evidence_score) in \
        enumerate(_SCORE_CASES):
    def _make(conf=_conf, text=_text, unc=_unc,
              ev_score=_evidence_score):
        def test(self):
            entry = {
                "monitor_id": "cm_x", "task": "t",
                "reasoning_type": "rules",
                "confidence": conf,
                "uncertainty": unc,
                "resources": [],
            }
            r = ReasoningEvaluator().evaluate(entry, text)
            self.assertEqual(
                r["dimensions"]["evidence"]["score"],
                ev_score)
            self.assertGreaterEqual(r["score"], 0.0)
            self.assertLessEqual(r["score"], 1.0)
        test.__name__ = f"test_score_{_i}"
        test.__doc__ = f"评分 {_i}"
        return test
    setattr(TestGeneratedScores,
            _make().__name__, _make())


# ── 监控容量矩阵 ────────────────────────────────────────────────
_CAP_CASES = [1, 5, 20]


class TestGeneratedMonitorCap(unittest.TestCase):
    """生成式: 监控容量"""
    pass


for _i, _cap in enumerate(_CAP_CASES):
    def _make(cap=_cap):
        def test(self):
            monitor = CognitiveMonitor(max_records=cap)
            for j in range(cap * 2):
                monitor.record(f"任务{j}")
            self.assertEqual(monitor.stats()[
                "record_count"], cap)
        test.__name__ = f"test_mcap_{_i}"
        test.__doc__ = f"监控容量 {_cap}"
        return test
    setattr(TestGeneratedMonitorCap,
            _make().__name__, _make())


# ── 服务统计矩阵 ────────────────────────────────────────────────
class TestServiceStats(unittest.TestCase):
    """服务统计"""

    def test_stats_shape(self):
        svc = setup_service()
        svc.companion_meta_cognition_monitor("任务")
        stats = svc.companion_meta_cognition_stats()
        for key in ("monitor", "evaluator", "detector",
                    "reflection", "verification", "memory",
                    "audit"):
            self.assertIn(key, stats)

    def test_audit_after_ops(self):
        svc = setup_service()
        svc.companion_meta_cognition_monitor("任务")
        svc.companion_meta_cognition_detect_error("记错了")
        stats = svc.companion_meta_cognition_stats()
        self.assertGreaterEqual(stats["audit"][
            "record_count"], 2)

    def test_operation_count(self):
        svc = setup_service()
        svc.companion_meta_cognition_monitor("a")
        svc.companion_meta_cognition_monitor("b")
        svc.companion_meta_cognition_monitor("c")
        stats = svc.companion_meta_cognition_stats()
        self.assertEqual(stats["operation_count"], 3)


# ── 服务配置矩阵 ────────────────────────────────────────────────
class TestServiceConfig(unittest.TestCase):
    """服务配置"""

    def test_constitution_link_off(self):
        svc = setup_service(
            companion_meta_cognition_constitution_link=False,
        )
        self.assertIsNone(
            svc.companion_meta_cognition._constitution)

    def test_memory_max_config(self):
        svc = setup_service(
            companion_meta_cognition_memory_max=5,
        )
        memory = svc.companion_meta_cognition._memory
        self.assertEqual(memory._max_records, 5)

    def test_audit_max_config(self):
        svc = setup_service(
            companion_meta_cognition_audit_max=10,
        )
        audit = svc.companion_meta_cognition._audit
        self.assertEqual(audit._max_records, 10)


if __name__ == "__main__":
    unittest.main()
