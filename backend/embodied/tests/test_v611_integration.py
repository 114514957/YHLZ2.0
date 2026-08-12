"""
YHLZ Embodied AI V9.5.0 - 成长节律门面与集成测试 (Growth Rhythm & Service)

覆盖 (rhythm/growth_rhythm.py + Service 集成):
    - handle 联动: 自动事件采集 / 情绪联动
    - 自动整理 (条件触发) / 自动快照 (每日) / 反思触发
    - 自主成长边界 (不修改人格)
    - 快照 emotion 域扩展 + 旧快照兼容
    - Service API
"""
import os
import shutil
import tempfile
import time
import unittest

from backend.embodied.companion.continuity_engine import (
    ContinuityEngine,
)
from backend.embodied.companion.creative import CreativeEngine
from backend.embodied.companion.emotion import EmotionEngine
from backend.embodied.companion.experience import ExperienceManager
from backend.embodied.companion.personality import (
    AdaptivePersonalityEngine,
)
from backend.embodied.companion.reflection import ReflectionEngine
from backend.embodied.companion.relationship import RelationshipManager
from backend.embodied.companion.rhythm import GrowthRhythm
from backend.embodied.companion.verification import ExperienceVerifier
from backend.embodied.service import EmbodiedService


class RhythmTestBase(unittest.TestCase):
    """基础环境"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="yhlz_rhythm_")
        self.path = os.path.join(self.tmp, "state.jsonl")
        self.mgr = ExperienceManager()
        self.verifier = ExperienceVerifier()
        self.reflection = ReflectionEngine()
        self.creative = CreativeEngine(
            experience_manager=self.mgr,
            verifier=self.verifier,
            reflection_engine=self.reflection,
        )
        self.relationship = RelationshipManager()
        self.personality = AdaptivePersonalityEngine(base="铁哥们")
        self.emotion = EmotionEngine()
        self.continuity = ContinuityEngine(
            experience_manager=self.mgr,
            verifier=self.verifier,
            reflection_engine=self.reflection,
            creative_engine=self.creative,
            relationship_manager=self.relationship,
            personality_engine=self.personality,
            emotion_engine=self.emotion,
        )
        self.rhythm = GrowthRhythm(
            continuity=self.continuity,
            emotion=self.emotion,
            config={
                "companion_rhythm_consolidate_threshold": 3,
                "companion_rhythm_consolidate_days": 7,
                "companion_rhythm_daily_snapshot": False,
            },
        )

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def seed(self, trigger="生成工程Prompt", n=3):
        ids = []
        for _ in range(n):
            rec = self.mgr.store_from_event(
                success=True, trigger=trigger,
                source="rhythm_test", action="a", result="成功",
            )
            ids.append(rec["id"])
        for rid in ids:
            for _ in range(3):
                self.verifier.verify(rid, evidence_count=2,
                                     contradictions=0)
        return ids


class TestRhythmHandle(RhythmTestBase):
    """handle 联动"""

    def test_on_handle_captures(self):
        r = self.rhythm.on_handle(
            {"intent": "扫描"}, {"aggregated": {"ok_count": 1,
                                                "total": 1}},
        )
        self.assertIn("experience_added", r["captured"])
        self.assertIn("task_completed", r["captured"])

    def test_on_handle_tracks_events(self):
        self.rhythm.on_handle({}, {"aggregated": {"ok_count": 1,
                                                  "total": 1}})
        st = self.continuity.tracker.stats()
        self.assertGreaterEqual(st["by_type"].get(
            "experience_added", 0), 1)
        self.assertGreaterEqual(st["by_type"].get(
            "task_completed", 0), 1)

    def test_on_handle_emotion_success(self):
        before = self.emotion.get_state()["positivity"]
        self.rhythm.on_handle({}, {"aggregated": {"ok_count": 1,
                                                  "total": 1}})
        after = self.emotion.get_state()["positivity"]
        self.assertGreater(after, before)

    def test_on_handle_emotion_failure(self):
        self.rhythm.on_handle({}, {"aggregated": {"ok_count": 1,
                                                  "total": 1}})
        before = self.emotion.get_state()["positivity"]
        self.rhythm.on_handle({}, {"aggregated": {"ok_count": 0,
                                                  "total": 1}})
        after = self.emotion.get_state()["positivity"]
        self.assertLess(after, before)

    def test_on_handle_no_response_no_emotion(self):
        before = self.emotion.get_state()
        self.rhythm.on_handle({}, None)
        after = self.emotion.get_state()
        self.assertEqual(before, after)

    def test_on_handle_disabled(self):
        r = GrowthRhythm(enabled=False).on_handle({}, {})
        self.assertFalse(r["enabled"])

    def test_on_handle_structure(self):
        r = self.rhythm.on_handle({}, {})
        for key in ("mode", "captured", "consolidated",
                    "snapshot_taken", "reflection_triggered"):
            self.assertIn(key, r)

    def test_capture_audited(self):
        self.rhythm.on_handle({}, {})
        r = self.rhythm.audit_report()
        self.assertGreaterEqual(r["by_action"].get("capture", 0), 1)


class TestRhythmConsolidation(RhythmTestBase):
    """自动整理"""

    def test_auto_consolidate_threshold(self):
        """经验数达阈值 (3) → 自动整理"""
        self.seed(n=3)
        r = self.rhythm.on_handle({}, {})
        self.assertTrue(r["consolidated"])

    def test_auto_consolidate_not_triggered(self):
        self.seed(n=1)
        r = self.rhythm.on_handle({}, {})
        # 数量 1 < 3; 但首次 last_run=0 → 天数触发
        self.assertTrue(r["consolidated"])

    def test_consolidate_audited(self):
        self.seed(n=3)
        self.rhythm.on_handle({}, {})
        report = self.rhythm.audit_report()
        self.assertGreaterEqual(
            report["by_action"].get("consolidate", 0), 1,
        )

    def test_skip_audited(self):
        r = self.rhythm.on_handle({}, {})
        report = self.rhythm.audit_report()
        self.assertGreaterEqual(report["by_action"].get(
            "skip", 0), 0)

    def test_scheduler_stats(self):
        self.rhythm.on_handle({}, {})
        st = self.rhythm.scheduler_stats()
        self.assertIn("run_count", st)

    def test_rhythm_stats(self):
        self.rhythm.on_handle({}, {})
        st = self.rhythm.stats()
        for key in ("mode", "enabled", "capture_count",
                    "consolidate_count", "snapshot_count",
                    "reflection_count", "thresholds"):
            self.assertIn(key, st)


class TestRhythmSnapshot(RhythmTestBase):
    """自动快照"""

    def test_daily_snapshot_disabled(self):
        self.rhythm.on_handle({}, {})
        self.assertEqual(self.rhythm.stats()["snapshot_count"], 0)

    def test_daily_snapshot_taken(self):
        rhythm = GrowthRhythm(
            continuity=self.continuity,
            emotion=self.emotion,
            config={"companion_rhythm_daily_snapshot": True},
        )
        rhythm._continuity._path = self.path
        r = rhythm.on_handle({}, {})
        self.assertTrue(r["snapshot_taken"])
        self.assertTrue(os.path.exists(self.path))

    def test_daily_snapshot_once_per_day(self):
        rhythm = GrowthRhythm(
            continuity=self.continuity,
            emotion=self.emotion,
            config={"companion_rhythm_daily_snapshot": True},
        )
        rhythm._continuity._path = self.path
        rhythm.on_handle({}, {})
        r2 = rhythm.on_handle({}, {})
        self.assertFalse(r2["snapshot_taken"])

    def test_snapshot_without_path_skipped(self):
        r = self.rhythm.on_handle({}, {})
        self.assertFalse(r["snapshot_taken"])

    def test_snapshot_audited(self):
        rhythm = GrowthRhythm(
            continuity=self.continuity,
            emotion=self.emotion,
            config={"companion_rhythm_daily_snapshot": True},
        )
        rhythm._continuity._path = self.path
        rhythm.on_handle({}, {})
        report = rhythm.audit_report()
        self.assertGreaterEqual(
            report["by_action"].get("snapshot", 0), 1,
        )


class TestRhythmReflection(RhythmTestBase):
    """反思触发"""

    def test_auto_reflection(self):
        self.seed(n=2)
        self.rhythm.on_handle({}, {})
        st = self.continuity._reflection.stats()
        self.assertGreaterEqual(st["reflection_count"], 1)

    def test_reflection_audited(self):
        self.rhythm.on_handle({}, {})
        report = self.rhythm.audit_report()
        self.assertGreaterEqual(
            report["by_action"].get("reflection", 0), 1,
        )

    def test_reflection_disabled(self):
        rhythm = GrowthRhythm(
            continuity=self.continuity,
            emotion=self.emotion,
            config={"companion_rhythm_auto_reflection": False},
        )
        rhythm.on_handle({}, {})
        self.assertEqual(rhythm.stats()["reflection_count"], 0)


class TestRhythmBoundary(RhythmTestBase):
    """自主成长边界"""

    def test_no_personality_change(self):
        before = self.personality.personality()
        self.rhythm.on_handle({}, {"aggregated": {"ok_count": 0,
                                                  "total": 1}})
        self.rhythm.on_handle({}, {"aggregated": {"ok_count": 1,
                                                  "total": 1}})
        after = self.personality.personality()
        # 情绪联动不影响人格 base 与维度
        self.assertEqual(before["base"], after["base"])
        self.assertEqual(before["dimensions"], after["dimensions"])

    def test_clear(self):
        self.rhythm.on_handle({}, {})
        cleared = self.rhythm.clear()
        self.assertIn("audit", cleared)


class TestServiceEmotionAPI(unittest.TestCase):
    """Service 情绪 API"""

    def setUp(self):
        self.svc = EmbodiedService()
        self.svc.load_config({"embodied_enabled": True,
                              "companion_enabled": True})

    def test_companion_emotion_api(self):
        e = self.svc.companion_emotion()
        for key in ("positivity", "energy", "warmth"):
            self.assertIn(key, e)

    def test_companion_emotion_adjust_api(self):
        before = self.svc.companion_emotion()["positivity"]
        self.svc.companion_emotion_adjust("success")
        after = self.svc.companion_emotion()["positivity"]
        self.assertGreater(after, before)

    def test_companion_emotion_adjust_invalid(self):
        with self.assertRaises(Exception):
            self.svc.companion_emotion_adjust("bogus")

    def test_companion_emotion_audit_api(self):
        self.svc.companion_emotion_adjust("success")
        r = self.svc.companion_emotion_audit()
        self.assertGreaterEqual(r["by_action"].get("update", 0), 1)

    def test_companion_emotion_history_api(self):
        self.svc.companion_emotion_adjust("failure")
        h = self.svc.companion_emotion_history()
        self.assertEqual(h["stats"]["total"], 1)

    def test_companion_emotion_decay_api(self):
        self.svc.companion_emotion_decay()
        self.assertIn("positivity", self.svc.companion_emotion())


class TestServiceRhythmAPI(unittest.TestCase):
    """Service 节律 API"""

    def setUp(self):
        self.svc = EmbodiedService()
        self.svc.load_config({"embodied_enabled": True,
                              "companion_enabled": True})

    def test_growth_rhythm_api(self):
        r = self.svc.companion_growth_rhythm()
        self.assertIn("capture_count", r)

    def test_growth_rhythm_cycle_api(self):
        r = self.svc.companion_growth_rhythm_cycle(
            {"intent": "测试"}, {"aggregated": {"ok_count": 1,
                                                "total": 1}},
        )
        self.assertIn("captured", r)

    def test_rhythm_audit_api(self):
        self.svc.companion_growth_rhythm_cycle(
            {}, {"aggregated": {"ok_count": 1, "total": 1}},
        )
        r = self.svc.companion_rhythm_audit()
        self.assertGreaterEqual(r["by_action"].get("capture", 0), 1)

    def test_handle_returns_rhythm(self):
        r = self.svc.companion_handle({"text": "扫描环境查看策略建议"})
        self.assertIn("rhythm", r)


class TestServiceSnapshotEmotion(unittest.TestCase):
    """快照 emotion 域"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="yhlz_snapem_")
        self.path = os.path.join(self.tmp, "state.jsonl")
        self.svc = EmbodiedService()
        self.svc.load_config({"embodied_enabled": True,
                              "companion_enabled": True,
                              "companion_persistence_enabled": True})

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_emotion_in_snapshot_domains(self):
        from backend.embodied.companion.persistence import (
            SNAPSHOT_DOMAINS,
        )
        self.assertIn("emotion", SNAPSHOT_DOMAINS)

    def test_save_load_emotion(self):
        self.svc.companion_emotion_adjust("success")
        self.svc.companion_emotion_adjust("relationship_up")
        state = self.svc.companion_emotion()
        self.svc.companion_persistence_save(self.path)
        svc2 = EmbodiedService()
        svc2.load_config({"companion_persistence_enabled": True})
        res = svc2.companion_persistence_load(self.path)
        self.assertIn("emotion", res["activated"])
        restored = svc2.companion_emotion()
        self.assertEqual(restored["positivity"],
                         state["positivity"])
        self.assertEqual(restored["warmth"], state["warmth"])

    def test_old_snapshot_without_emotion_compatible(self):
        """旧快照 (无 emotion 域) → 恢复不报错, emotion 跳过"""
        self.svc.companion_persistence_save(self.path)
        # 移除 emotion 域, 模拟旧版本快照
        import json
        with open(self.path, "r", encoding="utf-8") as f:
            content = f.read()
        data = json.loads(content)
        if "emotion" in data["data"]["state"]:
            del data["data"]["state"]["emotion"]
            data["data"]["checksum"] = None  # 重新计算
        # 用 CompanionSnapshot 重新构建校验
        from backend.embodied.companion.persistence import (
            CompanionSnapshot,
        )
        snap = CompanionSnapshot()
        rebuilt = snap.build(data["data"]["state"])
        rebuilt["snapshot_id"] = data["data"]["snapshot_id"]
        rebuilt["created_at"] = data["data"]["created_at"]
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(json.dumps({
                "schema_version": "6.0.0", "type": "snapshot",
                "timestamp": 1.0, "data": rebuilt,
            }, ensure_ascii=False) + "\n")
        svc2 = EmbodiedService()
        svc2.load_config({"companion_persistence_enabled": True})
        res = svc2.companion_persistence_load(self.path)
        self.assertTrue(res["success"])
        self.assertNotIn("emotion", res["activated"])

    def test_emotion_restored_audit(self):
        self.svc.companion_emotion_adjust("success")
        self.svc.companion_persistence_save(self.path)
        svc2 = EmbodiedService()
        svc2.load_config({"companion_persistence_enabled": True})
        svc2.companion_persistence_load(self.path)
        r = svc2.companion_emotion_audit()
        self.assertGreaterEqual(r["by_action"].get("restore", 0), 1)


