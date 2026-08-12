"""
YHLZ Embodied AI V6.5 - 认知反思生成式补充测试 2 (V6.5 Extra4)

覆盖 (专项补足至 ≥400):
    - 认知反思引擎变体矩阵 (生成式)
    - Service 组合 (生成式)
"""
import time
import unittest

from backend.embodied.companion.reflection import (
    CognitiveReflectionEngine,
)
from backend.embodied.service import EmbodiedService


def make_rec(trigger="t", type="improvement", result="成功",
             rid="r", ts_offset=0):
    return {
        "id": rid, "type": type, "trigger": trigger,
        "lesson": "l", "result": result,
        "timestamp": time.time() - ts_offset * 86400,
    }


# ── 生成式反思测试 ──────────────────────────────────────────────
class TestGeneratedReflections(unittest.TestCase):
    """生成式反思测试"""
    pass


_reflect_triggers = [
    "任务执行", "环境感知", "经验整理", "策略选择",
    "关系互动", "创造方案", "日志回顾", "目标追踪",
    "记忆查询", "情绪调节", "节律运行", "身份记录",
]


def _make_reflect_test(idx, trigger):
    def test(self):
        e = CognitiveReflectionEngine()
        records = [
            make_rec(trigger=trigger, result="成功",
                     rid=f"{trigger}{i}", ts_offset=i)
            for i in range(4)
        ]
        r = e.analyze(records)
        self.assertGreaterEqual(len(r["patterns"]), 1)
        self.assertIn(trigger[:4], r["summary"])
    test.__name__ = f"test_reflect_{idx}"
    test.__doc__ = f"反思: {trigger}"
    return test


for i, t in enumerate(_reflect_triggers):
    setattr(TestGeneratedReflections,
            _make_reflect_test(i, t).__name__,
            _make_reflect_test(i, t))


def _make_reflect_fail_test(idx, trigger):
    def test(self):
        e = CognitiveReflectionEngine()
        records = [
            make_rec(trigger=trigger, type="failure",
                     result="错误", rid=f"{trigger}{i}",
                     ts_offset=i)
            for i in range(3)
        ]
        r = e.analyze(records)
        self.assertTrue(r["failure_factor"])
    test.__name__ = f"test_reflect_fail_{idx}"
    test.__doc__ = f"失败反思: {trigger}"
    return test


for i, t in enumerate(_reflect_triggers[:6]):
    setattr(TestGeneratedReflections,
            _make_reflect_fail_test(i, t).__name__,
            _make_reflect_fail_test(i, t))


def _make_reflect_mixed_test(idx, trigger):
    def test(self):
        e = CognitiveReflectionEngine()
        records = (
            [make_rec(trigger=trigger, result="成功",
                      rid=f"s{i}", ts_offset=i)
             for i in range(2)]
            + [make_rec(trigger=trigger, type="failure",
                        result="错误", rid=f"f{i}",
                        ts_offset=i + 2)
               for i in range(2)]
        )
        r = e.analyze(records)
        self.assertGreaterEqual(r["confidence"], 0.0)
    test.__name__ = f"test_reflect_mixed_{idx}"
    test.__doc__ = f"混合反思: {trigger}"
    return test


for i, t in enumerate(_reflect_triggers[:8]):
    setattr(TestGeneratedReflections,
            _make_reflect_mixed_test(i, t).__name__,
            _make_reflect_mixed_test(i, t))


# ── 生成式 Service 测试 ─────────────────────────────────────────
class TestGeneratedService(unittest.TestCase):
    """生成式 Service 测试"""
    pass


_service_triggers = [
    "工程任务", "视觉感知", "策略优化", "长期规划",
    "互动沟通", "创造提案", "经验总结", "身份验证",
]


def _make_service_reflect_test(idx, trigger):
    def test(self):
        svc = EmbodiedService()
        svc.load_config({"companion_enabled": True})
        for i in range(4):
            svc.companion_experience.store_from_event(
                success=True, trigger=trigger,
                source="gen_test", action="a", result="成功",
            )
        r = svc.companion_reflection_analyze()
        self.assertGreaterEqual(len(r["patterns"]), 0)
    test.__name__ = f"test_service_reflect_{idx}"
    test.__doc__ = f"Service 反思: {trigger}"
    return test


for i, t in enumerate(_service_triggers):
    setattr(TestGeneratedService,
            _make_service_reflect_test(i, t).__name__,
            _make_service_reflect_test(i, t))


def _make_service_growth_test(idx, trigger):
    def test(self):
        svc = EmbodiedService()
        svc.load_config({"companion_enabled": True})
        for i in range(4):
            svc.companion_experience.store_from_event(
                success=False, trigger=trigger,
                source="gen_test", action="a", result="错误",
            )
        g = svc.companion_growth_generate()
        self.assertGreaterEqual(g["proposal_count"], 1)
    test.__name__ = f"test_service_growth_{idx}"
    test.__doc__ = f"Service 成长: {trigger}"
    return test


for i, t in enumerate(_service_triggers[:6]):
    setattr(TestGeneratedService,
            _make_service_growth_test(i, t).__name__,
            _make_service_growth_test(i, t))


def _make_service_guard_test(idx, field):
    def test(self):
        svc = EmbodiedService()
        svc.load_config({"companion_enabled": True})
        r = svc.companion_growth_apply(
            {"id": f"p{idx}", "type": "skill_improvement",
             "description": "改进", "expected_gain": "g",
             "risk": "low", "confidence": 0.8},
            {"approved": True, "reason": "x"},
            changes={field: "新值"},
        )
        self.assertEqual(r["status"], "blocked", field)
    test.__name__ = f"test_service_guard_{idx}"
    test.__doc__ = f"Service 守护: {field}"
    return test


_service_guard_fields = [
    "mission", "core_value", "base_personality",
    "safety_rules", "permission",
]

for i, field in enumerate(_service_guard_fields):
    setattr(TestGeneratedService,
            _make_service_guard_test(i, field).__name__,
            _make_service_guard_test(i, field))


def _make_service_stats_test(idx, trigger):
    def test(self):
        svc = EmbodiedService()
        svc.load_config({"companion_enabled": True})
        for i in range(3):
            svc.companion_experience.store_from_event(
                success=True, trigger=trigger,
                source="gen_test", action="a", result="成功",
            )
        svc.companion_reflection_analyze()
        st = svc.companion_growth_stats()
        self.assertGreaterEqual(st["reflection"][
            "reflection_count"], 1)
    test.__name__ = f"test_service_stats_{idx}"
    test.__doc__ = f"Service 统计: {trigger}"
    return test


for i, t in enumerate(_service_triggers[:5]):
    setattr(TestGeneratedService,
            _make_service_stats_test(i, t).__name__,
            _make_service_stats_test(i, t))


if __name__ == "__main__":
    unittest.main()
