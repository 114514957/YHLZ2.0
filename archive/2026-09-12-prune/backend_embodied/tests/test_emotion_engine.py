"""
YHLZ Embodied AI V9.5.0 - 情绪引擎单元测试 (Emotion Engine)

覆盖 (emotion/emotion_engine.py, emotion/emotion_audit.py):
    - update: 情境 → 维度变化 (规则驱动)
    - 稳定性: 连续失败/成功有限幅, 不剧烈震荡
    - 衰减 / 统计 / 历史 / 审计
    - 隔离: 情绪不触碰人格
    - 恢复 (快照)
"""
import time
import unittest

from backend.embodied.companion.emotion import (
    EMOTION_AUDIT_ACTIONS,
    AuditError,
    EmotionAudit,
    EmotionEngine,
    EmotionEngineError,
)


class TestEngineInit(unittest.TestCase):
    """初始化"""

    def test_default_init(self):
        e = EmotionEngine()
        self.assertIsNotNone(e)

    def test_update_step_validation(self):
        with self.assertRaises(EmotionEngineError):
            EmotionEngine(update_step=0.0)

    def test_update_step_validation_high(self):
        with self.assertRaises(EmotionEngineError):
            EmotionEngine(update_step=1.5)

    def test_consecutive_limit_validation(self):
        with self.assertRaises(EmotionEngineError):
            EmotionEngine(consecutive_limit=1)

    def test_disabled_update_blocked(self):
        e = EmotionEngine(enabled=False)
        with self.assertRaises(EmotionEngineError):
            e.update("success")

    def test_disabled_decay_blocked(self):
        e = EmotionEngine(enabled=False)
        with self.assertRaises(EmotionEngineError):
            e.decay()


class TestUpdate(unittest.TestCase):
    """情绪更新"""

    def setUp(self):
        self.engine = EmotionEngine(update_step=0.1)

    def test_success_raises_positivity(self):
        before = self.engine.get_state()["positivity"]
        self.engine.update("success")
        after = self.engine.get_state()["positivity"]
        self.assertGreater(after, before)

    def test_failure_lowers_positivity(self):
        self.engine.update("success")
        before = self.engine.get_state()["positivity"]
        self.engine.update("failure")
        after = self.engine.get_state()["positivity"]
        self.assertLess(after, before)

    def test_relationship_up_raises_warmth(self):
        before = self.engine.get_state()["warmth"]
        self.engine.update("relationship_up")
        after = self.engine.get_state()["warmth"]
        self.assertGreater(after, before)

    def test_creative_done_raises(self):
        before = self.engine.get_state()
        self.engine.update("creative_done")
        after = self.engine.get_state()
        self.assertGreater(after["positivity"], before["positivity"])
        self.assertGreater(after["warmth"], before["warmth"])

    def test_invalid_context(self):
        with self.assertRaises(EmotionEngineError):
            self.engine.update("bogus")

    def test_update_records_memory(self):
        self.engine.update("success")
        st = self.engine.memory()
        self.assertEqual(st["by_event"].get("success", 0), 1)

    def test_update_records_audit(self):
        self.engine.update("failure")
        r = self.engine.audit_report()
        self.assertGreaterEqual(r["by_action"].get("update", 0), 1)

    def test_last_reason_set(self):
        self.engine.update("success")
        self.assertIn("成功", self.engine.get_state()["last_reason"])

    def test_step_applied(self):
        """update_step=0.2 时 success 使 positivity +0.2"""
        e = EmotionEngine(update_step=0.2)
        before = e.get_state()["positivity"]
        e.update("success")
        after = e.get_state()["positivity"]
        self.assertAlmostEqual(after - before, 0.2, places=4)

    def test_update_clamped(self):
        e = EmotionEngine(update_step=1.0)
        for _ in range(10):
            e.update("success")
        self.assertLessEqual(e.get_state()["positivity"], 1.0)


class TestStability(unittest.TestCase):
    """稳定性"""

    def setUp(self):
        self.engine = EmotionEngine(update_step=0.1,
                                    consecutive_limit=3)

    def test_consecutive_fail_limited(self):
        """连续失败第 3 次后幅度减半 (防无限下降)"""
        drops = []
        before = self.engine.get_state()["positivity"]
        for _ in range(6):
            self.engine.update("failure")
            after = self.engine.get_state()["positivity"]
            drops.append(before - after)
            before = after
        # 后期下降幅度 ≤ 前期
        self.assertLessEqual(drops[-1], drops[0] + 1e-9)

    def test_consecutive_fail_bounded(self):
        for _ in range(30):
            self.engine.update("failure")
        self.assertGreaterEqual(self.engine.get_state()["positivity"],
                                0.0)
        # 不应无限跌至 0 (有稳定性限制)
        self.assertGreater(
            self.engine.get_state()["positivity"], 0.0,
        )

    def test_consecutive_success_limited(self):
        """连续成功后幅度减半 (防无限兴奋)"""
        gains = []
        before = self.engine.get_state()["positivity"]
        for _ in range(6):
            self.engine.update("success")
            after = self.engine.get_state()["positivity"]
            gains.append(after - before)
            before = after
        self.assertLessEqual(gains[-1], gains[0] + 1e-9)

    def test_mixed_events_reset_counter(self):
        for _ in range(4):
            self.engine.update("failure")
        # 成功重置失败计数
        self.engine.update("success")
        st = self.engine.get_stats()
        self.assertEqual(st["consecutive_failures"], 0)
        self.assertEqual(st["consecutive_successes"], 1)

    def test_no_violent_oscillation(self):
        """连续事件不剧烈震荡 (单次变化 ≤ step)"""
        max_delta = 0.0
        prev = self.engine.get_state()
        for ctx in ("success", "failure", "success", "failure"):
            self.engine.update(ctx)
            cur = self.engine.get_state()
            max_delta = max(max_delta,
                            abs(cur["positivity"] - prev["positivity"]))
            prev = cur
        self.assertLessEqual(max_delta, 0.1 + 1e-9)

    def test_consecutive_counts_in_stats(self):
        self.engine.update("failure")
        self.engine.update("failure")
        st = self.engine.get_stats()
        self.assertEqual(st["consecutive_failures"], 2)


