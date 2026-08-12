"""
YHLZ Embodied AI V7.0 - 具身表达层补充测试 5 (V7.0 Extra5)

覆盖 (生成式批量矩阵):
    - 上下文 × 情绪 × 人格三维矩阵
    - 连续表达一致性
    - 服务级边界
"""
import unittest

from backend.embodied.companion.embodied_presence import (
    PresenceEngine,
    PresenceMapper,
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


# ── 上下文 × 情绪三维矩阵 ───────────────────────────────────────
# (ctx, positivity, energy, warmth) → 表达式判定
_3D_CASES = [
    ("success", 0.2, 0.2, 0.2, "高兴"),   # 上下文优先
    ("failure", 0.9, 0.9, 0.9, "关切"),   # 上下文优先
    ("idle", 0.8, 0.5, 0.5, "高兴"),
    ("idle", 0.2, 0.5, 0.5, "关切"),
    ("idle", 0.5, 0.8, 0.5, "平静"),
    ("idle", 0.5, 0.5, 0.8, "平静"),
    ("deep_task", 0.1, 0.1, 0.1, "思考"),
]


class TestGenerated3D(unittest.TestCase):
    """生成式: 三维矩阵"""
    pass


for _i, (_ctx, _pos, _en, _warm, _expr) in \
        enumerate(_3D_CASES):
    def _make(ctx=_ctx, pos=_pos, en=_en, warm=_warm,
              expr=_expr):
        def test(self):
            r = PresenceMapper().map(
                _emotion(positivity=pos, energy=en,
                         warmth=warm),
                None, ctx,
            )
            self.assertEqual(r["expression"], expr)
        test.__name__ = f"test_3d_{_i}"
        test.__doc__ = f"三维 {_ctx}/{_pos}"
        return test
    setattr(TestGenerated3D, _make().__name__, _make())


# ── 连续一致性矩阵 ──────────────────────────────────────────────
_CONSISTENCY_CASES = [
    (["success"] * 10, "高兴", "playful"),
    (["failure"] * 10, "关切", "supportive"),
    (["deep_task"] * 10, "思考", "focused"),
    (["idle"] * 10, "平静", "neutral"),
]


class TestGeneratedConsistency(unittest.TestCase):
    """生成式: 连续一致性"""
    pass


for _i, (_seq, _expr, _mode) in enumerate(_CONSISTENCY_CASES):
    def _make(seq=_seq, expr=_expr, mode=_mode):
        def test(self):
            engine = PresenceEngine()
            for ctx in seq:
                engine.update(ctx)
            c = engine.continuity()
            self.assertEqual(c["preferred_expression"], expr)
            self.assertEqual(c["preferred_mode"], mode)
            # 状态稳定
            state = engine.state()
            self.assertEqual(state["expression"], expr)
        test.__name__ = f"test_consist_{_i}"
        test.__doc__ = f"一致性 {len(_seq)}"
        return test
    setattr(TestGeneratedConsistency,
            _make().__name__, _make())


# ── 服务级表达矩阵 ──────────────────────────────────────────────
class TestServicePresence(unittest.TestCase):
    """服务级表达"""

    def test_service_update_all_contexts(self):
        svc = setup_service()
        for ctx in ("success", "failure", "deep_task",
                    "idle"):
            r = svc.companion_presence_update(ctx)
            self.assertIn("expression", r)

    def test_service_stats_fields(self):
        svc = setup_service()
        svc.companion_presence_update("success")
        stats = svc.companion_presence_stats()
        for key in ("enabled", "update_count",
                    "guard_block_count", "state", "mapper",
                    "memory", "intensity_step"):
            self.assertIn(key, stats)

    def test_service_continuity_fields(self):
        svc = setup_service()
        svc.companion_presence_update("success")
        c = svc.companion_presence_continuity()
        for key in ("mode", "window_days", "total",
                    "daily_avg", "rhythm_stability",
                    "preferred_mode",
                    "preferred_expression", "reason"):
            self.assertIn(key, c)

    def test_service_hybrid_presence_chain(self):
        svc = setup_service()
        for _ in range(3):
            svc.companion_hybrid_execute(
                {"type": "creative_exploration"},
                {"prompt": "x"},
            )
        c = svc.companion_presence_continuity(window_days=1)
        self.assertEqual(c["preferred_expression"], "高兴")


if __name__ == "__main__":
    unittest.main()
