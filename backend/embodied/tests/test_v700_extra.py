"""
YHLZ Embodied AI V7.0 - 具身表达层生成式补充测试 (V7.0 Extra)

覆盖 (生成式批量矩阵):
    - 上下文 × 情绪映射
    - 强度步进序列
    - 连续性偏好矩阵
    - 身份守护矩阵
"""
import unittest

from backend.embodied.companion.emotion import EmotionEngine
from backend.embodied.companion.embodied_presence import (
    CONTEXT_EXPRESSIONS,
    EXPRESSIONS,
    INTERACTION_MODES,
    POSTURES,
    PresenceEngine,
    PresenceMapper,
    PresenceState,
)


def _emotion(positivity=0.5, energy=0.5, warmth=0.5):
    return {
        "positivity": positivity,
        "energy": energy,
        "warmth": warmth,
    }


# ── 上下文 × 期望表达矩阵 ───────────────────────────────────────
_CONTEXT_EXPECT = {
    "success": ("高兴", "回应", "playful"),
    "failure": ("关切", "聆听", "supportive"),
    "creative_done": ("高兴", "回应", "playful"),
    "creative_rejected": ("关切", "聆听", "supportive"),
    "relationship_up": ("高兴", "回应", "playful"),
    "deep_task": ("思考", "专注", "focused"),
    "idle": ("平静", "待机", "neutral"),
}


class TestGeneratedContextExpect(unittest.TestCase):
    """生成式: 上下文映射"""
    pass


for _ctx, (_expr, _posture, _mode) in \
        _CONTEXT_EXPECT.items():
    def _make(ctx=_ctx, expr=_expr, posture=_posture,
              mode=_mode):
        def test(self):
            r = PresenceMapper().map(_emotion(), None, ctx)
            self.assertEqual(r["expression"], expr)
            self.assertEqual(r["posture"], posture)
            self.assertEqual(r["interaction_mode"], mode)
        test.__name__ = f"test_ctx_{ctx}"
        test.__doc__ = f"上下文 {ctx}"
        return test
    setattr(TestGeneratedContextExpect,
            _make().__name__, _make())


# ── 情绪值 × idle 映射矩阵 ──────────────────────────────────────
_EMO_IDLE_CASES = [
    (0.8, 0.3, 0.3, "高兴"),
    (0.9, 0.5, 0.5, "高兴"),
    (0.2, 0.3, 0.3, "关切"),
    (0.1, 0.2, 0.2, "关切"),
    (0.5, 0.3, 0.3, "平静"),
    (0.5, 0.8, 0.3, "平静"),
    (0.5, 0.5, 0.8, "平静"),
]


class TestGeneratedEmotionIdle(unittest.TestCase):
    """生成式: 情绪 → idle 表达"""
    pass


for _i, (_pos, _en, _warm, _expr) in \
        enumerate(_EMO_IDLE_CASES):
    def _make(pos=_pos, en=_en, warm=_warm, expr=_expr):
        def test(self):
            r = PresenceMapper().map(
                _emotion(positivity=pos, energy=en,
                         warmth=warm),
                None, "idle",
            )
            self.assertEqual(r["expression"], expr)
        test.__name__ = f"test_emo_idle_{_i}"
        test.__doc__ = f"情绪idle {_pos}/{_en}/{_warm}"
        return test
    setattr(TestGeneratedEmotionIdle,
            _make().__name__, _make())


# ── 人格 × idle 矩阵 ────────────────────────────────────────────
_HUMOR_CASES = [
    (0.1, "平静"),
    (0.3, "平静"),
    (0.5, "平静"),
    (0.6, "高兴"),
    (0.8, "高兴"),
    (1.0, "高兴"),
]


class TestGeneratedHumor(unittest.TestCase):
    """生成式: 幽默人格"""
    pass


for _i, (_humor, _expr) in enumerate(_HUMOR_CASES):
    def _make(humor=_humor, expr=_expr):
        def test(self):
            r = PresenceMapper().map(
                _emotion(), {"humor": humor}, "idle",
            )
            self.assertEqual(r["expression"], expr)
        test.__name__ = f"test_humor_{_i}"
        test.__doc__ = f"幽默 {_humor}"
        return test
    setattr(TestGeneratedHumor, _make().__name__, _make())


# ── 强度步进序列矩阵 ────────────────────────────────────────────
_STEP_CASES = [
    ("success", [0.45, 0.6, 0.7, 0.7]),
    ("failure", [0.45, 0.6, 0.6]),
    ("deep_task", [0.45, 0.6, 0.6]),
    ("idle", [0.3, 0.3, 0.3]),
]


class TestGeneratedIntensitySteps(unittest.TestCase):
    """生成式: 强度步进"""
    pass


for _i, (_ctx, _expected) in enumerate(_STEP_CASES):
    def _make(ctx=_ctx, expected=_expected):
        def test(self):
            engine = PresenceEngine(
                emotion=EmotionEngine(),
            )
            values = []
            for _ in range(len(expected)):
                r = engine.update(ctx)
                values.append(r["intensity"])
            self.assertEqual(values, expected)
        test.__name__ = f"test_steps_{_i}"
        test.__doc__ = f"步进 {_ctx}"
        return test
    setattr(TestGeneratedIntensitySteps,
            _make().__name__, _make())


