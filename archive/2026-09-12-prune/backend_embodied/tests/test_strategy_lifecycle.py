"""
YHLZ Embodied AI V4.4 - 策略生命周期管理单元测试 (Policy Lifecycle)

覆盖:
    - 状态机: active / degraded / stale / archived (effective_status)
    - 版本化: upsert_version (v1 → v2, 旧版本入历史, 统计独立)
    - policy_history: 版本历史查询 (最旧 → 最新)
    - 归档/恢复: archive_policy / restore_policy (不是删除)
    - 老化: evaluate_aging (max_age_days → stale, 不参与候选)
    - 恢复机制: 连续采纳+成功 → 自动恢复 active
    - 候选筛选: candidates 排除 stale / archived / degraded
    - 持久化: 版本历史 JSONL 还原
"""
import os
import tempfile
import time
import unittest

from backend.embodied.experience.policy import (
    POLICY_STATUS_ARCHIVED,
    POLICY_STATUS_DEGRADED,
    POLICY_STATUS_STALE,
    ExperiencePolicy,
    PolicyTable,
    PolicyTableError,
)


def make_policy(trigger="t", strategy="s", kind="failure", action_type="pick",
                scene="", goal_type="", version=1):
    return ExperiencePolicy.create(
        trigger=trigger, strategy=strategy, kind=kind,
        action_type=action_type, scene=scene, goal_type=goal_type,
        version=version,
    )


class TestStatusMachine(unittest.TestCase):

    def test_default_active(self):
        p = make_policy()
        self.assertEqual(p.effective_status, "active")
        self.assertFalse(p.degraded)

    def test_set_status_degraded_sync(self):
        p = make_policy()
        p.set_status("degraded")
        self.assertTrue(p.degraded)
        self.assertEqual(p.effective_status, "degraded")

    def test_set_status_invalid_raises(self):
        p = make_policy()
        with self.assertRaises(PolicyTableError):
            p.set_status("unknown")

    def test_effective_status_fallback(self):
        p = make_policy()
        p.status = "unknown"
        self.assertEqual(p.effective_status, "active")

    def test_to_dict_status(self):
        p = make_policy()
        p.set_status("archived")
        d = p.to_dict()
        self.assertEqual(d["status"], "archived")
        self.assertTrue(d["degraded"] is False)

    def test_from_dict_legacy_degraded(self):
        """V4.3 旧数据: degraded=True → status=degraded"""
        d = make_policy().to_dict()
        d.pop("status")
        d["degraded"] = True
        p = ExperiencePolicy.from_dict(d)
        self.assertEqual(p.effective_status, "degraded")

    def test_last_activity_at(self):
        p = make_policy()
        p.created_at = 100.0
        p.updated_at = 200.0
        p.last_accepted_at = 300.0
        self.assertEqual(p.last_activity_at, 300.0)


