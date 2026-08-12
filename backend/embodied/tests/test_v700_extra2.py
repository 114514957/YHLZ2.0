"""
YHLZ Embodied AI V7.0 - 具身表达层补充测试 2 (V7.0 Extra2)

覆盖 (生成式批量 + 边界):
    - 状态更新组合
    - 映射输出组合
    - 引擎审计矩阵
    - 线程安全
"""
import threading
import unittest

from backend.embodied.companion.emotion import EmotionEngine
from backend.embodied.companion.embodied_presence import (
    PresenceEngine,
    PresenceMapper,
    PresenceMemory,
    PresenceState,
)


def _emotion(positivity=0.5, energy=0.5, warmth=0.5):
    return {
        "positivity": positivity,
        "energy": energy,
        "warmth": warmth,
    }


# ── 状态更新组合矩阵 ────────────────────────────────────────────
_UPDATE_CASES = [
    ("success", "高兴"),
    ("failure", "关切"),
    ("creative_done", "高兴"),
    ("creative_rejected", "关切"),
    ("relationship_up", "高兴"),
    ("deep_task", "思考"),
    ("idle", "平静"),
]


class TestGeneratedUpdate(unittest.TestCase):
    """生成式: 状态更新"""
    pass


for _i, (_ctx, _expr) in enumerate(_UPDATE_CASES):
    def _make(ctx=_ctx, expr=_expr):
        def test(self):
            engine = PresenceEngine()
            r = engine.update(ctx)
            self.assertEqual(r["expression"], expr)
            self.assertEqual(r["mode"], "rule_based")
        test.__name__ = f"test_update_{_i}"
        test.__doc__ = f"更新 {_ctx}"
        return test
    setattr(TestGeneratedUpdate, _make().__name__, _make())


# ── 状态字段保持矩阵 ────────────────────────────────────────────
_PARTIAL_CASES = [
    ("success", "failure"),
    ("deep_task", "idle"),
    ("creative_done", "creative_rejected"),
    ("failure", "success"),
]


class TestGeneratedTransitions(unittest.TestCase):
    """生成式: 状态转移"""
    pass


for _i, (_a, _b) in enumerate(_PARTIAL_CASES):
    def _make(a=_a, b=_b):
        def test(self):
            engine = PresenceEngine()
            engine.update(a)
            s1 = engine.state()
            engine.update(b)
            s2 = engine.state()
            # 表情可切换 (表达可变化)
            self.assertIn("expression", s1)
            self.assertIn("expression", s2)
            # 转移不破坏结构
            for key in ("expression", "posture",
                        "intensity", "interaction_mode"):
                self.assertIn(key, s2)
        test.__name__ = f"test_trans_{_i}"
        test.__doc__ = f"转移 {_a}→{_b}"
        return test
    setattr(TestGeneratedTransitions,
            _make().__name__, _make())


# ── 审计矩阵 ────────────────────────────────────────────────────
_AUDIT_SEQ_CASES = [
    ["success"],
    ["success", "failure"],
    ["success", "failure", "deep_task"],
    ["idle"] * 5,
    ["success", "creative_done", "relationship_up",
     "deep_task", "idle"],
]


class TestGeneratedAuditSeq(unittest.TestCase):
    """生成式: 审计序列"""
    pass


for _i, _seq in enumerate(_AUDIT_SEQ_CASES):
    def _make(seq=_seq):
        def test(self):
            engine = PresenceEngine()
            for ctx in seq:
                engine.update(ctx)
            audit = engine.audit_report()
            self.assertEqual(audit["total"], len(seq))
            self.assertEqual(
                [e["context"] for e in audit["recent"]],
                list(reversed(seq)),
            )
        test.__name__ = f"test_audit_seq_{_i}"
        test.__doc__ = f"审计序列 {len(_seq)}"
        return test
    setattr(TestGeneratedAuditSeq,
            _make().__name__, _make())


# ── 记忆分布矩阵 ────────────────────────────────────────────────
_MEMORY_SEQ_CASES = [
    (["success"] * 3, {"playful": 3}),
    (["success", "failure"] * 2,
     {"playful": 2, "supportive": 2}),
    (["deep_task"] * 4, {"focused": 4}),
]


class TestGeneratedMemoryDist(unittest.TestCase):
    """生成式: 记忆分布"""
    pass


for _i, (_seq, _dist) in enumerate(_MEMORY_SEQ_CASES):
    def _make(seq=_seq, dist=_dist):
        def test(self):
            engine = PresenceEngine()
            for ctx in seq:
                engine.update(ctx)
            stats = engine.memory_stats()
            self.assertEqual(stats["mode_distribution"],
                             dist)
        test.__name__ = f"test_mem_dist_{_i}"
        test.__doc__ = f"记忆分布 {_i}"
        return test
    setattr(TestGeneratedMemoryDist,
            _make().__name__, _make())