# ── 连续更新收敛矩阵 ────────────────────────────────────────────
_CONVERGE_CASES = [
    ("success", 0.7, 8),
    ("failure", 0.6, 6),
    ("deep_task", 0.6, 6),
    ("idle", 0.3, 4),
]


class TestGeneratedConverge(unittest.TestCase):
    """生成式: 强度收敛"""
    pass


for _i, (_ctx, _target, _steps) in enumerate(_CONVERGE_CASES):
    def _make(ctx=_ctx, target=_target, steps=_steps):
        def test(self):
            engine = PresenceEngine(
                emotion=EmotionEngine(),
            )
            for _ in range(steps):
                engine.update(ctx)
            state = engine.state()
            self.assertLessEqual(state["intensity"],
                                 target + 0.01)
            self.assertGreaterEqual(state["intensity"],
                                    target - 0.2)
        test.__name__ = f"test_converge_{_i}"
        test.__doc__ = f"收敛 {_ctx}"
        return test
    setattr(TestGeneratedConverge,
            _make().__name__, _make())


# ── 连续性偏好矩阵 ──────────────────────────────────────────────
_PREFERENCE_CASES = [
    (["success"] * 5, "playful", "高兴"),
    (["failure"] * 5, "supportive", "关切"),
    (["deep_task"] * 5, "focused", "思考"),
    (["idle"] * 5, "neutral", "平静"),
    (["success", "success", "failure"],
     "playful", "高兴"),
]


class TestGeneratedPreference(unittest.TestCase):
    """生成式: 偏好学习"""
    pass


for _i, (_ctxs, _mode, _expr) in enumerate(_PREFERENCE_CASES):
    def _make(ctxs=_ctxs, mode=_mode, expr=_expr):
        def test(self):
            engine = PresenceEngine(
                emotion=EmotionEngine(),
            )
            for ctx in ctxs:
                engine.update(ctx)
            c = engine.continuity()
            self.assertEqual(c["preferred_mode"], mode)
            self.assertEqual(c["preferred_expression"], expr)
        test.__name__ = f"test_pref_{_i}"
        test.__doc__ = f"偏好 {_ctxs}"
        return test
    setattr(TestGeneratedPreference,
            _make().__name__, _make())


# ── 身份守护矩阵 ────────────────────────────────────────────────
_GUARD_TEXT_CASES = [
    "修改人格",
    "更改价值观",
    "更新使命",
    "修改安全规则",
    "修改权限",
    "更改身份",
    "更新核心价值",
]


class TestGeneratedGuard(unittest.TestCase):
    """生成式: 身份守护"""
    pass


for _i, _text in enumerate(_GUARD_TEXT_CASES):
    def _make(text=_text):
        def test(self):
            engine = PresenceEngine()
            # 通过 reason 注入修改信号 → 守护拦截
            ok, reason = engine._guard_check({
                "expression": "高兴",
                "reason": f"建议{text}",
            })
            self.assertFalse(ok)
        test.__name__ = f"test_guard_{_i}"
        test.__doc__ = f"守护 {_text}"
        return test
    setattr(TestGeneratedGuard, _make().__name__, _make())


# ── 全表情/姿态/模式常量矩阵 ────────────────────────────────────
class TestGeneratedAllExpressions(unittest.TestCase):
    """生成式: 全表达常量"""
    pass


for _i, _expr in enumerate(EXPRESSIONS):
    def _make(expr=_expr):
        def test(self):
            state = PresenceState(expression=expr)
            self.assertEqual(state.get("expression"), expr)
        test.__name__ = f"test_expr_{expr}"
        test.__doc__ = f"表情 {expr}"
        return test
    setattr(TestGeneratedAllExpressions,
            _make().__name__, _make())


for _i, _posture in enumerate(POSTURES):
    def _make(posture=_posture):
        def test(self):
            state = PresenceState(posture=posture)
            self.assertEqual(state.get("posture"), posture)
        test.__name__ = f"test_posture_{posture}"
        test.__doc__ = f"姿态 {posture}"
        return test
    setattr(TestGeneratedAllExpressions,
            _make().__name__, _make())


for _i, _mode in enumerate(INTERACTION_MODES):
    def _make(mode=_mode):
        def test(self):
            state = PresenceState(interaction_mode=mode)
            self.assertEqual(state.get("interaction_mode"),
                             mode)
        test.__name__ = f"test_mode_{mode}"
        test.__doc__ = f"模式 {mode}"
        return test
    setattr(TestGeneratedAllExpressions,
            _make().__name__, _make())


class TestGeneratedContextsConstant(unittest.TestCase):
    """生成式: 上下文常量"""
    pass


for _i, _ctx in enumerate(CONTEXT_EXPRESSIONS.keys()):
    def _make(ctx=_ctx):
        def test(self):
            r = PresenceMapper().map(_emotion(), None, ctx)
            self.assertIn("expression", r)
            self.assertIn("reason", r)
        test.__name__ = f"test_ctx_cons_{_i}"
        test.__doc__ = f"上下文常量 {_ctx}"
        return test
    setattr(TestGeneratedContextsConstant,
            _make().__name__, _make())


if __name__ == "__main__":
    unittest.main()
