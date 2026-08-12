"""
YHLZ Embodied AI V4.5 - 治理 Dry Run 体系化单元测试 (Governance Dry Run + Audit)

覆盖 (治理 Dry Run 体系化):
    - governance_dry_run 统一入口: 支持全部治理动作白名单
    - 返回: 影响策略 / 执行后系统快照差异 / 保护规则检查结果
    - SystemSnapshot: 快照捕获 + 差异对比
    - 保护规则检查: 只影响策略系统 / 不控设备 / 不写 Agent Memory /
      纯规则 / 不绕过 Permission
    - 不支持的动作 → DryRunError
    - dry_run 绝不修改任何状态

覆盖 (审计增强):
    - audit_policy_log(action=...) 治理动作过滤
    - audit_system_export: 完整 JSON 审计档案导出
    - 治理动作进入审计白名单 (consolidate / split / rollback / purge /
      resolve_conflict / archive_redundant / apply_archival)
"""
import unittest

from backend.embodied.experience.policy import (
    POLICY_STATUS_ACTIVE,
    POLICY_STATUS_ARCHIVED,
    PolicyTable,
)
from backend.embodied.governance import (
    DryRunError,
    GOVERNANCE_DRY_RUN_ACTIONS,
    GovernanceDryRun,
    PolicyEvolution,
    PolicyGovernance,
    PolicyHealthCheck,
    StrategyGovernance,
    SystemSnapshot,
)
from backend.embodied.strategy.audit import (
    AUDIT_ACTIONS,
    PolicyAuditLog,
)


class TestSystemSnapshot(unittest.TestCase):
    """体系快照: 捕获 + 差异"""

    def setUp(self):
        self.table = PolicyTable()
        self.audit = PolicyAuditLog()

    def test_capture_empty(self):
        """空表快照字段完整"""
        s = SystemSnapshot.capture(self.table)
        for key in ("total", "status_counts", "version_total",
                    "archived_count", "deleted_count", "avg_hit_rate",
                    "family_count"):
            self.assertIn(key, s)
        self.assertEqual(s["total"], 0)
        self.assertEqual(s["family_count"], 0)

    def test_capture_counts(self):
        """快照统计: 数量 / 状态分布 / 版本"""
        self.table.upsert(trigger="a", strategy="s", kind="failure",
                          action_type="pick")
        self.table.upsert_version(trigger="a", strategy="s2", kind="failure",
                                  action_type="pick")
        self.table.upsert(trigger="b", strategy="s", kind="success",
                          action_type="pick")
        self.table.archive_policy("b")
        s = SystemSnapshot.capture(self.table)
        self.assertEqual(s["total"], 2)
        self.assertEqual(s["version_total"], 3)
        self.assertEqual(s["archived_count"], 1)
        self.assertEqual(s["status_counts"]["active"], 1)

    def test_diff_only_changes(self):
        """差异只输出变化字段"""
        before = {"a": 1, "b": 2, "c": 3}
        after = {"a": 1, "b": 9, "c": 3}
        d = SystemSnapshot.diff(before, after)
        self.assertEqual(d, {"b": {"before": 2, "after": 9}})


def build_dry(table, audit):
    gov = PolicyGovernance(table, audit,
                           min_archive_age_days=30, min_archive_hit_rate=0.3)
    evo = PolicyEvolution(table, audit)
    health = PolicyHealthCheck(table, weak_hit_rate=0.3,
                               weak_acceptance_rate=0.2)
    return GovernanceDryRun(gov, evo, health)


