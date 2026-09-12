"""
YHLZ Embodied AI V7.0 - 具身表达层补充测试 6 (V7.0 Extra6)

覆盖 (生成式批量矩阵 + 恢复/边界):
    - 恢复后一致性
    - 强度序列收敛
    - 引擎审计累积
    - 服务边界
"""
import unittest

from backend.embodied.companion.embodied_presence import (
    PresenceEngine,
    PresenceState,
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


# ── 恢复后更新序列矩阵 ──────────────────────────────────────────
_RESTORE_SEQ_CASES = [
    ("success", "failure", "success"),
    ("deep_task", "idle", "success"),
    ("failure", "deep_task", "idle"),
]


class TestGeneratedRestoreSeq(unittest.TestCase):
    """生成式: 恢复后序列"""
    pass


for _i, _seq in enumerate(_RESTORE_SEQ_CASES):
    def _make(seq=_seq):
        def test(self):
            engine = PresenceEngine()
            engine.restore_state({
                "expression": "平静", "posture": "待机",
                "intensity": 0.3,
                "interaction_mode": "neutral",
            })
            for ctx in seq:
                r = engine.update(ctx)
                self.assertIn("expression", r)
            # 审计累计 = 序列长度 (恢复不计审计)
            self.assertEqual(engine.audit_report()["total"],
                             len(seq))
        test.__name__ = f"test_rseq_{_i}"
        test.__doc__ = f"恢复序列 {_i}"
        return test
    setattr(TestGeneratedRestoreSeq,
            _make().__name__, _make())


# ── 强度收敛终点矩阵 ────────────────────────────────────────────
_CONVERGE_FINAL = [
    ("success", 0.7),
    ("failure", 0.6),
    ("deep_task", 0.6),
    ("idle", 0.3),
]


class TestGeneratedConvergeFinal(unittest.TestCase):
    """生成式: 收敛终点"""
    pass


for _i, (_ctx, _target) in enumerate(_CONVERGE_FINAL):
    def _make(ctx=_ctx, target=_target):
        def test(self):
            engine = PresenceEngine()
            for _ in range(15):
                engine.update(ctx)
            state = engine.state()
            self.assertAlmostEqual(state["intensity"],
                                   target, places=2)
        test.__name__ = f"test_cfinal_{_i}"
        test.__doc__ = f"收敛终点 {_ctx}"
        return test
    setattr(TestGeneratedConvergeFinal,
            _make().__name__, _make())


# ── 审计累积矩阵 ────────────────────────────────────────────────
_AUDIT_ACCUM = [1, 3, 5, 10]


class TestGeneratedAuditAccum(unittest.TestCase):
    """生成式: 审计累积"""
    pass


for _i, _n in enumerate(_AUDIT_ACCUM):
    def _make(n=_n):
        def test(self):
            engine = PresenceEngine()
            for _ in range(n):
                engine.update("success")
            audit = engine.audit_report()
            self.assertEqual(audit["total"], n)
            self.assertEqual(
                engine.stats()["update_count"], n)
        test.__name__ = f"test_accum_{_i}"
        test.__doc__ = f"累积 {_n}"
        return test
    setattr(TestGeneratedAuditAccum,
            _make().__name__, _make())


# ── 状态构造矩阵 ────────────────────────────────────────────────
_STATE_CONSTRUCT_CASES = [
    ("平静", "待机", 0.3, "neutral"),
    ("高兴", "回应", 0.7, "playful"),
    ("关切", "聆听", 0.6, "supportive"),
    ("思考", "专注", 0.6, "focused"),
    ("疲惫", "待机", 0.2, "neutral"),
]


class TestGeneratedStateConstruct(unittest.TestCase):
    """生成式: 状态构造"""
    pass


for _i, (_expr, _posture, _intensity, _mode) in \
        enumerate(_STATE_CONSTRUCT_CASES):
    def _make(expr=_expr, posture=_posture,
              intensity=_intensity, mode=_mode):
        def test(self):
            state = PresenceState(
                expression=expr, posture=posture,
                intensity=intensity,
                interaction_mode=mode,
            )
            s = state.to_dict()
            self.assertEqual(s["expression"], expr)
            self.assertEqual(s["posture"], posture)
            self.assertEqual(s["interaction_mode"], mode)
        test.__name__ = f"test_construct_{_i}"
        test.__doc__ = f"构造 {_expr}"
        return test
    setattr(TestGeneratedStateConstruct,
            _make().__name__, _make())


class TestServiceBoundary(unittest.TestCase):
    """服务边界"""

    def test_presence_after_handle(self):
        svc = setup_service()
        r = svc.companion.handle({"text": "hi"})
        self.assertIn("personality", r)
        # handle 不直接改变表达 (表达经显式调用)
        state = svc.companion_presence_state()
        self.assertEqual(state["expression"], "平静")

    def test_presence_state_after_hybrid_many(self):
        svc = setup_service()
        for i in range(5):
            svc.companion_hybrid_execute(
                {"type": "creative_exploration"
                 if i % 2 == 0 else "architecture_design"},
                {"prompt": "x"},
            )
        state = svc.companion_presence_state()
        self.assertIn(state["expression"],
                      ["高兴", "思考"])

    def test_presence_config_steps(self):
        svc = setup_service(
            companion_presence_intensity_step=0.5,
        )
        svc.companion_presence_update("success")
        r = svc.companion_presence_update("success")
        self.assertLessEqual(r["intensity"], 0.8)


if __name__ == "__main__":
    unittest.main()
