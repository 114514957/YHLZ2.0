"""
YHLZ Embodied AI V7.0 - 具身表达层补充测试 3 (V7.0 Extra3)

覆盖 (生成式批量矩阵):
    - 状态恢复组合
    - 映射输出不变量
    - 引擎联动矩阵
    - 审计统计矩阵
"""
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


# ── 状态不变量矩阵 ──────────────────────────────────────────────
_INVARIANT_CASES = [
    "success", "failure", "deep_task", "idle",
    "creative_done", "creative_rejected",
    "relationship_up",
]


class TestGeneratedInvariants(unittest.TestCase):
    """生成式: 更新后状态不变量"""
    pass


for _i, _ctx in enumerate(_INVARIANT_CASES):
    def _make(ctx=_ctx):
        def test(self):
            engine = PresenceEngine()
            r = engine.update(ctx)
            self.assertIn(r["expression"], ["平静", "高兴",
                                            "关切", "思考",
                                            "疲惫"])
            self.assertIn(r["posture"], ["待机", "聆听",
                                         "回应", "专注"])
            self.assertIn(r["interaction_mode"],
                          ["neutral", "supportive", "playful",
                           "focused"])
            self.assertGreaterEqual(r["intensity"], 0.0)
            self.assertLessEqual(r["intensity"], 1.0)
        test.__name__ = f"test_inv_{_i}"
        test.__doc__ = f"不变量 {_ctx}"
        return test
    setattr(TestGeneratedInvariants,
            _make().__name__, _make())


# ── 引擎更新后记忆同步矩阵 ──────────────────────────────────────
_SYNC_CASES = [
    (["success"], {"playful": 1}),
    (["success", "success"], {"playful": 2}),
    (["success", "failure"],
     {"playful": 1, "supportive": 1}),
    (["deep_task"] * 3, {"focused": 3}),
]


class TestGeneratedMemorySync(unittest.TestCase):
    """生成式: 记忆同步"""
    pass


for _i, (_seq, _dist) in enumerate(_SYNC_CASES):
    def _make(seq=_seq, dist=_dist):
        def test(self):
            engine = PresenceEngine()
            for ctx in seq:
                engine.update(ctx)
            stats = engine.memory_stats()
            self.assertEqual(stats["mode_distribution"],
                             dist)
            self.assertEqual(stats["record_count"],
                             len(seq))
        test.__name__ = f"test_sync_{_i}"
        test.__doc__ = f"同步 {len(_seq)}"
        return test
    setattr(TestGeneratedMemorySync,
            _make().__name__, _make())


# ── 审计统计矩阵 ────────────────────────────────────────────────
_AUDIT_DIST_CASES = [
    (["success"] * 2, {"success": 2}),
    (["success", "failure", "success"],
     {"success": 2, "failure": 1}),
    (["idle"] * 4, {"idle": 4}),
]


class TestGeneratedAuditDist(unittest.TestCase):
    """生成式: 审计分布"""
    pass


for _i, (_seq, _dist) in enumerate(_AUDIT_DIST_CASES):
    def _make(seq=_seq, dist=_dist):
        def test(self):
            engine = PresenceEngine()
            for ctx in seq:
                engine.update(ctx)
            report = engine.audit_report(limit=0)
            contexts = [e["context"]
                        for e in report["recent"]]
            from collections import Counter
            self.assertEqual(dict(Counter(contexts)), dist)
        test.__name__ = f"test_audit_dist_{_i}"
        test.__doc__ = f"审计分布 {_i}"
        return test
    setattr(TestGeneratedAuditDist,
            _make().__name__, _make())


# ── 强度逐步逼近矩阵 ────────────────────────────────────────────
_APPROACH_CASES = [
    ("success", 0.7, 3),
    ("failure", 0.6, 2),
    ("deep_task", 0.6, 2),
    ("idle", 0.3, 1),
]


class TestGeneratedApproach(unittest.TestCase):
    """生成式: 强度逼近"""
    pass


for _i, (_ctx, _target, _min_steps) in \
        enumerate(_APPROACH_CASES):
    def _make(ctx=_ctx, target=_target,
              min_steps=_min_steps):
        def test(self):
            engine = PresenceEngine(
                emotion=EmotionEngine(),
            )
            for _ in range(min_steps):
                engine.update(ctx)
            state = engine.state()
            self.assertLessEqual(state["intensity"],
                                 target + 0.01)
        test.__name__ = f"test_approach_{_i}"
        test.__doc__ = f"逼近 {_ctx}"
        return test
    setattr(TestGeneratedApproach,
            _make().__name__, _make())