class TestGovernanceDryRun(unittest.TestCase):
    """治理预演统一入口"""

    def setUp(self):
        self.table = PolicyTable()
        self.audit = PolicyAuditLog()
        self.dry = build_dry(self.table, self.audit)

    def test_action_whitelist(self):
        """白名单覆盖全部治理动作"""
        self.assertEqual(set(GOVERNANCE_DRY_RUN_ACTIONS), {
            "archive_redundant", "resolve_conflicts", "apply_archival",
            "consolidate", "split", "rollback", "purge",
        })

    def test_unsupported_action_raises(self):
        """不支持的动作 → DryRunError"""
        with self.assertRaises(DryRunError):
            self.dry.run("train_model")

    def test_base_fields(self):
        """基础字段: dry_run / action / protection_checks"""
        r = self.dry.run("consolidate")
        self.assertTrue(r["dry_run"])
        self.assertEqual(r["action"], "consolidate")
        self.assertTrue(r["protection_checks"]["passed"])
        self.assertEqual(len(r["protection_checks"]["checks"]), 5)

    def test_protection_checks_content(self):
        """保护规则: 5 项全通过 (可解释)"""
        r = self.dry.run("consolidate")
        names = {c["name"] for c in r["protection_checks"]["checks"]}
        self.assertEqual(names, {
            "targets_only_policy_system", "no_device_control",
            "no_agent_memory_write", "no_ai_training",
            "permission_layer_untouched",
        })

    def test_dry_run_no_side_effect(self):
        """预演绝不修改状态"""
        self.table.upsert(trigger="a", strategy="s", kind="failure",
                          action_type="pick")
        self.table.upsert(trigger="b", strategy="s", kind="failure",
                          action_type="pick")
        before = SystemSnapshot.capture(self.table)
        self.dry.run("archive_redundant")
        after = SystemSnapshot.capture(self.table)
        self.assertEqual(before, after)
        self.assertEqual(self.audit.count(), 0)

    def test_archive_redundant_impacts(self):
        """archive_redundant → 影响策略 = 冗余候选"""
        self.table.upsert(trigger="a", strategy="s", kind="failure",
                          action_type="pick", scene="room")
        self.table.upsert(trigger="b", strategy="s", kind="failure",
                          action_type="pick", scene="room")
        r = self.dry.run("archive_redundant")
        self.assertEqual(r["impact_count"], 1)
        self.assertEqual(r["impacted_policies"][0]["trigger"], "b")
        self.assertEqual(r["impacted_policies"][0]["change"], "active → archived")

    def test_archive_redundant_snapshot_diff(self):
        """预演输出快照差异: active → archived"""
        self.table.upsert(trigger="a", strategy="s", kind="failure",
                          action_type="pick", scene="room")
        self.table.upsert(trigger="b", strategy="s", kind="failure",
                          action_type="pick", scene="room")
        r = self.dry.run("archive_redundant")
        d = r["snapshot_diff"]
        self.assertIn("status_counts", d)
        self.assertEqual(
            d["status_counts"]["before"]["active"],
            d["status_counts"]["after"]["active"] + 1,
        )

    def test_apply_archival_dry(self):
        """apply_archival 预演 = 候选清单"""
        p = self.table.upsert(trigger="old", strategy="s", kind="failure",
                              action_type="pick")
        import time as _time
        p.created_at = _time.time() - 40 * 86400
        p.updated_at = _time.time() - 40 * 86400
        p.last_suggested_at = 0.0
        p.last_accepted_at = 0.0
        p.accepted_count, p.success_count = 10, 1
        r = self.dry.run("apply_archival")
        self.assertEqual(r["impact_count"], 1)
        self.assertEqual(r["impacted_policies"][0]["trigger"], "old")
        self.assertEqual(self.table.get("old").effective_status,
                         POLICY_STATUS_ACTIVE)

    def test_consolidate_impacts(self):
        """consolidate 预演 → 影响 family 成员"""
        self.table.upsert(trigger="a", strategy="s", kind="success",
                          action_sequence=[{"action_type": "pick"}])
        self.table.upsert(trigger="b", strategy="s", kind="success",
                          action_sequence=[{"action_type": "pick"}])
        r = self.dry.run("consolidate")
        self.assertEqual(r["impact_count"], 2)
        self.assertEqual(r["detail"]["total"], 1)
        # 预演后 family 未写入
        self.assertEqual(self.table.get("a").family_id, "")

    def test_split_dry_run(self):
        """split 预演: 需要 trigger / values 参数"""
        self.table.upsert(trigger="pick_object", strategy="s", kind="failure",
                          action_type="pick")
        r = self.dry.run("split", trigger="pick_object",
                         by="scene", values=["warehouse", "home"])
        self.assertEqual(r["impact_count"], 3)   # 原策略 + 2 新策略
        self.assertEqual(r["detail"]["total"], 2)
        self.assertIsNone(self.table.get("pick_object_warehouse"))

    def test_split_missing_trigger_raises(self):
        """split 预演目标不存在 → 异常 (策略不存在)"""
        from backend.embodied.governance import EvolutionError
        with self.assertRaises(EvolutionError):
            self.dry.run("split", trigger="nope", values=["a"])

    def test_rollback_dry_run(self):
        """rollback 预演: regression 允许 / healthy 禁止"""
        self.table.upsert(trigger="t", strategy="good", kind="failure",
                          action_type="pick")
        self.table.upsert_version(trigger="t", strategy="bad", kind="failure",
                                  action_type="pick")
        v1, v2 = self.table.all_versions("t")
        v1.accepted_count, v1.success_count = 10, 9
        v2.accepted_count, v2.success_count = 10, 1
        r = self.dry.run("rollback", trigger="t")
        self.assertTrue(r["detail"]["allowed"])
        self.assertEqual(r["impact_count"], 1)
        # 预演不改变状态
        self.assertEqual(self.table.get("t").version, 2)

    def test_rollback_healthy_denied(self):
        """healthy 最新版本 → 预演 allowed=False, 无影响"""
        self.table.upsert(trigger="t", strategy="s", kind="failure",
                          action_type="pick")
        self.table.upsert_version(trigger="t", strategy="s2", kind="failure",
                                  action_type="pick")
        v1, v2 = self.table.all_versions("t")
        v1.accepted_count, v1.success_count = 10, 1
        v2.accepted_count, v2.success_count = 10, 9
        r = self.dry.run("rollback", trigger="t")
        self.assertFalse(r["detail"]["allowed"])
        self.assertEqual(r["impact_count"], 0)

    def test_purge_dry_run(self):
        """purge 预演: 需要 trigger / triggers"""
        self.table.upsert(trigger="p", strategy="s", kind="failure",
                          action_type="pick")
        r = self.dry.run("purge", trigger="p")
        self.assertEqual(r["impact_count"], 1)
        self.assertIsNotNone(self.table.get("p"))   # 未删除
        self.assertEqual(
            r["snapshot_diff"]["total"]["after"],
            r["snapshot_diff"]["total"]["before"] - 1,
        )

    def test_purge_without_trigger_raises(self):
        """purge 预演缺参数 → DryRunError"""
        with self.assertRaises(DryRunError):
            self.dry.run("purge")

    def test_purge_missing_policy_raises(self):
        """purge 预演目标不存在 → DryRunError"""
        with self.assertRaises(DryRunError):
            self.dry.run("purge", trigger="nope")

    def test_resolve_conflicts_dry(self):
        """resolve_conflicts 预演 → 影响旧版本"""
        self.table.upsert(trigger="c", strategy="v1", kind="failure",
                          action_type="pick")
        self.table.upsert_version(trigger="c", strategy="v2", kind="failure",
                                  action_type="pick")
        vers = self.table.all_versions("c")
        vers[0].set_status(POLICY_STATUS_ACTIVE)
        r = self.dry.run("resolve_conflicts")
        self.assertEqual(r["impact_count"], 1)
        self.assertEqual(r["impacted_policies"][0]["version"], 1)
        # 状态未变
        self.assertTrue(all(v.effective_status == POLICY_STATUS_ACTIVE
                            for v in self.table.all_versions("c")))

    def test_governance_facade_dry_run(self):
        """门面 governance_dry_run 统一入口"""
        table = PolicyTable()
        audit = PolicyAuditLog()
        facade = StrategyGovernance(table, audit)
        r = facade.governance_dry_run("archive_redundant")
        self.assertTrue(r["dry_run"])
        self.assertEqual(r["action"], "archive_redundant")


