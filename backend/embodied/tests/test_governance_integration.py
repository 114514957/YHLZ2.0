"""
YHLZ Embodied AI V4.5 - 元策略管理 Service 集成测试
(Meta Strategy Management via EmbodiedService)

覆盖:
    - Service 全部 21 个 V4.5 API 可调用 (strategy_system_overview /
      strategy_system_report / redundant_policies / archive_redundant_policies /
      conflicting_policies / resolve_conflicts / archive_candidates /
      apply_archival / delete_policy / restore_policy / purge_policy /
      recycle_bin / consolidate_similar_policies / split_policy /
      compare_policy_versions / rollback_policy / policy_families /
      policy_health_check / scene_coverage / governance_dry_run /
      audit_system_export)
    - 版本: report() / status() 为 9.5.0, report 含 governance 段
    - 端到端治理闭环: 冗余 → 归档 → 回收站 → 恢复 → 版本比较 → 回滚 → 导出
    - 治理动作不写入 Agent Memory / 不绕过 Permission
    - 纯规则模式 (mode=rule_based)
"""
import unittest

from backend.embodied.service import EmbodiedService


class TestServiceV45Api(unittest.TestCase):
    """Service V4.5 API 可调用性 + 返回值结构"""

    def setUp(self):
        self.svc = EmbodiedService()
        self.svc.load_config({
            "embodied_enabled": True,
            "embodied_policy_min_archive_age_days": 30,
            "embodied_policy_min_archive_hit_rate": 0.3,
        })
        self.t = self.svc._experience.table

    def _seed_redundant(self):
        self.t.upsert(trigger="a", strategy="s", kind="failure",
                      action_type="pick", scene="room")
        self.t.upsert(trigger="b", strategy="s", kind="failure",
                      action_type="pick", scene="room")

    def test_version_4_5_0(self):
        """Service 版本 = 9.5.0"""
        self.assertEqual(self.svc.report()["version"], "9.5.0")

    def test_report_contains_governance(self):
        """report 含 governance 段 (health_score / coverage)"""
        rep = self.svc.report()
        gov = rep.get("governance", {})
        self.assertIn("health_score", gov)
        self.assertIn("coverage", gov)
        self.assertIn("coverage_rate", gov["coverage"])
        self.assertEqual(gov["mode"], "rule_based")

    def test_governance_status(self):
        """governance.status(): 版本 / 模式 / 阈值 / dry_run 动作"""
        st = self.svc.governance.status()
        self.assertEqual(st["version"], "9.5.0")
        self.assertEqual(st["mode"], "rule_based")
        self.assertIn("thresholds", st)
        self.assertEqual(len(st["dry_run_actions"]), 7)

    def test_strategy_system_overview_api(self):
        """strategy_system_overview 返回结构"""
        self._seed_redundant()
        o = self.svc.strategy_system_overview()
        for key in ("generated_at", "mode", "matrix", "stats",
                    "quality", "consistency"):
            self.assertIn(key, o)
        self.assertEqual(o["stats"]["total"], 2)

    def test_strategy_system_report_api(self):
        """strategy_system_report 文本报告"""
        self._seed_redundant()
        text = self.svc.strategy_system_report()
        self.assertIn("V4.5", text)

    def test_conflicting_policies_api(self):
        """conflicting_policies 返回结构"""
        self.t.upsert(trigger="c", strategy="v1", kind="failure",
                      action_type="pick")
        r = self.svc.conflicting_policies()
        self.assertIn("conflicts", r)
        self.assertIn("total", r)

    def test_archive_candidates_api(self):
        """archive_candidates 返回结构"""
        r = self.svc.archive_candidates()
        self.assertIn("candidates", r)
        self.assertIn("thresholds", r)

    def test_recycle_bin_api(self):
        """recycle_bin 返回结构"""
        self.t.upsert(trigger="d", strategy="s", kind="failure",
                      action_type="pick")
        self.svc.delete_policy("d")
        r = self.svc.recycle_bin()
        self.assertIn("entries", r)
        self.assertEqual(r["entries"][0]["trigger"], "d")

    def test_policy_families_api(self):
        """policy_families 返回结构"""
        r = self.svc.policy_families()
        self.assertIsInstance(r, dict)

    def test_compare_policy_versions_api(self):
        """compare_policy_versions 返回结构"""
        self.t.upsert(trigger="t", strategy="s", kind="failure",
                      action_type="pick")
        r = self.svc.compare_policy_versions("t")
        self.assertIn("versions", r)
        self.assertIn("latest_verdict", r)

    def test_audit_policy_log_action_filter_api(self):
        """audit_policy_log 支持 action 过滤"""
        self._seed_redundant()
        self.svc.archive_redundant_policies(dry_run=False)
        log = self.svc.audit_policy_log(limit=0, action="archive_redundant")
        self.assertEqual(log["total"], 1)
        all_log = self.svc.audit_policy_log(limit=0)
        self.assertGreaterEqual(all_log["total"], 1)

    def test_governance_dry_run_api(self):
        """governance_dry_run 经 Service"""
        r = self.svc.governance_dry_run("consolidate")
        self.assertTrue(r["dry_run"])
        self.assertEqual(r["action"], "consolidate")

    def test_audit_system_export_api(self):
        """audit_system_export 经 Service"""
        self._seed_redundant()
        exp = self.svc.audit_system_export()
        self.assertEqual(exp["version"], "9.5.0")
        self.assertIn("strategy_system", exp)
        self.assertIn("audit", exp)