class TestVersioning(unittest.TestCase):

    def setUp(self):
        self.table = PolicyTable()

    def test_upsert_version_creates_v2(self):
        self.table.upsert(trigger="t", strategy="s1", action_sequence=[{"action_type": "move"}])
        p2 = self.table.upsert_version(
            trigger="t", strategy="s2",
            action_sequence=[{"action_type": "scan"}, {"action_type": "move"}],
        )
        self.assertEqual(p2.version, 2)
        self.assertEqual(self.table.get("t").version, 2)
        self.assertEqual(self.table.get("t").strategy, "s2")

    def test_old_version_in_history(self):
        self.table.upsert(trigger="t", strategy="s1")
        self.table.upsert_version(trigger="t", strategy="s2")
        history = self.table.policy_history("t")
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["version"], 1)
        self.assertEqual(history[1]["version"], 2)

    def test_old_version_archived(self):
        self.table.upsert(trigger="t", strategy="s1")
        self.table.upsert_version(trigger="t", strategy="s2")
        history = self.table.policy_history("t")
        self.assertEqual(history[0]["status"], "archived")

    def test_new_version_stats_independent(self):
        p1 = self.table.upsert(trigger="t", strategy="s1")
        self.table.record_suggested("t")
        self.table.record_accepted("t", success=True)
        p2 = self.table.upsert_version(trigger="t", strategy="s2")
        self.assertEqual(p2.suggest_count, 0)
        self.assertEqual(p2.accepted_count, 0)
        self.assertEqual(p1.suggest_count, 1)  # 旧版本统计保留

    def test_version_source_goal_ids_carried(self):
        self.table.upsert(trigger="t", strategy="s1", source_goal_id="g-1")
        p2 = self.table.upsert_version(trigger="t", strategy="s2", source_goal_id="g-2")
        self.assertIn("g-1", p2.source_goal_ids)
        self.assertIn("g-2", p2.source_goal_ids)

    def test_version_three_versions(self):
        self.table.upsert(trigger="t", strategy="s1")
        self.table.upsert_version(trigger="t", strategy="s2")
        self.table.upsert_version(trigger="t", strategy="s3")
        history = self.table.policy_history("t")
        self.assertEqual([h["version"] for h in history], [1, 2, 3])
        self.assertEqual(self.table.get("t").version, 3)

    def test_upsert_merge_keeps_version(self):
        self.table.upsert(trigger="t", strategy="s1")
        self.table.upsert(trigger="t", strategy="s1")
        self.assertEqual(self.table.get("t").version, 1)

    def test_upsert_version_new_trigger_v1(self):
        p = self.table.upsert_version(trigger="new", strategy="s")
        self.assertEqual(p.version, 1)

    def test_history_unknown_trigger(self):
        self.assertEqual(self.table.policy_history("nope"), [])


class TestArchiveRestore(unittest.TestCase):

    def setUp(self):
        self.table = PolicyTable()

    def test_archive(self):
        self.table.upsert(trigger="t", strategy="s")
        p = self.table.archive_policy("t")
        self.assertIsNotNone(p)
        self.assertEqual(p.effective_status, POLICY_STATUS_ARCHIVED)
        self.assertGreater(p.archived_at, 0)

    def test_archive_unknown_returns_none(self):
        self.assertIsNone(self.table.archive_policy("nope"))

    def test_archive_is_not_delete(self):
        self.table.upsert(trigger="t", strategy="s")
        self.table.archive_policy("t")
        self.assertEqual(self.table.count(), 1)  # 不是删除

    def test_archive_idempotent(self):
        self.table.upsert(trigger="t", strategy="s")
        self.table.archive_policy("t")
        self.table.archive_policy("t")
        self.assertEqual(self.table.count(), 1)

    def test_restore(self):
        self.table.upsert(trigger="t", strategy="s")
        self.table.archive_policy("t")
        p = self.table.restore_policy("t")
        self.assertEqual(p.effective_status, "active")
        self.assertEqual(p.archived_at, 0.0)

    def test_restore_unknown_returns_none(self):
        self.assertIsNone(self.table.restore_policy("nope"))

    def test_archived_not_in_candidates(self):
        self.table.upsert(trigger="t", strategy="s", action_type="pick")
        self.table.archive_policy("t")
        self.assertEqual(self.table.candidates(action_type="pick"), [])

    def test_restored_in_candidates(self):
        self.table.upsert(trigger="t", strategy="s", action_type="pick")
        self.table.archive_policy("t")
        self.table.restore_policy("t")
        self.assertEqual(len(self.table.candidates(action_type="pick")), 1)


