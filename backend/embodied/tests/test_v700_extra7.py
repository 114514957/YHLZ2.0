"""
YHLZ Embodied AI V7.0 - 具身表达层补充测试 7 (V7.0 Extra7)

覆盖 (生成式批量矩阵):
    - 情绪值边界矩阵
    - 上下文轮换矩阵
    - 快照循环矩阵
    - 服务级联动矩阵
"""
import unittest

from backend.embodied.companion.emotion import EmotionEngine
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


# ── 情绪极值矩阵 ────────────────────────────────────────────────
_EXTREME_CASES = [
    (0.0, 0.0, 0.0),
    (1.0, 1.0, 1.0),
    (0.0, 1.0, 0.0),
    (1.0, 0.0, 1.0),
    (0.33, 0.66, 0.99),
]


class TestGeneratedExtremes(unittest.TestCase):
    """生成式: 情绪极值"""
    pass


for _i, (_pos, _en, _warm) in enumerate(_EXTREME_CASES):
    def _make(pos=_pos, en=_en, warm=_warm):
        def test(self):
            r = PresenceMapper().map(
                _emotion(positivity=pos, energy=en,
                         warmth=warm),
                None, "idle",
            )
            self.assertIn(r["expression"],
                          ["平静", "高兴", "关切"])
            self.assertGreaterEqual(r["intensity"], 0.0)
            self.assertLessEqual(r["intensity"], 1.0)
        test.__name__ = f"test_extreme_{_i}"
        test.__doc__ = f"极值 {_pos}/{_en}/{_warm}"
        return test
    setattr(TestGeneratedExtremes,
            _make().__name__, _make())


# ── 上下文轮换矩阵 ──────────────────────────────────────────────
_ROTATION_CASES = [
    ["success", "failure", "idle", "success"],
    ["deep_task", "creative_done", "failure", "idle"],
    ["idle", "deep_task", "success", "creative_done"],
]


class TestGeneratedRotation(unittest.TestCase):
    """生成式: 上下文轮换"""
    pass


for _i, _seq in enumerate(_ROTATION_CASES):
    def _make(seq=_seq):
        def test(self):
            engine = PresenceEngine(
                emotion=EmotionEngine(),
            )
            last = None
            for ctx in seq:
                last = engine.update(ctx)
            self.assertIn("expression", last)
            self.assertEqual(engine.memory_stats()[
                "record_count"], len(seq))
        test.__name__ = f"test_rotate_{_i}"
        test.__doc__ = f"轮换 {len(_seq)}"
        return test
    setattr(TestGeneratedRotation,
            _make().__name__, _make())


# ── 快照循环矩阵 ────────────────────────────────────────────────
_SNAPSHOT_LOOP_CASES = [
    ["success", "idle"],
    ["deep_task", "success", "failure"],
    ["success", "failure", "success", "idle"],
]


class TestGeneratedSnapshotLoop(unittest.TestCase):
    """生成式: 快照循环"""
    pass


for _i, _seq in enumerate(_SNAPSHOT_LOOP_CASES):
    def _make(seq=_seq):
        def test(self):
            engine = PresenceEngine()
            for ctx in seq:
                engine.update(ctx)
            snap = engine.state()
            engine2 = PresenceEngine()
            engine2.restore_state(snap)
            self.assertEqual(engine2.state()["expression"],
                             snap["expression"])
            self.assertEqual(engine2.state()["intensity"],
                             snap["intensity"])
        test.__name__ = f"test_snap_{_i}"
        test.__doc__ = f"快照 {len(_seq)}"
        return test
    setattr(TestGeneratedSnapshotLoop,
            _make().__name__, _make())


# ── 服务联动轮换矩阵 ────────────────────────────────────────────
_SERVICE_ROTATE = [
    ["success", "success"],
    ["success", "failure"],
    ["deep_task", "deep_task"],
    ["failure", "failure", "success"],
]


class TestGeneratedServiceRotate(unittest.TestCase):
    """生成式: 服务轮换"""
    pass


for _i, _seq in enumerate(_SERVICE_ROTATE):
    def _make(seq=_seq):
        def test(self):
            svc = setup_service()
            for ctx in seq:
                svc.companion_presence_update(ctx)
            c = svc.companion_presence_continuity(
                window_days=1,
            )
            self.assertEqual(c["total"], len(seq))
            stats = svc.companion_presence_stats()
            self.assertEqual(stats["update_count"],
                             len(seq))
        test.__name__ = f"test_svc_rot_{_i}"
        test.__doc__ = f"服务轮换 {len(_seq)}"
        return test
    setattr(TestGeneratedServiceRotate,
            _make().__name__, _make())


# ── 混合联动矩阵 ────────────────────────────────────────────────
_HYBRID_ROTATE = [
    ["creative_exploration"],
    ["creative_exploration", "architecture_design"],
    ["architecture_design", "creative_exploration",
     "creative_exploration"],
]


class TestGeneratedHybridRotate(unittest.TestCase):
    """生成式: 混合联动"""
    pass


for _i, _seq in enumerate(_HYBRID_ROTATE):
    def _make(seq=_seq):
        def test(self):
            svc = setup_service()
            for ttype in seq:
                svc.companion_hybrid_execute(
                    {"type": ttype}, {"prompt": "x"},
                )
            state = svc.companion_presence_state()
            self.assertIn("expression", state)
            self.assertIn(state["expression"],
                          ["高兴", "思考"])
        test.__name__ = f"test_hyb_rot_{_i}"
        test.__doc__ = f"混合联动 {len(_seq)}"
        return test
    setattr(TestGeneratedHybridRotate,
            _make().__name__, _make())


class TestEngineEdge(unittest.TestCase):
    """引擎边界"""

    def test_update_unknown_context(self):
        engine = PresenceEngine()
        r = engine.update("bogus_context")
        self.assertEqual(r["expression"], "平静")

    def test_update_none_context(self):
        engine = PresenceEngine()
        r = engine.update(None)
        self.assertIn("expression", r)

    def test_engine_without_emotion(self):
        engine = PresenceEngine()
        r = engine.update("idle")
        self.assertEqual(r["expression"], "平静")

    def test_engine_default_state(self):
        engine = PresenceEngine()
        state = engine.state()
        self.assertEqual(state["expression"], "平静")
        self.assertEqual(state["intensity"], 0.3)


if __name__ == "__main__":
    unittest.main()