# ── 强度边界矩阵 ────────────────────────────────────────────────
_INTENSITY_BOUNDS = [
    (0.0, 0.0),
    (0.1, 0.1),
    (0.5, 0.5),
    (0.9, 0.9),
    (1.0, 1.0),
    (1.5, 1.0),
    (-0.5, 0.0),
]


class TestGeneratedIntensityBound(unittest.TestCase):
    """生成式: 强度边界"""
    pass


for _i, (_raw, _expected) in enumerate(_INTENSITY_BOUNDS):
    def _make(raw=_raw, expected=_expected):
        def test(self):
            state = PresenceState()
            state.update(intensity=raw)
            self.assertEqual(state.get("intensity"),
                             expected)
        test.__name__ = f"test_ibound_{_i}"
        test.__doc__ = f"强度边界 {_raw}"
        return test
    setattr(TestGeneratedIntensityBound,
            _make().__name__, _make())


# ── 映射置信度矩阵 ──────────────────────────────────────────────
_CONFIDENCE_CASES = [
    (1.0, 0.9),
    (0.9, 0.87),
    (0.5, 0.75),
    (0.0, 0.6),
]


class TestGeneratedConfidence(unittest.TestCase):
    """生成式: 置信度"""
    pass


for _i, (_pos, _expected) in enumerate(_CONFIDENCE_CASES):
    def _make(pos=_pos, expected=_expected):
        def test(self):
            r = PresenceMapper().map(
                _emotion(positivity=pos), None, "idle",
            )
            self.assertAlmostEqual(r["confidence"],
                                   expected, places=2)
        test.__name__ = f"test_conf_{_i}"
        test.__doc__ = f"置信度 {_pos}"
        return test
    setattr(TestGeneratedConfidence,
            _make().__name__, _make())


# ── 连续性统计矩阵 ──────────────────────────────────────────────
_CONTINUITY_CASES = [
    (1, 0),
    (5, 0),
    (10, 5),
    (30, 20),
]


class TestGeneratedContinuityStats(unittest.TestCase):
    """生成式: 连续性统计"""
    pass


for _i, (_total, _fails) in enumerate(_CONTINUITY_CASES):
    def _make(total=_total, fails=_fails):
        def test(self):
            engine = PresenceEngine()
            for _ in range(fails):
                engine.update("failure")
            for _ in range(total - fails):
                engine.update("success")
            c = engine.continuity()
            self.assertEqual(c["total"], total)
            self.assertGreaterEqual(c["rhythm_stability"],
                                    0.0)
        test.__name__ = f"test_cont_{_i}"
        test.__doc__ = f"连续性 {_total}"
        return test
    setattr(TestGeneratedContinuityStats,
            _make().__name__, _make())


# ── 恢复矩阵 ────────────────────────────────────────────────────
_RESTORE_CASES = [
    ("高兴", "回应", 0.7, "playful"),
    ("关切", "聆听", 0.6, "supportive"),
    ("思考", "专注", 0.6, "focused"),
    ("平静", "待机", 0.3, "neutral"),
]


class TestGeneratedRestore(unittest.TestCase):
    """生成式: 快照恢复"""
    pass


for _i, (_expr, _posture, _intensity, _mode) in \
        enumerate(_RESTORE_CASES):
    def _make(expr=_expr, posture=_posture,
              intensity=_intensity, mode=_mode):
        def test(self):
            engine = PresenceEngine()
            engine.update("success")
            engine.restore_state({
                "expression": expr, "posture": posture,
                "intensity": intensity,
                "interaction_mode": mode,
            })
            s = engine.state()
            self.assertEqual(s["expression"], expr)
            self.assertEqual(s["posture"], posture)
            self.assertEqual(s["interaction_mode"], mode)
        test.__name__ = f"test_restore_{_i}"
        test.__doc__ = f"恢复 {_expr}"
        return test
    setattr(TestGeneratedRestore,
            _make().__name__, _make())


class TestEngineThreadSafety(unittest.TestCase):
    """线程安全"""

    def test_concurrent_engine_updates(self):
        engine = PresenceEngine(emotion=EmotionEngine())
        errors = []

        def work():
            try:
                for _ in range(15):
                    engine.update("success")
                    engine.update("idle")
            except Exception as e:  # pragma: no cover
                errors.append(e)

        threads = [threading.Thread(target=work)
                   for _ in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        self.assertEqual(engine.stats()["update_count"], 180)

    def test_concurrent_memory_records(self):
        memory = PresenceMemory()
        errors = []

        def work():
            try:
                for _ in range(30):
                    memory.record(context="a",
                                  interaction_mode="x")
            except Exception as e:  # pragma: no cover
                errors.append(e)

        threads = [threading.Thread(target=work)
                   for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        self.assertEqual(memory.stats()["record_count"], 120)

    def test_concurrent_state_updates(self):
        state = PresenceState()
        errors = []

        def work():
            try:
                for _ in range(30):
                    state.update(expression="高兴",
                                 intensity=0.8)
                    state.update(expression="平静",
                                 intensity=0.2)
            except Exception as e:  # pragma: no cover
                errors.append(e)

        threads = [threading.Thread(target=work)
                   for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