# ── 映射输出全字段矩阵 ──────────────────────────────────────────
_FIELD_KEYS = ["expression", "posture", "intensity",
               "interaction_mode", "reason", "confidence",
               "mode"]


class TestGeneratedMapperFields(unittest.TestCase):
    """生成式: 映射输出字段"""
    pass


for _i, _ctx in enumerate(
        ["success", "failure", "idle", "deep_task",
         "creative_done", "relationship_up"]):
    def _make(ctx=_ctx):
        def test(self):
            r = PresenceMapper().map(_emotion(), None, ctx)
            for key in _FIELD_KEYS:
                self.assertIn(key, r)
        test.__name__ = f"test_fields_{_i}"
        test.__doc__ = f"字段 {_ctx}"
        return test
    setattr(TestGeneratedMapperFields,
            _make().__name__, _make())


# ── 状态 get 查询矩阵 ───────────────────────────────────────────
class TestGeneratedStateGet(unittest.TestCase):
    """生成式: 状态查询"""
    pass


for _i, _key in enumerate(["expression", "posture",
                           "intensity", "interaction_mode"]):
    def _make(key=_key):
        def test(self):
            state = PresenceState()
            self.assertIsNotNone(state.get(key))
        test.__name__ = f"test_get_{_i}"
        test.__doc__ = f"查询 {_key}"
        return test
    setattr(TestGeneratedStateGet,
            _make().__name__, _make())


# ── 连续性窗口矩阵 ──────────────────────────────────────────────
_WINDOW_CASES = [(7,), (30,), (90,)]


class TestGeneratedWindows(unittest.TestCase):
    """生成式: 连续性窗口"""
    pass


for _i, (_days,) in enumerate(_WINDOW_CASES):
    def _make(days=_days):
        def test(self):
            engine = PresenceEngine()
            for _ in range(5):
                engine.update("success")
            c = engine.continuity(window_days=days)
            self.assertEqual(c["window_days"], days)
            self.assertGreaterEqual(c["total"], 0)
        test.__name__ = f"test_window_{_i}"
        test.__doc__ = f"窗口 {_days}"
        return test
    setattr(TestGeneratedWindows,
            _make().__name__, _make())


# ── 引擎与情绪联动矩阵 ──────────────────────────────────────────
_EMOTION_LINK_CASES = [
    (0.9, 0.5, 0.5, "高兴"),
    (0.1, 0.5, 0.5, "关切"),
    (0.5, 0.9, 0.5, "平静"),
]


class TestGeneratedEmotionLink(unittest.TestCase):
    """生成式: 情绪联动"""
    pass


for _i, (_pos, _en, _warm, _expr) in \
        enumerate(_EMOTION_LINK_CASES):
    def _make(pos=_pos, en=_en, warm=_warm, expr=_expr):
        def test(self):
            emotion = EmotionEngine()
            emotion.restore_state(_emotion(
                positivity=pos, energy=en, warmth=warm,
            ))
            engine = PresenceEngine(emotion=emotion)
            r = engine.update("idle")
            self.assertEqual(r["expression"], expr)
        test.__name__ = f"test_emo_link_{_i}"
        test.__doc__ = f"情绪联动 {_pos}"
        return test
    setattr(TestGeneratedEmotionLink,
            _make().__name__, _make())


class TestHistoryBoundary(unittest.TestCase):
    """历史边界"""

    def test_history_empty(self):
        engine = PresenceEngine()
        h = engine.history()
        self.assertEqual(h["records"], [])

    def test_history_limit(self):
        engine = PresenceEngine()
        for _ in range(10):
            engine.update("idle")
        h = engine.history(limit=3)
        self.assertEqual(len(h["records"]), 3)

    def test_memory_max_cap(self):
        memory = PresenceMemory(max_records=5)
        for i in range(10):
            memory.record(context=f"t{i}",
                          interaction_mode="x")
        self.assertEqual(memory.stats()["record_count"], 5)


if __name__ == "__main__":
    unittest.main()