class TestAging(unittest.TestCase):

    def setUp(self):
        self.table = PolicyTable()

    def test_stale_after_max_age(self):
        p = self.table.upsert(trigger="t", strategy="s")
        p.created_at = 0.0
        p.updated_at = 0.0
        p.last_suggested_at = 0.0
        p.last_accepted_at = 0.0
        now = 40 * 86400.0  # 40 天前创建
        aged = self.table.evaluate_aging(max_age_days=30, now=now)
        self.assertEqual(aged, ["t"])
        self.assertEqual(self.table.get("t").effective_status, POLICY_STATUS_STALE)

    def test_active_within_age(self):
        p = self.table.upsert(trigger="t", strategy="s")
        p.created_at = 10 * 86400.0
        now = 40 * 86400.0
        aged = self.table.evaluate_aging(max_age_days=30, now=now)
        self.assertEqual(aged, [])
        self.assertEqual(self.table.get("t").effective_status, "active")

    def test_recent_activity_prevents_stale(self):
        p = self.table.upsert(trigger="t", strategy="s")
        p.created_at = 0.0
        p.last_suggested_at = now = 40 * 86400.0 - 3600  # 1 小时前仍在使用
        aged = self.table.evaluate_aging(max_age_days=30, now=40 * 86400.0)
        self.assertEqual(aged, [])

    def test_stale_not_in_candidates(self):
        self.table.upsert(trigger="t", strategy="s", action_type="pick")
        p = self.table.get("t")
        p.created_at = 0.0
        p.updated_at = 0.0
        self.table.evaluate_aging(max_age_days=1, now=40 * 86400.0)
        self.assertEqual(self.table.candidates(action_type="pick"), [])

    def test_archived_skips_aging(self):
        self.table.upsert(trigger="t", strategy="s")
        p = self.table.get("t")
        p.created_at = 0.0
        p.updated_at = 0.0
        self.table.archive_policy("t")
        aged = self.table.evaluate_aging(max_age_days=1, now=40 * 86400.0)
        self.assertEqual(aged, [])
        self.assertEqual(self.table.get("t").effective_status, POLICY_STATUS_ARCHIVED)

    def test_aging_invalid_days(self):
        with self.assertRaises(PolicyTableError):
            self.table.evaluate_aging(max_age_days=0)


class TestRecovery(unittest.TestCase):

    def setUp(self):
        self.table = PolicyTable()

    def test_recovery_streak_increments_on_success(self):
        p = self.table.upsert(trigger="t", strategy="s")
        p.set_status("degraded")
        self.table.record_accepted("t", success=True)
        self.table.record_accepted("t", success=True)
        self.assertEqual(self.table.get("t").recovery_streak, 2)

    def test_recovery_streak_resets_on_failure(self):
        p = self.table.upsert(trigger="t", strategy="s")
        p.set_status("degraded")
        self.table.record_accepted("t", success=True)
        self.table.record_accepted("t", success=False)
        self.assertEqual(self.table.get("t").recovery_streak, 0)

    def test_recovery_restores_active(self):
        p = self.table.upsert(trigger="t", strategy="s")
        p.set_status("degraded")
        for _ in range(3):
            self.table.record_accepted("t", success=True)
        recovered = self.table.evaluate_recovery(recovery_threshold=3)
        self.assertEqual(recovered, ["t"])
        self.assertEqual(self.table.get("t").effective_status, "active")

    def test_recovery_below_threshold(self):
        p = self.table.upsert(trigger="t", strategy="s")
        p.set_status("degraded")
        self.table.record_accepted("t", success=True)
        self.table.record_accepted("t", success=True)
        self.assertEqual(
            self.table.evaluate_recovery(recovery_threshold=3), []
        )
        self.assertEqual(self.table.get("t").effective_status, "degraded")

    def test_active_policy_not_affected(self):
        self.table.upsert(trigger="t", strategy="s")
        self.table.record_accepted("t", success=True)
        self.assertEqual(self.table.get("t").recovery_streak, 0)
        self.assertEqual(self.table.evaluate_recovery(recovery_threshold=1), [])

    def test_recovery_invalid_threshold(self):
        with self.assertRaises(PolicyTableError):
            self.table.evaluate_recovery(recovery_threshold=0)


