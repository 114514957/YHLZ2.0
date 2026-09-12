"""
YHLZ Embodied AI V7.0 - 具身表达层补充测试 8 (V7.0 Extra8)

覆盖 (生成式批量矩阵):
    - 表达式轮换
    - 强度阈值
    - 连续性节奏
    - 服务矩阵
"""
import unittest

from backend.embodied.companion.embodied_presence import (
    EXPRESSIONS,
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


# ── 表情可达矩阵 (每表情至少一次可达到) ─────────────────────────
_EXPRESSION_REACH = {
    "平静": "idle",
    "高兴": "success",
    "关切": "failure",
    "思考": "deep_task",
}


class TestGeneratedExpressionReach(unittest.TestCase):
    """生成式: 表情可达"""
    pass


for _expr, _ctx in _EXPRESSION_REACH.items():
    def _make(expr=_expr, ctx=_ctx):
        def test(self):
            engine = PresenceEngine()
            r = engine.update(ctx)
            self.assertEqual(r["expression"], expr)
        test.__name__ = f"test_reach_{expr}"
        test.__doc__ = f"可达 {expr}"
        return test
    setattr(TestGeneratedExpressionReach,
            _make().__name__, _make())


# ── 强度阈值矩阵 ────────────────────────────────────────────────
_THRESHOLD_CASES = [
    ("success", 0.7, 5),
    ("failure", 0.6, 5),
    ("deep_task", 0.6, 5),
    ("idle", 0.3, 3),
]


class TestGeneratedThreshold(unittest.TestCase):
    """生成式: 强度阈值"""
    pass


for _i, (_ctx, _target, _steps) in enumerate(_THRESHOLD_CASES):
    def _make(ctx=_ctx, target=_target, steps=_steps):
        def test(self):
            engine = PresenceEngine()
            for _ in range(steps):
                engine.update(ctx)
            s = engine.state()
            self.assertLessEqual(s["intensity"],
                                 target + 0.01)
        test.__name__ = f"test_thresh_{_i}"
        test.__doc__ = f"阈值 {_ctx}"
        return test
    setattr(TestGeneratedThreshold,
            _make().__name__, _make())


# ── 连续性节奏矩阵 ──────────────────────────────────────────────
_RHYTHM_CASES = [
    (["success"] * 3, "playful"),
    (["failure"] * 3, "supportive"),
    (["deep_task"] * 3, "focused"),
    (["success", "failure", "success"],
     "playful"),
]


class TestGeneratedRhythm(unittest.TestCase):
    """生成式: 节奏偏好"""
    pass


for _i, (_seq, _mode) in enumerate(_RHYTHM_CASES):
    def _make(seq=_seq, mode=_mode):
        def test(self):
            engine = PresenceEngine()
            for ctx in seq:
                engine.update(ctx)
            c = engine.continuity()
            self.assertEqual(c["preferred_mode"], mode)
        test.__name__ = f"test_rhythm_{_i}"
        test.__doc__ = f"节奏 {_i}"
        return test
    setattr(TestGeneratedRhythm,
            _make().__name__, _make())


# ── 服务矩阵 ────────────────────────────────────────────────────
class TestServiceMatrix(unittest.TestCase):
    """服务级矩阵"""

    def test_service_update_returns_state_fields(self):
        svc = setup_service()
        r = svc.companion_presence_update("success")
        for key in ("expression", "posture", "intensity",
                    "interaction_mode", "timestamp",
                    "reason", "mode"):
            self.assertIn(key, r)

    def test_service_state_after_sequence(self):
        svc = setup_service()
        svc.companion_presence_update("success")
        svc.companion_presence_update("failure")
        svc.companion_presence_update("success")
        state = svc.companion_presence_state()
        self.assertEqual(state["expression"], "高兴")

    def test_service_interpreter_all(self):
        svc = setup_service()
        for ctx in ("success", "failure", "deep_task",
                    "idle"):
            r = svc.companion_presence_interpreter(ctx)
            self.assertIn("expression", r)
            self.assertIn("confidence", r)

    def test_service_continuity_after_hybrid(self):
        svc = setup_service()
        for _ in range(3):
            svc.companion_hybrid_execute(
                {"type": "architecture_design"},
                {"prompt": "x"},
            )
        c = svc.companion_presence_continuity(window_days=1)
        self.assertEqual(c["preferred_expression"], "思考")

    def test_service_disabled_hybrid_link(self):
        svc = setup_service(
            companion_presence_hybrid_link=False,
        )
        svc.companion_hybrid_execute(
            {"type": "creative_exploration"},
            {"prompt": "x"},
        )
        state = svc.companion_presence_state()
        self.assertEqual(state["expression"], "平静")


class TestMapperEdge(unittest.TestCase):
    """映射器边界"""

    def test_mapper_empty_emotion(self):
        r = PresenceMapper().map({}, None, "idle")
        self.assertEqual(r["expression"], "平静")

    def test_mapper_empty_all(self):
        r = PresenceMapper().map({}, {}, "idle")
        self.assertIn("expression", r)

    def test_mapper_confidence_always_range(self):
        for ctx in ("success", "failure", "deep_task",
                    "idle", "creative_done"):
            r = PresenceMapper().map({}, {}, ctx)
            self.assertGreaterEqual(r["confidence"], 0.0)
            self.assertLessEqual(r["confidence"], 1.0)


class TestStateEdge(unittest.TestCase):
    """状态边界"""

    def test_state_expressions_all_valid(self):
        for expr in EXPRESSIONS:
            state = PresenceState(expression=expr)
            self.assertEqual(state.get("expression"), expr)

    def test_state_intensity_rounding(self):
        state = PresenceState()
        state.update(intensity=0.33333)
        self.assertEqual(state.get("intensity"), 0.3333)

    def test_state_timestamp_float(self):
        state = PresenceState()
        self.assertIsInstance(
            state.to_dict()["timestamp"], float)


if __name__ == "__main__":
    unittest.main()