class TestDecay(unittest.TestCase):
    """引擎衰减"""

    def test_decay(self):
        e = EmotionEngine(decay_rate=0.5,
                          decay_window_days=1)
        e.update("success")
        e._state._timestamp = time.time() - 86400
        before = e.get_state()["positivity"]
        e.decay()
        after = e.get_state()["positivity"]
        self.assertLess(after, before)

    def test_decay_audit(self):
        e = EmotionEngine(decay_rate=0.5, decay_window_days=1)
        e.update("success")
        e._state._timestamp = time.time() - 86400
        e.decay()
        r = e.audit_report()
        self.assertGreaterEqual(r["by_action"].get("decay", 0), 1)

    def test_decay_no_change_no_audit(self):
        e = EmotionEngine()
        e.decay()
        r = e.audit_report()
        self.assertEqual(r["by_action"].get("decay", 0), 0)


class TestStatsAndQuery(unittest.TestCase):
    """统计与查询"""

    def setUp(self):
        self.engine = EmotionEngine()

    def test_get_state_structure(self):
        d = self.engine.get_state()
        for key in ("positivity", "energy", "warmth",
                    "last_reason", "timestamp"):
            self.assertIn(key, d)

    def test_get_stats_structure(self):
        self.engine.update("success")
        st = self.engine.get_stats()
        for key in ("mode", "enabled", "state", "update_count",
                    "decay_count", "reason_distribution",
                    "avg_change", "consecutive_failures",
                    "consecutive_successes", "baseline"):
            self.assertIn(key, st)

    def test_update_count(self):
        self.engine.update("success")
        self.engine.update("failure")
        self.assertEqual(self.engine.get_stats()["update_count"], 2)

    def test_reason_distribution(self):
        self.engine.update("success")
        self.engine.update("success")
        st = self.engine.get_stats()
        self.assertEqual(st["reason_distribution"]["success"], 2)

    def test_avg_change(self):
        self.engine.update("success")
        st = self.engine.get_stats()
        self.assertGreater(st["avg_change"], 0.0)

    def test_history(self):
        self.engine.update("success")
        h = self.engine.history()
        self.assertEqual(h["stats"]["total"], 1)

    def test_history_records(self):
        self.engine.update("success")
        h = self.engine.history(limit=10)
        self.assertEqual(h["records"][0]["event"], "success")


class TestRestore(unittest.TestCase):
    """快照恢复"""

    def test_restore_state(self):
        e = EmotionEngine()
        e.restore_state({"positivity": 0.9, "energy": 0.2,
                         "warmth": 0.8})
        st = e.get_state()
        self.assertEqual(st["positivity"], 0.9)
        self.assertEqual(st["energy"], 0.2)
        self.assertEqual(st["warmth"], 0.8)

    def test_restore_audit(self):
        e = EmotionEngine()
        e.restore_state({"positivity": 0.9})
        r = e.audit_report()
        self.assertGreaterEqual(r["by_action"].get("restore", 0), 1)

    def test_restore_memory(self):
        e = EmotionEngine()
        e.restore_state({"positivity": 0.9})
        st = e.memory()
        self.assertGreaterEqual(st["by_event"].get("restore", 0), 1)


class TestIsolation(unittest.TestCase):
    """情绪与人格隔离"""

    def test_emotion_has_no_personality_access(self):
        e = EmotionEngine()
        self.assertFalse(hasattr(e, "personality"))
        self.assertFalse(hasattr(e, "adjust_personality"))

    def test_emotion_engine_no_identity_fields(self):
        e = EmotionEngine()
        for field in ("mission", "core_value"):
            self.assertFalse(hasattr(e, field))

    def test_reset(self):
        e = EmotionEngine()
        e.update("success")
        r = e.reset()
        self.assertGreaterEqual(r["memory"], 1)
        self.assertEqual(e.get_stats()["update_count"], 0)


class TestEmotionAudit(unittest.TestCase):
    """情绪审计"""

    def test_actions_whitelist(self):
        for a in ("update", "decay", "reset", "restore"):
            self.assertIn(a, EMOTION_AUDIT_ACTIONS)

    def test_record(self):
        a = EmotionAudit()
        e = a.record(action="update", detail="success")
        self.assertTrue(e["audit_id"].startswith("ema_"))

    def test_record_invalid(self):
        a = EmotionAudit()
        with self.assertRaises(AuditError):
            a.record(action="hack")

    def test_report(self):
        a = EmotionAudit()
        a.record(action="update")
        r = a.report()
        self.assertEqual(r["mode"], "rule_based")
        self.assertEqual(r["by_action"]["update"], 1)

    def test_clear(self):
        a = EmotionAudit()
        a.record(action="update")
        self.assertEqual(a.clear(), 1)


if __name__ == "__main__":
    unittest.main()