class TestCandidates(unittest.TestCase):

    def setUp(self):
        self.table = PolicyTable()

    def test_scene_dimension(self):
        self.table.upsert(trigger="room_pick", strategy="s1", kind="failure",
                          action_type="pick", scene="room")
        self.table.upsert(trigger="wh_pick", strategy="s2", kind="failure",
                          action_type="pick", scene="warehouse")
        self.table.upsert(trigger="global_pick", strategy="s3", kind="failure",
                          action_type="pick")
        room = self.table.candidates(action_type="pick", scene="room")
        self.assertEqual({p.trigger for p in room},
                         {"room_pick", "global_pick"})
        wh = self.table.candidates(action_type="pick", scene="warehouse")
        self.assertEqual({p.trigger for p in wh},
                         {"wh_pick", "global_pick"})

    def test_goal_type_dimension(self):
        self.table.upsert(trigger="pick_pol", strategy="s", kind="failure",
                          action_type="pick", goal_type="pick")
        self.table.upsert(trigger="move_pol", strategy="s", kind="failure",
                          action_type="move", goal_type="move")
        cands = self.table.candidates(kind="failure", goal_type="pick")
        self.assertEqual([p.trigger for p in cands], ["pick_pol"])

    def test_global_policy_matches_all(self):
        self.table.upsert(trigger="g", strategy="s", kind="failure", action_type="pick")
        self.assertEqual(len(self.table.candidates(
            action_type="pick", scene="warehouse", goal_type="pick")), 1)

    def test_kind_filter(self):
        self.table.upsert(trigger="f", strategy="s", kind="failure")
        self.table.upsert(trigger="r", strategy="s", kind="success")
        self.assertEqual(len(self.table.candidates(kind="success")), 1)

    def test_include_degraded_flag(self):
        p = self.table.upsert(trigger="t", strategy="s")
        p.set_status("degraded")
        self.assertEqual(self.table.candidates(), [])
        self.assertEqual(len(self.table.candidates(include_degraded=True)), 1)

    def test_by_status_query(self):
        self.table.upsert(trigger="a", strategy="s")
        p = self.table.upsert(trigger="d", strategy="s")
        p.set_status("archived")
        self.assertEqual(
            [x.trigger for x in self.table.by_status("active")], ["a"]
        )
        self.assertEqual(
            [x.trigger for x in self.table.by_status("archived")], ["d"]
        )

    def test_stats_status_counts(self):
        self.table.upsert(trigger="a", strategy="s")
        p = self.table.upsert(trigger="d", strategy="s")
        p.set_status("stale")
        stats = self.table.stats()
        self.assertEqual(stats["status_counts"]["active"], 1)
        self.assertEqual(stats["status_counts"]["stale"], 1)
        self.assertEqual(stats["version_total"], 2)


class TestLifecyclePersistence(unittest.TestCase):

    def test_version_history_save_load(self):
        table = PolicyTable()
        table.upsert(trigger="t", strategy="s1")
        table.upsert_version(trigger="t", strategy="s2")
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "policy_v.jsonl")
            self.assertEqual(table.save_to_file(path), 2)
            table2 = PolicyTable()
            self.assertEqual(table2.load_from_file(path), 2)
            self.assertEqual(table2.get("t").version, 2)
            self.assertEqual(table2.get("t").strategy, "s2")
            history = table2.policy_history("t")
            self.assertEqual([h["version"] for h in history], [1, 2])

    def test_save_load_status_preserved(self):
        table = PolicyTable()
        table.upsert(trigger="t", strategy="s")
        table.archive_policy("t")
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "policy_s.jsonl")
            table.save_to_file(path)
            table2 = PolicyTable()
            table2.load_from_file(path)
            self.assertEqual(
                table2.get("t").effective_status, POLICY_STATUS_ARCHIVED
            )

    def test_save_load_v43_legacy(self):
        """V4.3 旧文件 (无 status 字段) 兼容加载"""
        table = PolicyTable()
        table.upsert(trigger="t", strategy="s")
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "legacy.jsonl")
            table.save_to_file(path)
            with open(path, "r", encoding="utf-8") as f:
                lines = f.read().splitlines()
            # 去掉 V4.4 新字段, 模拟旧格式
            import json
            d = json.loads(lines[0])
            for k in ("scene", "goal_type", "version", "status", "recovery_streak",
                      "last_suggested_at", "last_accepted_at", "archived_at"):
                d.pop(k, None)
            with open(path, "w", encoding="utf-8") as f:
                f.write(json.dumps(d) + "\n")
            table2 = PolicyTable()
            self.assertEqual(table2.load_from_file(path), 1)
            self.assertEqual(table2.get("t").effective_status, "active")
            self.assertEqual(table2.get("t").version, 1)


if __name__ == "__main__":
    unittest.main()
