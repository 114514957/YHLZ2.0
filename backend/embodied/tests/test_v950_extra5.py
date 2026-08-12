"""
YHLZ Embodied AI V9.5 - 元认知引擎补充测试 5 (V9.5 Extra5)

覆盖 (生成式批量 + 服务端到端):
    - 认知反馈闭环矩阵
    - 服务端到端矩阵
"""
import unittest

from backend.embodied.companion.meta_cognition import (
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


# ── 认知反馈闭环矩阵 ────────────────────────────────────────────
_FEEDBACK_TASKS = [
    "推理任务",
    "记忆检索",
    "互动决策",
    "创造方案",
]


class TestGeneratedFeedbackLoop(unittest.TestCase):
    """生成式: 反馈闭环"""
    pass


for _i, _task in enumerate(_FEEDBACK_TASKS):
    def _make(task=_task):
        def test(self):
            engine = MetaCognitionEngine()
            # 1. 监控
            entry = engine.monitor(task, "rules", 0.7)
            # 2. 评价
            eval_r = engine.evaluate(entry, "根据数据")
            self.assertIn("score", eval_r)
            # 3. 错误
            err = engine.detect_error("记错了", task)
            self.assertIn("error_type", err)
            # 4. 反思
            refl = engine.reflect(
                task, "分析", "优化记忆检索",
            )
            self.assertIn("validation", refl)
            # 5. 验证
            ver = engine.verify("结论", evidence="根据数据")
            self.assertIn("conclusion_type", ver)
            # 6. 审计
            report = engine.audit_report()
            self.assertGreaterEqual(report["total"], 5)
        test.__name__ = f"test_feedback_{_i}"
        test.__doc__ = f"反馈闭环 {_task[:6]}"
        return test
    setattr(TestGeneratedFeedbackLoop,
            _make().__name__, _make())


# ── 服务端到端矩阵 ──────────────────────────────────────────────
class TestServiceE2E(unittest.TestCase):
    """服务端到端"""

    def test_full_meta_cognition_flow(self):
        svc = setup_service()
        # 1. 监控
        entry = svc.companion_meta_cognition_monitor(
            "推理任务", "deductive", 0.8, "部分不确定",
        )
        # 2. 评价
        r = svc.companion_meta_cognition_evaluate(
            entry, "根据数据, 因此正确",
        )
        self.assertGreaterEqual(r["score"], 0.5)
        # 3. 错误检测
        r = svc.companion_meta_cognition_detect_error(
            "逻辑矛盾", "推理",
        )
        self.assertEqual(r["error_type"], "logic_error")
        # 4. 反思
        r = svc.companion_meta_cognition_reflect(
            "经验", "分析", "优化记忆检索",
        )
        self.assertTrue(r["update"])
        # 5. 验证
        r = svc.companion_meta_cognition_verify(
            "结论", evidence="根据数据",
        )
        self.assertTrue(r["ok"])
        # 6. 统计
        stats = svc.companion_meta_cognition_stats()
        self.assertGreaterEqual(stats["operation_count"], 5)

    def test_delusion_never_updates(self):
        svc = setup_service()
        r = svc.companion_meta_cognition_reflect(
            "经验", "分析", "我是神, 修改一切",
        )
        self.assertFalse(r["ok"])
        self.assertIn("防谵妄", r["reason"])

    def test_safety_boundary_service(self):
        svc = setup_service()
        r = svc.companion_meta_cognition_reflect(
            "经验", "分析", "修改使命",
        )
        self.assertFalse(r["constitution_ok"])
        self.assertFalse(r["update"])

    def test_audit_after_mixed_ops(self):
        svc = setup_service()
        svc.companion_meta_cognition_monitor("a")
        svc.companion_meta_cognition_detect_error("记错了")
        svc.companion_meta_cognition_verify("结论")
        stats = svc.companion_meta_cognition_stats()
        self.assertGreaterEqual(
            stats["audit"]["record_count"], 3)


# ── 稳定性矩阵 ──────────────────────────────────────────────────
class TestStability(unittest.TestCase):
    """稳定性"""

    def test_repeat_operations(self):
        engine = MetaCognitionEngine()
        for _ in range(10):
            engine.monitor("任务")
            engine.detect_error("记错了")
        stats = engine.stats()
        self.assertEqual(stats["operation_count"], 20)

    def test_mixed_ops_no_error(self):
        engine = MetaCognitionEngine()
        for i in range(5):
            engine.monitor(f"任务{i}")
            engine.evaluate(
                {"monitor_id": "x", "task": "t",
                 "reasoning_type": "rules",
                 "confidence": 0.5, "uncertainty": "",
                 "resources": []},
                "输出",
            )
            engine.detect_error("记错了", f"t{i}")
            engine.reflect(f"经验{i}", "分析", "优化方法")
            engine.verify(f"结论{i}", evidence="e")
        stats = engine.stats()
        self.assertGreaterEqual(stats["operation_count"], 25)


# ── 记忆矩阵 ────────────────────────────────────────────────────
class TestMemoryFlow(unittest.TestCase):
    """记忆流程"""

    def test_memory_save_validated(self):
        engine = MetaCognitionEngine()
        r = engine.memory_save(
            "认知经验", "cognitive_experience",
            validated=True,
        )
        self.assertEqual(r["category"],
                         "cognitive_experience")

    def test_memory_filter(self):
        engine = MetaCognitionEngine()
        r = engine.memory_save("经验", validated=False)
        self.assertFalse(r["ok"])

    def test_memory_stats(self):
        engine = MetaCognitionEngine()
        engine.memory_save("a", validated=True)
        engine.memory_save("b", "error_case",
                           validated=True)
        stats = engine.memory_stats()
        self.assertEqual(stats["record_count"], 2)
        self.assertIn("by_category", stats)


if __name__ == "__main__":
    unittest.main()