class TestAuditGovernance(unittest.TestCase):
    """审计增强: 治理动作过滤 + 档案导出"""

    def setUp(self):
        self.table = PolicyTable()
        self.audit = PolicyAuditLog()
        self.gov = PolicyGovernance(
            self.table, self.audit,
            min_archive_age_days=30, min_archive_hit_rate=0.3,
        )
        self.evo = PolicyEvolution(self.table, self.audit)

    def test_governance_actions_in_whitelist(self):
        """治理动作全部在审计白名单"""
        for action in ("consolidate", "split", "rollback", "purge",
                       "resolve_conflict", "archive_redundant",
                       "apply_archival"):
            self.assertIn(action, AUDIT_ACTIONS)

    def test_audit_filter_by_action(self):
        """audit_policy_log(action=...) 精确过滤"""
        self.audit.record(trigger="a", action="apply", applied=True)
        self.audit.record(trigger="b", action="archive", applied=False)
        self.audit.record(trigger="c", action="consolidate", applied=False)
        log = self.audit.audit_policy_log(limit=0, action="consolidate")
        self.assertEqual(log["total"], 1)
        self.assertEqual(log["by_action"], {"consolidate": 1})

    def test_audit_filter_invalid_action_raises(self):
        """非法动作过滤 → PolicyAuditError"""
        with self.assertRaises(Exception):
            self.audit.audit_policy_log(limit=0, action="hack")

    def test_audit_system_export_structure(self):
        """audit_system_export: 完整档案结构"""
        from backend.embodied.service import EmbodiedService
        svc = EmbodiedService()
        svc.load_config({"embodied_enabled": True})
        t = svc._experience.table
        t.upsert(trigger="a", strategy="s", kind="failure", action_type="pick")
        exp = svc.audit_system_export()
        self.assertEqual(exp["version"], "9.5.0")
        self.assertEqual(exp["mode"], "rule_based")
        self.assertIn("exported_at", exp)
        self.assertIn("strategy_system", exp)
        self.assertIn("policies", exp)
        self.assertIn("audit", exp)
        self.assertIn("families", exp)
        self.assertIn("recycle_bin", exp)
        self.assertIn("health", exp)
        self.assertIn("snapshot", exp)
        self.assertEqual(exp["policies"][0]["trigger"], "a")
        self.assertEqual(exp["snapshot"]["policies_total"], 1)

    def test_export_after_governance_actions(self):
        """治理动作后导出: 审计含治理动作, 回收站状态正确"""
        from backend.embodied.service import EmbodiedService
        svc = EmbodiedService()
        svc.load_config({"embodied_enabled": True})
        t = svc._experience.table
        t.upsert(trigger="a", strategy="s", kind="failure", action_type="pick")
        t.upsert(trigger="b", strategy="s", kind="failure", action_type="pick")
        svc.archive_redundant_policies(dry_run=False)
        svc.delete_policy("a")
        exp = svc.audit_system_export()
        actions = {e["action"] for e in exp["audit"]["entries"]}
        self.assertIn("archive_redundant", actions)
        self.assertEqual(len(exp["recycle_bin"]["entries"]), 1)


if __name__ == "__main__":
    unittest.main()