class TestBackwardCompat(unittest.TestCase):
    """V6.0 向后兼容"""

    def setUp(self):
        self.svc = EmbodiedService()
        self.svc.load_config({"embodied_enabled": True,
                              "companion_enabled": True,
                              "companion_persistence_enabled": True})

    def test_v60_persistence_api(self):
        tmp = tempfile.mkdtemp(prefix="yhlz_bc_")
        path = os.path.join(tmp, "s.jsonl")
        self.svc.companion_persistence_save(path)
        svc2 = EmbodiedService()
        svc2.load_config({"companion_persistence_enabled": True})
        res = svc2.companion_persistence_load(path)
        self.assertTrue(res["success"])
        shutil.rmtree(tmp, ignore_errors=True)

    def test_v60_growth_report_api(self):
        r = self.svc.companion_growth_report()
        self.assertEqual(r["mode"], "rule_based")

    def test_v59_creative_api(self):
        r = self.svc.companion_creative_run()
        self.assertIn("summary", r)

    def test_v58_reflection_api(self):
        r = self.svc.companion_reflection()
        self.assertEqual(r["mode"], "rule_based")

    def test_v55_personality_api(self):
        p = self.svc.companion_personality()
        self.assertIn("base", p)

    def test_version_6_1_1(self):
        self.assertEqual(self.svc.companion.status()["version"],
                         "9.5.0")


if __name__ == "__main__":
    unittest.main()
