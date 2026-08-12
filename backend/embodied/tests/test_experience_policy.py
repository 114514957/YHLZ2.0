"""
YHLZ Embodied AI V4.3 - 经验策略表单元测试 (Experience Policy Table)

覆盖:
    - ExperiencePolicy: hit_rate / acceptance_rate / to_dict / from_dict / create
    - PolicyTable: upsert 新增与合并 (保留累计统计 + 来源去重)
    - PolicyTable: 查询 (get / all / by_kind / matching / recipe)
    - PolicyTable: 质量指标 (record_suggested / record_accepted)
    - PolicyTable: 自动降级 (从未采纳 / 命中率过低)
    - PolicyTable: JSONL 持久化 (save / load / 坏行跳过)
    - PolicyTable: 容量限制与清空
"""
import json
import os
import tempfile
import unittest

from backend.embodied.experience.policy import (
    ExperiencePolicy,
    PolicyTable,
    PolicyTableError,
)


class TestExperiencePolicy(unittest.TestCase):

    def test_hit_rate_zero_when_no_accept(self):
        p = ExperiencePolicy.create(trigger="t", strategy="s")
        self.assertEqual(p.hit_rate, 0.0)

    def test_hit_rate(self):
        p = ExperiencePolicy.create(trigger="t", strategy="s")
        p.accepted_count = 4
        p.success_count = 3
        self.assertEqual(p.hit_rate, 0.75)

    def test_acceptance_rate_zero(self):
        p = ExperiencePolicy.create(trigger="t", strategy="s")
        self.assertEqual(p.acceptance_rate, 0.0)

    def test_acceptance_rate(self):
        p = ExperiencePolicy.create(trigger="t", strategy="s")
        p.suggest_count = 10
        p.accepted_count = 4
        self.assertEqual(p.acceptance_rate, 0.4)

    def test_to_dict_fields(self):
        p = ExperiencePolicy.create(
            trigger="t", strategy="s", kind="failure",
            action_type="pick", cause="object_missing",
        )
        d = p.to_dict()
        self.assertEqual(d["trigger"], "t")
        self.assertEqual(d["hit_rate"], 0.0)
        self.assertFalse(d["degraded"])
        self.assertIn("policy_id", d)
        self.assertIn("created_at", d)

    def test_from_dict_roundtrip(self):
        p = ExperiencePolicy.create(
            trigger="t", strategy="s", kind="success",
            action_sequence=[{"action_type": "scan"}],
            preconditions=["permission_required"],
            source_goal_ids=["g-1"],
        )
        p.suggest_count = 5
        p.accepted_count = 2
        p.success_count = 1
        p.degraded = True
        r = ExperiencePolicy.from_dict(p.to_dict())
        self.assertEqual(r.trigger, "t")
        self.assertEqual(r.kind, "success")
        self.assertEqual(r.suggest_count, 5)
        self.assertTrue(r.degraded)
        self.assertEqual(r.action_sequence, [{"action_type": "scan"}])
        self.assertEqual(r.source_goal_ids, ["g-1"])

    def test_from_dict_empty(self):
        p = ExperiencePolicy.from_dict({})
        self.assertEqual(p.trigger, "")
        self.assertEqual(p.action_sequence, [])
        self.assertFalse(p.degraded)

    def test_create_defaults(self):
        p = ExperiencePolicy.create(trigger="t", strategy="s")
        self.assertEqual(p.kind, "failure")
        self.assertEqual(p.source_goal_ids, [])


