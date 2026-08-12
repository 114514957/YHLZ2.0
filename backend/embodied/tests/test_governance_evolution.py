"""
YHLZ Embodied AI V4.5 - 策略体系进化单元测试 (Strategy Evolution)

覆盖 (Strategy Evolution):
    - 策略同化: consolidate_similar_policies
      不同 trigger 相同 action_sequence (success) / strategy+action_type (failure)
      → Policy Family (共享父级统计, 子策略保留独立历史)
    - 策略分裂: split_policy 按 scene / goal_type 拆分 (原策略归档, 新策略 active)
    - 版本比较: compare_policy_versions (healthy / regression 判定)
    - 策略回滚: rollback_policy (仅最新版本 regression 允许, 旧版本保留历史)

安全约束验证:
    - 治理动作只影响策略表 / 审计日志
    - 同化 / 分裂不修改策略内容 (只改变归属 / 状态)
    - 确定性 family_id (内容签名哈希)
"""
import unittest

from backend.embodied.experience.policy import (
    POLICY_STATUS_ACTIVE,
    POLICY_STATUS_ARCHIVED,
    ExperiencePolicy,
    PolicyTable,
)
from backend.embodied.governance import (
    EvolutionError,
    PolicyEvolution,
)
from backend.embodied.strategy.audit import PolicyAuditLog