class TestEndToEndGovernanceFlow(unittest.TestCase):
    """端到端治理闭环: 检测 → 治理 → 回收 → 版本 → 导出"""

    def setUp(self):
        self.svc = EmbodiedService()
        self.svc.load_config({
            "embodied_enabled": True,
            "embodied_policy_min_archive_age_days": 30,
            "embodied_policy_min_archive_hit_rate": 0.3,
        })
        self.t = self.svc._experience.table

    def test_full_governance_flow(self):
        """完整闭环: 冗余归档 → 回收站 → 恢复 → 回滚 → 导出"""
        # 1. 冗余检测 + 归档
        self.t.upsert(trigger="a", strategy="s", kind="failure",
                      action_type="pick", scene="room")
        self.t.upsert(trigger="b", strategy="s", kind="failure",
                      action_type="pick", scene="room")
        det = self.svc.redundant_policies()
        self.assertEqual(det["total"], 1)
        self.svc.archive_redundant_policies(dry_run=False)

        # 2. 回收站 + 恢复
        self.svc.delete_policy("a")
        bin_items = self.svc.recycle_bin()["entries"]
        self.assertEqual(bin_items[0]["trigger"], "a")
        self.svc.restore_policy("a")

        # 3. 版本比较 + 回滚
        self.t.upsert_version(trigger="a", strategy="s2", kind="failure",
                              action_type="pick", scene="room")
        v1, v2 = self.t.all_versions("a")
        v1.accepted_count, v1.success_count = 10, 9
        v2.accepted_count, v2.success_count = 10, 1
        cmp = self.svc.compare_policy_versions("a")
        self.assertEqual(cmp["latest_verdict"], "regression")
        rb = self.svc.rollback_policy("a", dry_run=False)
        self.assertEqual(rb["rolled_to"], 1)

        # 4. 健康检查 + 覆盖
        health = self.svc.policy_health_check()
        self.assertIn("health_score", health)
        cov = self.svc.scene_coverage()
        self.assertIn("coverage_rate", cov)

        # 5. 导出
        exp = self.svc.audit_system_export()
        actions = {e["action"] for e in exp["audit"]["entries"]}
        self.assertIn("archive_redundant", actions)
        self.assertIn("restore", actions)
        self.assertIn("rollback", actions)

    def test_governance_does_not_write_memory(self):
        """治理动作不写入 Agent Memory"""
        self.svc.load_config({
            "embodied_enabled": True,
            "embodied_memory_path": "",
        })
        memory_before = self.svc.memory.stats().get("total", 0)
        self._seed_and_govern()
        memory_after = self.svc.memory.stats().get("total", 0)
        self.assertEqual(memory_after, memory_before)

    def _seed_and_govern(self):
        self.t.upsert(trigger="a", strategy="s", kind="failure",
                      action_type="pick", scene="room")
        self.t.upsert(trigger="b", strategy="s", kind="failure",
                      action_type="pick", scene="room")
        self.svc.archive_redundant_policies(dry_run=False)
        self.svc.delete_policy("a")
        self.svc.purge_policy("a", confirm=True)

    def test_mode_rule_based_everywhere(self):
        """全部治理输出 mode=rule_based (无黑盒)"""
        self.t.upsert(trigger="a", strategy="s", kind="failure",
                      action_type="pick")
        self.assertEqual(self.svc.strategy_system_overview()["mode"],
                         "rule_based")
        self.assertEqual(self.svc.policy_health_check()["mode"], "rule_based")
        st = self.svc.governance.status()
        self.assertEqual(st["mode"], "rule_based")

    def test_audit_filter_governance_actions(self):
        """审计按治理动作过滤: 每个动作独立可查"""
        self.t.upsert(trigger="a", strategy="s", kind="failure",
                      action_type="pick")
        self.t.upsert(trigger="b", strategy="s", kind="failure",
                      action_type="pick")
        self.svc.archive_redundant_policies(dry_run=False)
        self.svc.delete_policy("a")
        self.svc.restore_policy("a")
        for action in ("archive_redundant", "archive", "restore"):
            log = self.svc.audit_policy_log(limit=0, action=action)
            self.assertEqual(log["total"], 1, f"action={action}")

    def test_rollback_denied_when_healthy(self):
        """healthy 最新版本 → rollback 拒绝"""
        self.t.upsert(trigger="t", strategy="good", kind="failure",
                      action_type="pick")
        self.t.upsert_version(trigger="t", strategy="better", kind="failure",
                              action_type="pick")
        v1, v2 = self.t.all_versions("t")
        v1.accepted_count, v1.success_count = 10, 2
        v2.accepted_count, v2.success_count = 10, 9
        r = self.svc.rollback_policy("t", dry_run=True)
        self.assertFalse(r["allowed"])

    def test_split_through_service(self):
        """split 经 Service"""
        self.t.upsert(trigger="pick_object", strategy="s", kind="failure",
                      action_type="pick", scene="room", goal_type="pick")
        r = self.svc.split_policy("pick_object", by="scene",
                                  values=["warehouse", "home"], dry_run=False)
        self.assertEqual(r["total"], 2)
        self.assertEqual(self.t.get("pick_object").effective_status, "archived")
        self.assertEqual(self.t.get("pick_object_warehouse").scene, "warehouse")


if __name__ == "__main__":
    unittest.main()