class TestPolicyTableUpsert(unittest.TestCase):

    def setUp(self):
        self.table = PolicyTable()

    def test_upsert_new(self):
        p = self.table.upsert(
            trigger="pick_failure_location", strategy="scan_before_pick",
            kind="failure", detail="d", action_type="pick", cause="object_missing",
            required_action="scan", source_goal_id="g-1",
        )
        self.assertEqual(p.trigger, "pick_failure_location")
        self.assertEqual(self.table.count(), 1)
        self.assertEqual(p.source_goal_ids, ["g-1"])

    def test_upsert_empty_trigger_raises(self):
        with self.assertRaises(PolicyTableError):
            self.table.upsert(trigger="", strategy="s")

    def test_upsert_merge_keeps_stats(self):
        self.table.upsert(trigger="t", strategy="s1", source_goal_id="g-1")
        self.table.record_suggested("t")
        self.table.record_accepted("t", success=True)
        self.table.upsert(trigger="t", strategy="s2", source_goal_id="g-2")
        p = self.table.get("t")
        self.assertEqual(p.strategy, "s2")
        self.assertEqual(p.suggest_count, 1)
        self.assertEqual(p.accepted_count, 1)
        self.assertEqual(p.success_count, 1)
        self.assertEqual(p.source_goal_ids, ["g-1", "g-2"])

    def test_upsert_merge_source_dedup(self):
        self.table.upsert(trigger="t", strategy="s", source_goal_id="g-1")
        self.table.upsert(trigger="t", strategy="s", source_goal_id="g-1")
        p = self.table.get("t")
        self.assertEqual(p.source_goal_ids, ["g-1"])

    def test_upsert_merge_updates_action_type(self):
        self.table.upsert(trigger="t", strategy="s", action_type="pick")
        self.table.upsert(trigger="t", strategy="s2")
        p = self.table.get("t")
        self.assertEqual(p.action_type, "pick")  # 保留旧值
        self.assertEqual(p.strategy, "s2")

    def test_upsert_merge_replaces_sequence(self):
        self.table.upsert(trigger="t", strategy="s",
                          action_sequence=[{"action_type": "move"}])
        self.table.upsert(trigger="t", strategy="s",
                          action_sequence=[{"action_type": "scan"}])
        p = self.table.get("t")
        self.assertEqual(p.action_sequence, [{"action_type": "scan"}])

    def test_upsert_from_dict(self):
        d = {
            "trigger": "t2", "strategy": "s", "kind": "failure",
            "suggest_count": 3, "accepted_count": 1, "success_count": 1,
        }
        p = self.table.upsert_from_dict(d)
        self.assertEqual(p.trigger, "t2")
        self.assertEqual(p.suggest_count, 3)

    def test_upsert_from_dict_merges_stats(self):
        self.table.upsert_from_dict({
            "trigger": "t3", "strategy": "s",
            "suggest_count": 3, "accepted_count": 2, "success_count": 1,
        })
        self.table.upsert_from_dict({
            "trigger": "t3", "strategy": "s",
            "suggest_count": 2, "accepted_count": 1, "success_count": 0,
        })
        p = self.table.get("t3")
        self.assertEqual(p.suggest_count, 5)
        self.assertEqual(p.accepted_count, 3)
        self.assertEqual(p.success_count, 1)

    def test_max_policies_limit(self):
        table = PolicyTable(max_policies=2)
        table.upsert(trigger="a", strategy="s")
        table.upsert(trigger="b", strategy="s")
        with self.assertRaises(PolicyTableError):
            table.upsert(trigger="c", strategy="s")

    def test_max_policies_zero_raises(self):
        with self.assertRaises(PolicyTableError):
            PolicyTable(max_policies=0)

    def test_merge_existing_allowed_when_full(self):
        table = PolicyTable(max_policies=1)
        table.upsert(trigger="a", strategy="s")
        table.upsert(trigger="a", strategy="s2")  # 合并不超限
        self.assertEqual(table.count(), 1)


class TestPolicyTableQuery(unittest.TestCase):

    def setUp(self):
        self.table = PolicyTable()
        self.table.upsert(trigger="pf", strategy="scan_before_pick", kind="failure",
                          action_type="pick", cause="object_missing")
        self.table.upsert(trigger="ps", strategy="move_then_pick", kind="success",
                          action_sequence=[{"action_type": "move"}])

    def test_get_missing(self):
        self.assertIsNone(self.table.get("nope"))

    def test_all_sorted_by_created(self):
        table = PolicyTable()
        table.upsert(trigger="b", strategy="s")
        table.upsert(trigger="a", strategy="s")
        self.assertEqual([p.trigger for p in table.all()], ["b", "a"])

    def test_by_kind(self):
        failures = self.table.by_kind("failure")
        self.assertEqual([p.trigger for p in failures], ["pf"])
        successes = self.table.by_kind("success")
        self.assertEqual([p.trigger for p in successes], ["ps"])

    def test_matching_by_action_type(self):
        hits = self.table.matching("pick")
        self.assertEqual([p.trigger for p in hits], ["pf"])
        self.assertEqual(self.table.matching("scan"), [])

    def test_recipe(self):
        recipe = self.table.recipe("ps")
        self.assertIsNotNone(recipe)
        self.assertEqual(recipe.kind, "success")

    def test_recipe_wrong_kind(self):
        self.assertIsNone(self.table.recipe("pf"))

    def test_recipe_missing(self):
        self.assertIsNone(self.table.recipe("nope"))