class TestConsolidate(unittest.TestCase):
    """策略同化: 不同 trigger 相同内容 → Policy Family"""

    def setUp(self):
        self.table = PolicyTable()
        self.audit = PolicyAuditLog()
        self.evo = PolicyEvolution(self.table, self.audit)

    def test_no_family_when_alone(self):
        """单策略 → 无 family"""
        self.table.upsert(trigger="a", strategy="s", kind="success",
                          action_sequence=[{"action_type": "pick"}])
        r = self.evo.consolidate_similar_policies(dry_run=True)
        self.assertEqual(r["total"], 0)

    def test_success_same_sequence_forms_family(self):
        """不同 trigger 相同 success action_sequence → 形成 Family"""
        self.table.upsert(trigger="a", strategy="s1", kind="success",
                          scene="room",
                          action_sequence=[{"action_type": "pick"},
                                           {"action_type": "place"}])
        self.table.upsert(trigger="b", strategy="s2", kind="success",
                          scene="warehouse",
                          action_sequence=[{"action_type": "pick"},
                                           {"action_type": "place"}])
        r = self.evo.consolidate_similar_policies(dry_run=True)
        self.assertEqual(r["total"], 1)
        fam = r["families"][0]
        self.assertEqual(fam["kind"], "success")
        self.assertEqual(fam["member_count"], 2)
        self.assertTrue(fam["family_id"].startswith("fam_"))

    def test_success_different_sequence_not_family(self):
        """不同 action_sequence → 不形成 Family"""
        self.table.upsert(trigger="a", strategy="s", kind="success",
                          action_sequence=[{"action_type": "pick"}])
        self.table.upsert(trigger="b", strategy="s", kind="success",
                          action_sequence=[{"action_type": "scan"}])
        r = self.evo.consolidate_similar_policies(dry_run=True)
        self.assertEqual(r["total"], 0)

    def test_failure_same_strategy_forms_family(self):
        """不同 trigger 相同 failure strategy+action_type → 形成 Family"""
        self.table.upsert(trigger="a", strategy="scan_first", kind="failure",
                          action_type="pick", scene="room")
        self.table.upsert(trigger="b", strategy="scan_first", kind="failure",
                          action_type="pick", scene="warehouse")
        r = self.evo.consolidate_similar_policies(dry_run=True)
        self.assertEqual(r["total"], 1)
        self.assertEqual(r["families"][0]["kind"], "failure")

    def test_execute_sets_family_id(self):
        """执行同化 → family_id 写入策略表 + 审计"""
        self.table.upsert(trigger="a", strategy="s", kind="success",
                          action_sequence=[{"action_type": "pick"}])
        self.table.upsert(trigger="b", strategy="s", kind="success",
                          action_sequence=[{"action_type": "pick"}])
        r = self.evo.consolidate_similar_policies(dry_run=False)
        self.assertEqual(r["total"], 1)
        fid = r["families"][0]["family_id"]
        self.assertEqual(self.table.get("a").family_id, fid)
        self.assertEqual(self.table.get("b").family_id, fid)
        log = self.audit.audit_policy_log(limit=0, action="consolidate")
        self.assertEqual(log["total"], 2)

    def test_dry_run_no_side_effect(self):
        """dry_run=True → 不写 family_id, 不写审计"""
        self.table.upsert(trigger="a", strategy="s", kind="success",
                          action_sequence=[{"action_type": "pick"}])
        self.table.upsert(trigger="b", strategy="s", kind="success",
                          action_sequence=[{"action_type": "pick"}])
        r = self.evo.consolidate_similar_policies(dry_run=True)
        self.assertTrue(r["dry_run"])
        self.assertEqual(self.table.get("a").family_id, "")
        self.assertEqual(self.audit.count(), 0)

    def test_archived_not_involved(self):
        """归档策略不参与同化"""
        self.table.upsert(trigger="a", strategy="s", kind="success",
                          action_sequence=[{"action_type": "pick"}])
        self.table.upsert(trigger="b", strategy="s", kind="success",
                          action_sequence=[{"action_type": "pick"}])
        self.table.archive_policy("b")
        r = self.evo.consolidate_similar_policies(dry_run=True)
        self.assertEqual(r["total"], 0)

    def test_parent_stats_aggregated(self):
        """父级统计 = 成员聚合 (suggest/accepted/success/hit_rate)"""
        a = self.table.upsert(trigger="a", strategy="s", kind="success",
                              action_sequence=[{"action_type": "pick"}])
        b = self.table.upsert(trigger="b", strategy="s", kind="success",
                              action_sequence=[{"action_type": "pick"}])
        a.suggest_count, a.accepted_count, a.success_count = 10, 8, 6
        b.suggest_count, b.accepted_count, b.success_count = 5, 2, 2
        r = self.evo.consolidate_similar_policies(dry_run=True)
        ps = r["families"][0]["parent_stats"]
        self.assertEqual(ps["suggest_count"], 15)
        self.assertEqual(ps["accepted_count"], 10)
        self.assertEqual(ps["success_count"], 8)
        self.assertEqual(ps["hit_rate"], 0.8)
        self.assertEqual(ps["acceptance_rate"], round(10 / 15, 4))

    def test_deterministic_family_id(self):
        """同内容 → 确定性 family_id (两次一致)"""
        self.table.upsert(trigger="a", strategy="s", kind="success",
                          action_sequence=[{"action_type": "pick"}])
        self.table.upsert(trigger="b", strategy="s", kind="success",
                          action_sequence=[{"action_type": "pick"}])
        r1 = self.evo.consolidate_similar_policies(dry_run=True)
        self.table.clear()
        self.table.upsert(trigger="x", strategy="s", kind="success",
                          action_sequence=[{"action_type": "pick"}])
        self.table.upsert(trigger="y", strategy="s", kind="success",
                          action_sequence=[{"action_type": "pick"}])
        r2 = self.evo.consolidate_similar_policies(dry_run=True)
        self.assertEqual(r1["families"][0]["family_id"],
                         r2["families"][0]["family_id"])


