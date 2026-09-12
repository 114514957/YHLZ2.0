"""
YHLZ Embodied AI V7.0 - 具身表达层补充测试 9 (V7.0 Extra9)

覆盖 (生成式批量):
    - 上下文可达矩阵
    - 强度单调性
    - 服务表达矩阵
"""
import unittest

from backend.embodied.companion.embodied_presence import (
    PresenceEngine,
    PresenceMapper,
    PresenceState,
)
from backend.embodied.service import EmbodiedService


def _emotion(positivity=0.5, energy=0.5, warmth=0.5):
    return {
        "positivity": positivity,
        "energy": energy,
        "warmth": warmth,
    }


def setup_service(**extra):
    cfg = {
        "embodied_enabled": True,
        "companion_enabled": True,
    }
    cfg.update(extra)
    svc = EmbodiedService()
    svc.load_config(cfg)
    return svc


# ── 上下文可达矩阵 ──────────────────────────────────────────────
_CTX_REACH = [
    ("success", "高兴", "playful"),
    ("failure", "关切", "supportive"),
    ("creative_done", "高兴", "playful"),
    ("creative_rejected", "关切", "supportive"),
    ("relationship_up", "高兴", "playful"),
    ("deep_task", "思考", "focused"),
    ("idle", "平静", "neutral"),
]


class TestGeneratedCtxReach(unittest.TestCase):
    """生成式: 上下文可达"""
    pass


for _i, (_ctx, _expr, _mode) in enumerate(_CTX_REACH):
    def _make(ctx=_ctx, expr=_expr, mode=_mode):
        def test(self):
            engine = PresenceEngine()
            r = engine.update(ctx)
            self.assertEqual(r["expression"], expr)
            self.assertEqual(r["interaction_mode"], mode)
        test.__name__ = f"test_ctxreach_{_i}"
        test.__doc__ = f"可达 {_ctx}"
        return test
    setattr(TestGeneratedCtxReach,
            _make().__name__, _make())


# ── 强度单调逼近矩阵 ────────────────────────────────────────────
_MONO_CASES = [
    ("success", 5, 0.7),
    ("failure", 5, 0.6),
    ("deep_task", 5, 0.6),
]


class TestGeneratedMonoApproach(unittest.TestCase):
    """生成式: 单调逼近"""
    pass


for _i, (_ctx, _n, _target) in enumerate(_MONO_CASES):
    def _make(ctx=_ctx, n=_n, target=_target):
        def test(self):
            engine = PresenceEngine()
            prev = 0.3
            for _ in range(n):
                cur = engine.update(ctx)["intensity"]
                self.assertLessEqual(cur - prev, 0.151)
                prev = cur
            self.assertLessEqual(prev, target + 0.01)
        test.__name__ = f"test_monoapp_{_i}"
        test.__doc__ = f"单调 {_ctx}"
        return test
    setattr(TestGeneratedMonoApproach,
            _make().__name__, _make())


# ── 服务表达矩阵 ────────────────────────────────────────────────
class TestServiceExprMatrix(unittest.TestCase):
    """服务表达矩阵"""

    def test_service_expression_cycle(self):
        svc = setup_service()
        svc.companion_presence_update("deep_task")
        svc.companion_presence_update("success")
        svc.companion_presence_update("failure")
        state = svc.companion_presence_state()
        self.assertEqual(state["expression"], "关切")

    def test_service_interpreter_readonly_all(self):
        svc = setup_service()
        for ctx in ("success", "failure", "deep_task",
                    "idle", "creative_done"):
            svc.companion_presence_interpreter(ctx)
        state = svc.companion_presence_state()
        self.assertEqual(state["expression"], "平静")

    def test_service_hybrid_presence_final(self):
        svc = setup_service()
        svc.companion_hybrid_execute(
            {"type": "architecture_design"},
            {"prompt": "x"},
        )
        svc.companion_hybrid_execute(
            {"type": "creative_exploration"},
            {"prompt": "x"},
        )
        state = svc.companion_presence_state()
        self.assertEqual(state["expression"], "高兴")


class TestMapperBoundary(unittest.TestCase):
    """映射边界"""

    def test_mapper_all_contexts_output(self):
        mapper = PresenceMapper()
        for ctx in ("success", "failure", "deep_task",
                    "idle", "creative_done",
                    "creative_rejected",
                    "relationship_up"):
            r = mapper.map(_emotion(), None, ctx)
            self.assertEqual(r["mode"], "rule_based")
            self.assertIn("reason", r)

    def test_mapper_high_humor_all_contexts(self):
        mapper = PresenceMapper()
        r = mapper.map(_emotion(), {"humor": 0.9}, "idle")
        self.assertEqual(r["interaction_mode"], "playful")


class TestStateBoundary(unittest.TestCase):
    """状态边界"""

    def test_state_restore_default(self):
        state = PresenceState()
        state.update(expression="高兴", intensity=0.9)
        state.restore({})
        # 缺省字段回默认
        self.assertEqual(state.get("expression"), "平静")
        self.assertEqual(state.get("posture"), "待机")

    def test_state_reset_after_updates(self):
        state = PresenceState()
        for _ in range(10):
            state.update(expression="高兴",
                         intensity=0.9)
        state.reset()
        self.assertEqual(state.get("expression"), "平静")
        self.assertEqual(state.get("intensity"), 0.3)

    def test_state_reason_update(self):
        state = PresenceState()
        state.update(expression="高兴",
                     reason="自定义原因")
        self.assertEqual(state.to_dict()["last_reason"],
                         "自定义原因")


if __name__ == "__main__":
    unittest.main()
