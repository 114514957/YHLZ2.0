"""
YHLZ Embodied AI V7.0 - 具身表达层补充测试 4 (V7.0 Extra4)

覆盖 (生成式批量矩阵 + 服务级):
    - 上下文组合序列
    - 恢复边界
    - 服务级表达联动
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


# ── 组合序列矩阵 ────────────────────────────────────────────────
_COMBO_SEQS = [
    ["success", "success", "success"],
    ["failure", "failure", "success"],
    ["deep_task", "success", "idle"],
    ["idle", "failure", "creative_done"],
    ["success", "deep_task", "failure", "idle"],
]


class TestGeneratedCombos(unittest.TestCase):
    """生成式: 组合序列"""
    pass


for _i, _seq in enumerate(_COMBO_SEQS):
    def _make(seq=_seq):
        def test(self):
            engine = PresenceEngine()
            last = None
            for ctx in seq:
                last = engine.update(ctx)
            # 最后状态有效
            self.assertIn("expression", last)
            self.assertEqual(engine.stats()[
                "update_count"], len(seq))
            # 记忆同步
            self.assertEqual(engine.memory_stats()[
                "record_count"], len(seq))
        test.__name__ = f"test_combo_{_i}"
        test.__doc__ = f"组合 {len(_seq)}"
        return test
    setattr(TestGeneratedCombos,
            _make().__name__, _make())


# ── 强度序列单调性矩阵 ──────────────────────────────────────────
_MONOTONE_CASES = [
    ["success", "success", "success"],
    ["deep_task", "deep_task"],
    ["failure", "failure", "failure"],
]


class TestGeneratedMonotone(unittest.TestCase):
    """生成式: 强度单调逼近"""
    pass


for _i, _seq in enumerate(_MONOTONE_CASES):
    def _make(seq=_seq):
        def test(self):
            engine = PresenceEngine()
            values = []
            for ctx in seq:
                values.append(engine.update(ctx)[
                    "intensity"])
            for j in range(len(values) - 1):
                self.assertLessEqual(values[j + 1] -
                                     values[j], 0.151)
        test.__name__ = f"test_mono_{_i}"
        test.__doc__ = f"单调 {_i}"
        return test
    setattr(TestGeneratedMonotone,
            _make().__name__, _make())


# ── 恢复后更新矩阵 ──────────────────────────────────────────────
_RESTORE_UPDATE_CASES = [
    ("平静", "success", "高兴"),
    ("平静", "failure", "关切"),
    ("思考", "idle", "平静"),
]


class TestGeneratedRestoreUpdate(unittest.TestCase):
    """生成式: 恢复后更新"""
    pass


for _i, (_restore_expr, _ctx, _expected) in \
        enumerate(_RESTORE_UPDATE_CASES):
    def _make(restore_expr=_restore_expr, ctx=_ctx,
              expected=_expected):
        def test(self):
            engine = PresenceEngine()
            engine.restore_state({
                "expression": restore_expr,
                "posture": "待机", "intensity": 0.3,
                "interaction_mode": "neutral",
            })
            r = engine.update(ctx)
            self.assertEqual(r["expression"], expected)
        test.__name__ = f"test_restore_upd_{_i}"
        test.__doc__ = f"恢复更新 {_restore_expr}"
        return test
    setattr(TestGeneratedRestoreUpdate,
            _make().__name__, _make())


# ── 映射 reason 可解释矩阵 ──────────────────────────────────────
_REASON_CASES = [
    ("success", "任务成功"),
    ("failure", "任务失败"),
    ("deep_task", "深度任务"),
    ("idle", "空闲"),
]


class TestGeneratedReasons(unittest.TestCase):
    """生成式: 映射原因"""
    pass


for _i, (_ctx, _kw) in enumerate(_REASON_CASES):
    def _make(ctx=_ctx, kw=_kw):
        def test(self):
            r = PresenceMapper().map(_emotion(), None, ctx)
            self.assertIn(kw, r["reason"])
        test.__name__ = f"test_reason_{_i}"
        test.__doc__ = f"原因 {_ctx}"
        return test
    setattr(TestGeneratedReasons,
            _make().__name__, _make())


# ── 服务级联动矩阵 ──────────────────────────────────────────────
class TestServiceLinkage(unittest.TestCase):
    """服务级表达联动"""

    def test_presence_after_hybrid_flow(self):
        svc = setup_service()
        svc.companion_hybrid_execute(
            {"type": "creative_exploration"},
            {"prompt": "x"},
        )
        state = svc.companion_presence_state()
        self.assertEqual(state["expression"], "高兴")

    def test_presence_after_deep_flow(self):
        svc = setup_service()
        svc.companion_hybrid_execute(
            {"type": "architecture_design"},
            {"prompt": "x"},
        )
        state = svc.companion_presence_state()
        self.assertEqual(state["expression"], "思考")

    def test_presence_stats_after_mixed(self):
        svc = setup_service()
        svc.companion_presence_update("success")
        svc.companion_hybrid_execute(
            {"type": "creative_exploration"},
            {"prompt": "x"},
        )
        stats = svc.companion_presence_stats()
        self.assertEqual(stats["update_count"], 2)

    def test_presence_continuity_service(self):
        svc = setup_service()
        for _ in range(3):
            svc.companion_presence_update("success")
        c = svc.companion_presence_continuity(window_days=1)
        self.assertEqual(c["preferred_expression"], "高兴")

    def test_presence_interpreter_service_readonly(self):
        svc = setup_service()
        before = svc.companion_presence_state()
        svc.companion_presence_interpreter("success")
        after = svc.companion_presence_state()
        self.assertEqual(before, after)

    def test_presence_guard_via_service(self):
        svc = setup_service()
        svc.companion_presence_update("success")
        stats = svc.companion_presence_stats()
        self.assertEqual(stats["guard_block_count"], 0)


class TestStateBoundary(unittest.TestCase):
    """状态边界"""

    def test_state_get_missing_key(self):
        state = PresenceState()
        self.assertIsNone(state.get("missing_key"))

    def test_state_dict_isolation(self):
        state = PresenceState()
        d1 = state.to_dict()
        d1["expression"] = "高兴"
        d2 = state.to_dict()
        self.assertEqual(d2["expression"], "平静")

    def test_state_update_isolation(self):
        state = PresenceState()
        r1 = state.update(expression="高兴")
        r1["expression"] = "思考"
        self.assertEqual(state.get("expression"), "高兴")


if __name__ == "__main__":
    unittest.main()