class TestSplitPolicy(unittest.TestCase):
    """策略分裂: 按 scene / goal_type 拆分"""

    def setUp(self):
        self.table = PolicyTable()
        self.audit = PolicyAuditLog()
        self.evo = PolicyEvolution(self.table, self.audit)

    def _seed(self, trigger="pick_object"):
        return self.table.upsert(
            trigger=trigger, strategy="scan_then_pick", kind="failure",
            action_type="pick", scene="room", goal_type="pick",
            source_goal_id="g-1",
        )

    def test_invalid_by_raises(self):
        """by 非法 → EvolutionError"""
        self._seed()
        with self.assertRaises(EvolutionError):
            self.evo.split_policy("pick_object", by="axis", values=["a"])

    def test_empty_values_raises(self):
        """values 为空 → EvolutionError"""
        self._seed()
        with self.assertRaises(EvolutionError):
            self.evo.split_policy("pick_object", by="scene", values=[])

    def test_duplicate_values_raises(self):
        """values 重复 → EvolutionError"""
        self._seed()
        with self.assertRaises(EvolutionError):
            self.evo.split_policy("pick_object", by="scene",
                                  values=["a", "a"])

    def test_missing_policy_raises(self):
        """策略不存在 → EvolutionError"""
        with self.assertRaises(EvolutionError):
            self.evo.split_policy("nope", by="scene", values=["a"])

    def test_dry_run_lists_created(self):
        """dry_run=True → 返回将创建清单, 不修改状态"""
        self._seed()
        r = self.evo.split_policy("pick_object", by="scene",
                                  values=["warehouse", "home"], dry_run=True)
        self.assertTrue(r["dry_run"])
        self.assertEqual(r["total"], 2)
        triggers = [c["trigger"] for c in r["created"]]
        self.assertEqual(triggers, ["pick_object_warehouse", "pick_object_home"])
        self.assertEqual(r["created"][0]["scene"], "warehouse")
        self.assertEqual(r["created"][1]["scene"], "home")
        self.assertIsNone(self.table.get("pick_object_warehouse"))
        self.assertEqual(self.table.get("pick_object").effective_status,
                         POLICY_STATUS_ACTIVE)

    def test_execute_archives_original(self):
        """执行 → 原策略归档 + 新策略 active + 审计"""
        self._seed()
        r = self.evo.split_policy("pick_object", by="scene",
                                  values=["warehouse", "home"], dry_run=False)
        self.assertEqual(self.table.get("pick_object").effective_status,
                         POLICY_STATUS_ARCHIVED)
        w = self.table.get("pick_object_warehouse")
        h = self.table.get("pick_object_home")
        self.assertEqual(w.effective_status, POLICY_STATUS_ACTIVE)
        self.assertEqual(w.scene, "warehouse")
        self.assertEqual(w.strategy, "scan_then_pick")
        self.assertEqual(h.scene, "home")
        self.assertIn("g-1", w.source_goal_ids)
        log = self.audit.audit_policy_log(limit=0, action="split")
        self.assertEqual(log["total"], 1)

    def test_split_by_goal_type(self):
        """按 goal_type 拆分"""
        self._seed()
        r = self.evo.split_policy("pick_object", by="goal_type",
                                  values=["pick", "inspect"], dry_run=False)
        self.assertEqual(self.table.get("pick_object_pick").goal_type, "pick")
        self.assertEqual(self.table.get("pick_object_inspect").goal_type, "inspect")

    def test_target_trigger_conflict_raises(self):
        """目标 trigger 已存在 → EvolutionError"""
        self._seed()
        self.table.upsert(trigger="pick_object_home", strategy="x",
                          kind="failure", action_type="pick")
        with self.assertRaises(EvolutionError):
            self.evo.split_policy("pick_object", by="scene",
                                  values=["home"], dry_run=False)


class TestCompareVersions(unittest.TestCase):
    """版本比较: healthy / regression 判定"""

    def setUp(self):
        self.table = PolicyTable()
        self.audit = PolicyAuditLog()
        self.evo = PolicyEvolution(self.table, self.audit)

    def test_single_version_baseline(self):
        """单版本 → baseline"""
        self.table.upsert(trigger="t", strategy="s", kind="failure",
                          action_type="pick")
        r = self.evo.compare_policy_versions("t")
        self.assertEqual(r["latest_verdict"], "baseline")
        self.assertEqual(r["latest_version"], 1)
        self.assertEqual(r["versions"][0]["verdict"], "baseline")

    def test_missing_trigger_empty(self):
        """不存在的 trigger → 空版本列表"""
        r = self.evo.compare_policy_versions("nope")
        self.assertEqual(r["versions"], [])
        self.assertEqual(r["latest_version"], 0)

    def test_healthy_verdict(self):
        """当前 hit_rate >= 上一版本 → healthy"""
        self.table.upsert(trigger="t", strategy="s", kind="failure",
                          action_type="pick")
        self.table.upsert_version(trigger="t", strategy="s2", kind="failure",
                                  action_type="pick")
        v1, v2 = self.table.all_versions("t")
        v1.accepted_count, v1.success_count = 10, 5   # 0.5
        v2.accepted_count, v2.success_count = 10, 8   # 0.8
        r = self.evo.compare_policy_versions("t")
        self.assertEqual(r["latest_verdict"], "healthy")
        self.assertEqual([v["verdict"] for v in r["versions"]],
                         ["baseline", "healthy"])

    def test_regression_verdict(self):
        """当前 hit_rate < 上一版本 → regression"""
        self.table.upsert(trigger="t", strategy="s", kind="failure",
                          action_type="pick")
        self.table.upsert_version(trigger="t", strategy="s2", kind="failure",
                                  action_type="pick")
        v1, v2 = self.table.all_versions("t")
        v1.accepted_count, v1.success_count = 10, 9   # 0.9
        v2.accepted_count, v2.success_count = 10, 2   # 0.2
        r = self.evo.compare_policy_versions("t")
        self.assertEqual(r["latest_verdict"], "regression")

    def test_version_fields_present(self):
        """版本条目含 version/updated_at/action_sequence/hit_rate/
        acceptance_rate/source_goal_id"""
        self.table.upsert(trigger="t", strategy="s", kind="failure",
                          action_type="pick", source_goal_id="g-1")
        r = self.evo.compare_policy_versions("t")
        e = r["versions"][0]
        for key in ("version", "updated_at", "action_sequence", "hit_rate",
                    "acceptance_rate", "source_goal_id", "verdict"):
            self.assertIn(key, e)