class TestPolicyTableMetrics(unittest.TestCase):

    def setUp(self):
        self.table = PolicyTable()

    def test_record_suggested(self):
        self.table.upsert(trigger="t", strategy="s")
        self.table.record_suggested("t")
        self.assertEqual(self.table.get("t").suggest_count, 1)

    def test_record_suggested_missing_ignored(self):
        self.table.record_suggested("nope")  # 不抛异常

    def test_record_accepted_success(self):
        self.table.upsert(trigger="t", strategy="s")
        self.table.record_accepted("t", success=True)
        p = self.table.get("t")
        self.assertEqual(p.accepted_count, 1)
        self.assertEqual(p.success_count, 1)
        self.assertEqual(p.hit_rate, 1.0)

    def test_record_accepted_failure(self):
        self.table.upsert(trigger="t", strategy="s")
        self.table.record_accepted("t", success=False)
        p = self.table.get("t")
        self.assertEqual(p.accepted_count, 1)
        self.assertEqual(p.success_count, 0)
        self.assertEqual(p.hit_rate, 0.0)

    def test_record_accepted_missing_ignored(self):
        self.table.record_accepted("nope", True)  # 不抛异常

    def test_evaluate_degradation_never_accepted(self):
        self.table.upsert(trigger="t", strategy="s")
        for _ in range(3):
            self.table.record_suggested("t")
        degraded = self.table.evaluate_degradation(min_suggestions=3)
        self.assertEqual(degraded, ["t"])
        self.assertTrue(self.table.get("t").degraded)

    def test_evaluate_degradation_low_hit_rate(self):
        self.table.upsert(trigger="t", strategy="s")
        for _ in range(3):
            self.table.record_suggested("t")
        for _ in range(3):
            self.table.record_accepted("t", success=False)
        degraded = self.table.evaluate_degradation(min_suggestions=3, min_hit_rate=0.5)
        self.assertEqual(degraded, ["t"])
        self.assertTrue(self.table.get("t").degraded)

    def test_evaluate_degradation_below_threshold(self):
        self.table.upsert(trigger="t", strategy="s")
        self.table.record_suggested("t")
        self.table.record_suggested("t")
        self.assertEqual(self.table.evaluate_degradation(min_suggestions=3), [])
        self.assertFalse(self.table.get("t").degraded)

    def test_evaluate_degradation_good_policy_kept(self):
        self.table.upsert(trigger="t", strategy="s")
        for _ in range(3):
            self.table.record_suggested("t")
        for _ in range(3):
            self.table.record_accepted("t", success=True)
        self.assertEqual(self.table.evaluate_degradation(min_suggestions=3), [])
        self.assertFalse(self.table.get("t").degraded)

    def test_evaluate_degradation_idempotent(self):
        self.table.upsert(trigger="t", strategy="s")
        for _ in range(3):
            self.table.record_suggested("t")
        self.table.evaluate_degradation(min_suggestions=3)
        self.assertEqual(self.table.evaluate_degradation(min_suggestions=3), [])

    def test_stats_fields(self):
        self.table.upsert(trigger="pf", strategy="s", kind="failure")
        self.table.upsert(trigger="ps", strategy="s", kind="success")
        stats = self.table.stats()
        self.assertEqual(stats["total"], 2)
        self.assertEqual(stats["failure_count"], 1)
        self.assertEqual(stats["success_count"], 1)
        self.assertEqual(stats["degraded_count"], 0)
        self.assertEqual(stats["mode"], "rule_based")

    def test_stats_rates(self):
        self.table.upsert(trigger="t", strategy="s")
        for _ in range(4):
            self.table.record_suggested("t")
        for _ in range(2):
            self.table.record_accepted("t", success=True)
        stats = self.table.stats()
        self.assertEqual(stats["suggest_count"], 4)
        self.assertEqual(stats["accepted_count"], 2)
        self.assertEqual(stats["success_count_executed"], 2)
        self.assertEqual(stats["hit_rate"], 1.0)
        self.assertEqual(stats["acceptance_rate"], 0.5)


class TestPolicyTablePersistence(unittest.TestCase):

    def setUp(self):
        self.table = PolicyTable()

    def test_save_load_roundtrip(self):
        self.table.upsert(trigger="pf", strategy="scan_before_pick", kind="failure",
                          action_type="pick", source_goal_id="g-1")
        self.table.record_suggested("pf")
        self.table.record_accepted("pf", success=True)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "embodied_policy.jsonl")
            self.assertEqual(self.table.save_to_file(path), 1)
            table2 = PolicyTable()
            self.assertEqual(table2.load_from_file(path), 1)
            p = table2.get("pf")
            self.assertIsNotNone(p)
            self.assertEqual(p.strategy, "scan_before_pick")
            self.assertEqual(p.suggest_count, 1)
            self.assertEqual(p.success_count, 1)
            self.assertEqual(p.source_goal_ids, ["g-1"])

    def test_load_missing_file(self):
        self.assertEqual(self.table.load_from_file("nope.jsonl"), 0)

    def test_load_bad_line_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "bad.jsonl")
            with open(path, "w", encoding="utf-8") as f:
                f.write('{"trigger": "ok", "strategy": "s"}\n')
                f.write("NOT JSON\n")
            self.assertEqual(self.table.load_from_file(path), 1)
            self.assertIsNotNone(self.table.get("ok"))

    def test_save_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "empty.jsonl")
            self.assertEqual(self.table.save_to_file(path), 0)


class TestPolicyTableLifecycle(unittest.TestCase):

    def test_clear(self):
        table = PolicyTable()
        table.upsert(trigger="a", strategy="s")
        table.upsert(trigger="b", strategy="s")
        self.assertEqual(table.clear(), 2)
        self.assertEqual(table.count(), 0)

    def test_max_policies_property(self):
        table = PolicyTable(max_policies=5)
        self.assertEqual(table.max_policies, 5)


if __name__ == "__main__":
    unittest.main()