class TestRollback(unittest.TestCase):
    """策略回滚: 仅最新版本 regression 允许"""

    def setUp(self):
        self.table = PolicyTable()
        self.audit = PolicyAuditLog()
        self.evo = PolicyEvolution(self.table, self.audit)

    def _seed_regression(self):
        self.table.upsert(trigger="t", strategy="good", kind="failure",
                          action_type="pick")
        self.table.upsert_version(trigger="t", strategy="bad", kind="failure",
                                  action_type="pick")
        v1, v2 = self.table.all_versions("t")
        v1.accepted_count, v1.success_count = 10, 9   # 0.9
        v2.accepted_count, v2.success_count = 10, 1   # 0.1 → regression

    def test_no_history_cannot_rollback(self):
        """无历史版本 → 不允许回滚"""
        self.table.upsert(trigger="t", strategy="s", kind="failure",
                          action_type="pick")
        r = self.evo.rollback_policy("t", dry_run=True)
        self.assertFalse(r["allowed"])
        self.assertIn("无历史版本", r["reason"])

    def test_healthy_latest_not_allowed(self):
        """最新版本 healthy → 禁止回滚"""
        self.table.upsert(trigger="t", strategy="s", kind="failure",
                          action_type="pick")
        self.table.upsert_version(trigger="t", strategy="s2", kind="failure",
                                  action_type="pick")
        v1, v2 = self.table.all_versions("t")
        v1.accepted_count, v1.success_count = 10, 2   # 0.2
        v2.accepted_count, v2.success_count = 10, 9   # 0.9 → healthy
        r = self.evo.rollback_policy("t", dry_run=True)
        self.assertFalse(r["allowed"])
        self.assertIn("未 regression", r["reason"])

    def test_regression_allowed_dry_run(self):
        """最新版本 regression → 允许回滚 (dry_run 不执行)"""
        self._seed_regression()
        r = self.evo.rollback_policy("t", dry_run=True)
        self.assertTrue(r["allowed"])
        self.assertEqual(r["would_rollback_to"], 1)
        self.assertEqual(self.table.get("t").version, 2)

    def test_regression_execute(self):
        """执行回滚 → 当前入历史 (archived), 上一版本升为 active"""
        self._seed_regression()
        r = self.evo.rollback_policy("t", dry_run=False)
        self.assertTrue(r["allowed"])
        self.assertEqual(r["rolled_to"], 1)
        by_version = {v.version: v for v in self.table.all_versions("t")}
        self.assertEqual(by_version[1].effective_status, POLICY_STATUS_ACTIVE)
        self.assertEqual(by_version[2].effective_status, POLICY_STATUS_ARCHIVED)
        log = self.audit.audit_policy_log(limit=0, action="rollback")
        self.assertEqual(log["total"], 1)

    def test_old_versions_keep_history(self):
        """回滚后旧版本保留历史 (可追溯)"""
        self._seed_regression()
        self.evo.rollback_policy("t", dry_run=False)
        self.assertEqual(len(self.table.all_versions("t")), 2)


if __name__ == "__main__":
    unittest.main()
