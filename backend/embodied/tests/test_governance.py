"""
YHLZ Embodied AI V4.5 - 元策略治理单元测试 (Meta Strategy Governance)

覆盖 (Strategy Governance):
    - 冗余策略检测: 同 scene×goal_type×kind×action_type 且内容一致 → 冗余
    - 冗余归档: archive_redundant_policies (dry_run 预演 / 执行 + 审计)
    - 冲突策略检测: 同一 trigger 多个 active version → 最新版本优先
    - 冲突解决: resolve_conflicts (旧版本归档, 保留 keeper)
    - 低效策略归档: archive_candidates (年龄 + hit_rate 阈值, 人工确认)
    - apply_archival: 检测 → 建议 → 人工确认 → 执行 (confirm=False 拒绝)
    - 策略回收站: delete / restore / purge / recycle_bin (两阶段删除)
    - 审计追踪: 治理动作进入审计日志, audit_policy_log(action=...) 过滤

安全约束验证:
    - 治理动作只影响策略表 / 审计日志 (不触碰 Permission / Agent Memory)
    - 不是自动删除: 低效归档必须人工确认
    - 纯规则 + 统计 + 阈值 (可解释输出)
"""
import time
import unittest

from backend.embodied.experience.policy import (
    POLICY_STATUS_ACTIVE,
    POLICY_STATUS_ARCHIVED,
    POLICY_STATUS_DELETED,
    ExperiencePolicy,
    PolicyTable,
)
from backend.embodied.governance import (
    GovernanceError,
    PolicyGovernance,
    StrategyGovernance,
)
from backend.embodied.service import EmbodiedService
from backend.embodied.strategy.audit import PolicyAuditLog


def make_policy(trigger="t", strategy="s", kind="failure", action_type="pick",
                scene="room", goal_type="pick", detail="d",
                action_sequence=None, **kw):
    return ExperiencePolicy.create(
        trigger=trigger, strategy=strategy, kind=kind,
        action_type=action_type, scene=scene, goal_type=goal_type,
        detail=detail, action_sequence=action_sequence or [],
        **kw,
    )


class TestRedundantPolicies(unittest.TestCase):
    """冗余策略检测: 同 scene×goal_type×kind×action_type 且内容一致"""

    def setUp(self):
        self.table = PolicyTable()
        self.audit = PolicyAuditLog()
        self.gov = PolicyGovernance(
            self.table, self.audit,
            min_archive_age_days=30, min_archive_hit_rate=0.3,
        )

    def test_no_redundant_empty(self):
        """空策略表 → 无冗余候选"""
        r = self.gov.redundant_policies()
        self.assertEqual(r["total"], 0)
        self.assertEqual(r["groups"], [])
        self.assertIn("rule", r)

    def test_single_policy_not_redundant(self):
        """单策略 → 不冗余"""
        self.table.upsert(trigger="only", strategy="s", kind="failure",
                          action_type="pick", scene="room")
        r = self.gov.redundant_policies()
        self.assertEqual(r["total"], 0)

    def test_identical_content_redundant(self):
        """同维度同内容双策略 → 判定冗余, 保留最早创建"""
        self.table.upsert(trigger="a", strategy="scan_first", kind="failure",
                          action_type="pick", scene="room", goal_type="pick",
                          detail="d1", action_sequence=[{"action_type": "scan"}])
        self.table.upsert(trigger="b", strategy="scan_first", kind="failure",
                          action_type="pick", scene="room", goal_type="pick",
                          detail="d1", action_sequence=[{"action_type": "scan"}])
        r = self.gov.redundant_policies()
        self.assertEqual(r["total"], 1)
        self.assertEqual(r["candidates"][0]["trigger"], "b")
        self.assertEqual(r["candidates"][0]["keeper"], "a")
        self.assertIn("冗余", r["candidates"][0]["reason"])

    def test_different_content_not_redundant(self):
        """同维度不同策略内容 → 不冗余"""
        self.table.upsert(trigger="a", strategy="scan_first", kind="failure",
                          action_type="pick", scene="room")
        self.table.upsert(trigger="b", strategy="move_first", kind="failure",
                          action_type="pick", scene="room")
        r = self.gov.redundant_policies()
        self.assertEqual(r["total"], 0)

    def test_different_scene_not_redundant(self):
        """不同 scene → 不冗余"""
        self.table.upsert(trigger="a", strategy="s", kind="failure",
                          action_type="pick", scene="room")
        self.table.upsert(trigger="b", strategy="s", kind="failure",
                          action_type="pick", scene="warehouse")
        r = self.gov.redundant_policies()
        self.assertEqual(r["total"], 0)

    def test_different_kind_not_redundant(self):
        """不同 kind (failure / success) → 不冗余"""
        self.table.upsert(trigger="a", strategy="s", kind="failure",
                          action_type="pick", scene="room")
        self.table.upsert(trigger="b", strategy="s", kind="success",
                          action_type="pick", scene="room")
        r = self.gov.redundant_policies()
        self.assertEqual(r["total"], 0)

    def test_archived_not_involved(self):
        """归档策略不参与冗余检测"""
        self.table.upsert(trigger="a", strategy="s", kind="failure",
                          action_type="pick", scene="room")
        self.table.upsert(trigger="b", strategy="s", kind="failure",
                          action_type="pick", scene="room")
        self.table.archive_policy("b")
        r = self.gov.redundant_policies()
        self.assertEqual(r["total"], 0)

    def test_group_key_explainable(self):
        """输出含可解释维度 key"""
        self.table.upsert(trigger="a", strategy="s", kind="failure",
                          action_type="pick", scene="room", goal_type="pick")
        self.table.upsert(trigger="b", strategy="s", kind="failure",
                          action_type="pick", scene="room", goal_type="pick")
        r = self.gov.redundant_policies()
        self.assertEqual(r["groups"][0]["key"], "room/pick/failure/pick")
        self.assertEqual(r["groups"][0]["scene"], "room")
        self.assertEqual(r["groups"][0]["goal_type"], "pick")
        self.assertEqual(r["groups"][0]["kind"], "failure")
        self.assertEqual(r["groups"][0]["action_type"], "pick")

    def test_three_identical_keeps_earliest(self):
        """三个同内容 → 保留最早, 其余冗余"""
        for i, tg in enumerate(["a", "b", "c"]):
            p = self.table.upsert(trigger=tg, strategy="s", kind="failure",
                                  action_type="pick", scene="room")
            p.created_at = 1000.0 + i
        r = self.gov.redundant_policies()
        self.assertEqual(r["total"], 2)
        triggers = {c["trigger"] for c in r["candidates"]}
        self.assertEqual(triggers, {"b", "c"})


class TestArchiveRedundant(unittest.TestCase):
    """冗余策略归档 (支持 dry_run 预演)"""

    def setUp(self):
        self.table = PolicyTable()
        self.audit = PolicyAuditLog()
        self.gov = PolicyGovernance(
            self.table, self.audit,
            min_archive_age_days=30, min_archive_hit_rate=0.3,
        )

    def _seed_redundant(self):
        self.table.upsert(trigger="a", strategy="s", kind="failure",
                          action_type="pick", scene="room")
        self.table.upsert(trigger="b", strategy="s", kind="failure",
                          action_type="pick", scene="room")

    def test_dry_run_no_side_effect(self):
        """dry_run=True → 不改变状态, 不写审计"""
        self._seed_redundant()
        before = self.table.stats()["status_counts"]["active"]
        r = self.gov.archive_redundant_policies(dry_run=True)
        self.assertTrue(r["dry_run"])
        self.assertEqual(r["total"], 1)
        self.assertEqual(self.table.stats()["status_counts"]["active"], before)
        self.assertEqual(self.audit.count(), 0)

    def test_execute_archives(self):
        """dry_run=False → 冗余策略归档, 保留 keeper"""
        self._seed_redundant()
        r = self.gov.archive_redundant_policies(dry_run=False)
        self.assertEqual(len(r["archived"]), 1)
        self.assertEqual(self.table.get("a").effective_status, POLICY_STATUS_ACTIVE)
        self.assertEqual(self.table.get("b").effective_status, POLICY_STATUS_ARCHIVED)

    def test_execute_writes_audit(self):
        """执行归档 → 审计日志记录 archive_redundant 动作"""
        self._seed_redundant()
        self.gov.archive_redundant_policies(dry_run=False)
        log = self.audit.audit_policy_log(limit=0, action="archive_redundant")
        self.assertEqual(log["total"], 1)
        self.assertEqual(log["recent"][0]["trigger"], "b")


class TestConflictingPolicies(unittest.TestCase):
    """冲突策略检测: 同一 trigger 多个 active version → 最新版本优先"""

    def setUp(self):
        self.table = PolicyTable()
        self.audit = PolicyAuditLog()
        self.gov = PolicyGovernance(
            self.table, self.audit,
            min_archive_age_days=30, min_archive_hit_rate=0.3,
        )

    def _seed_conflict(self):
        """构造冲突: 同 trigger 两个 active 版本"""
        self.table.upsert(trigger="c1", strategy="v1", kind="failure",
                          action_type="pick")
        self.table.upsert_version(trigger="c1", strategy="v2", kind="failure",
                                  action_type="pick")
        vers = self.table.all_versions("c1")
        vers[0].set_status(POLICY_STATUS_ACTIVE)

    def test_no_conflict_single_version(self):
        """单版本 → 无冲突"""
        self.table.upsert(trigger="c1", strategy="v1", kind="failure",
                          action_type="pick")
        r = self.gov.conflicting_policies()
        self.assertEqual(r["total"], 0)

    def test_conflict_detected(self):
        """双 active 版本 → 检出冲突, keeper=最新版本"""
        self._seed_conflict()
        r = self.gov.conflicting_policies()
        self.assertEqual(r["total"], 1)
        c = r["conflicts"][0]
        self.assertEqual(c["trigger"], "c1")
        self.assertEqual(c["keeper"], 2)
        self.assertEqual(c["outdated"], [1])

    def test_resolve_conflicts_dry_run(self):
        """resolve_conflicts(dry_run=True) → 不修改状态"""
        self._seed_conflict()
        r = self.gov.resolve_conflicts(dry_run=True)
        self.assertTrue(r["dry_run"])
        vers = self.table.all_versions("c1")
        self.assertTrue(all(v.effective_status == POLICY_STATUS_ACTIVE for v in vers))
        self.assertEqual(self.audit.count(), 0)

    def test_resolve_conflicts_execute(self):
        """resolve_conflicts(dry_run=False) → 旧版本归档, 最新保留 active"""
        self._seed_conflict()
        r = self.gov.resolve_conflicts(dry_run=False)
        self.assertEqual(len(r["resolved"]), 1)
        self.assertEqual(r["resolved"][0]["archived_versions"], [1])
        by_version = {v.version: v for v in self.table.all_versions("c1")}
        self.assertEqual(by_version[1].effective_status, POLICY_STATUS_ARCHIVED)
        self.assertEqual(by_version[2].effective_status, POLICY_STATUS_ACTIVE)

    def test_resolve_writes_audit(self):
        """冲突解决 → 审计记录 resolve_conflict 动作"""
        self._seed_conflict()
        self.gov.resolve_conflicts(dry_run=False)
        log = self.audit.audit_policy_log(limit=0, action="resolve_conflict")
        self.assertEqual(log["total"], 1)
        self.assertIn("冲突解决", log["recent"][0]["reason"])


class TestArchiveCandidates(unittest.TestCase):
    """低效策略归档: 年龄 + hit_rate 阈值, 人工确认"""

    def setUp(self):
        self.table = PolicyTable()
        self.audit = PolicyAuditLog()
        self.gov = PolicyGovernance(
            self.table, self.audit,
            min_archive_age_days=30, min_archive_hit_rate=0.3,
        )

    def _old_low_hit(self, trigger="old_pol", age_days=40, hit_rate=0.2):
        p = self.table.upsert(trigger=trigger, strategy="s", kind="failure",
                              action_type="pick")
        p.created_at = time.time() - age_days * 86400
        p.updated_at = time.time() - age_days * 86400
        p.last_suggested_at = 0.0
        p.last_accepted_at = 0.0
        p.accepted_count = 10
        p.success_count = int(hit_rate * 10)
        return p

    def test_no_candidates_when_fresh(self):
        """新策略 → 无候选"""
        self.table.upsert(trigger="new", strategy="s", kind="failure",
                          action_type="pick")
        r = self.gov.archive_candidates()
        self.assertEqual(r["total"], 0)

    def test_candidate_detected(self):
        """年龄>30 天且 hit_rate<0.3 → 候选"""
        self._old_low_hit()
        r = self.gov.archive_candidates()
        self.assertEqual(r["total"], 1)
        c = r["candidates"][0]
        self.assertEqual(c["trigger"], "old_pol")
        self.assertGreaterEqual(c["age_days"], 30)
        self.assertLess(c["hit_rate"], 0.3)
        self.assertIn("人工确认", c["reason"])

    def test_high_hit_rate_not_candidate(self):
        """hit_rate 达标 → 不候选 (即使年龄大)"""
        self._old_low_hit(hit_rate=0.8)
        r = self.gov.archive_candidates()
        self.assertEqual(r["total"], 0)

    def test_young_not_candidate(self):
        """年龄不足 → 不候选 (即使 hit_rate 低)"""
        self._old_low_hit(age_days=5, hit_rate=0.1)
        r = self.gov.archive_candidates()
        self.assertEqual(r["total"], 0)

    def test_thresholds_exposed(self):
        """输出阈值 (配置驱动)"""
        r = self.gov.archive_candidates()
        self.assertEqual(r["thresholds"]["min_archive_age_days"], 30.0)
        self.assertEqual(r["thresholds"]["min_archive_hit_rate"], 0.3)

    def test_archived_not_candidate(self):
        """已归档策略不参与候选"""
        self._old_low_hit()
        self.table.archive_policy("old_pol")
        r = self.gov.archive_candidates()
        self.assertEqual(r["total"], 0)

    def test_apply_archival_without_confirm_raises(self):
        """confirm=False → 拒绝执行 (人工确认流程)"""
        self._old_low_hit()
        with self.assertRaises(GovernanceError):
            self.gov.apply_archival("old_pol", confirm=False)

    def test_apply_archival_not_candidate_raises(self):
        """非候选策略 → 拒绝归档 (防止绕过治理流程)"""
        self.table.upsert(trigger="fresh", strategy="s", kind="failure",
                          action_type="pick")
        with self.assertRaises(GovernanceError):
            self.gov.apply_archival("fresh", confirm=True)

    def test_apply_archival_missing_raises(self):
        """策略不存在 → GovernanceError"""
        with self.assertRaises(GovernanceError):
            self.gov.apply_archival("nope", confirm=True)

    def test_apply_archival_success(self):
        """confirm=True + 候选 → 归档执行 + 审计"""
        self._old_low_hit()
        r = self.gov.apply_archival("old_pol", confirm=True)
        self.assertTrue(r["applied"])
        self.assertEqual(self.table.get("old_pol").effective_status,
                         POLICY_STATUS_ARCHIVED)
        log = self.audit.audit_policy_log(limit=0, action="apply_archival")
        self.assertEqual(log["total"], 1)

    def test_apply_archival_idempotent(self):
        """已归档 → 幂等返回"""
        self._old_low_hit()
        self.gov.apply_archival("old_pol", confirm=True)
        r = self.gov.apply_archival("old_pol", confirm=True)
        self.assertTrue(r["applied"])
        self.assertIn("幂等", r["reason"])


class TestRecycleBin(unittest.TestCase):
    """策略回收站: 两阶段删除 archived → deleted(retained) → purge"""

    def setUp(self):
        self.table = PolicyTable()
        self.audit = PolicyAuditLog()
        self.gov = PolicyGovernance(
            self.table, self.audit,
            min_archive_age_days=30, min_archive_hit_rate=0.3,
        )

    def test_delete_to_recycle_bin(self):
        """软删除 → deleted 状态 + 审计"""
        self.table.upsert(trigger="d", strategy="s", kind="failure",
                          action_type="pick")
        r = self.gov.delete_policy("d")
        self.assertTrue(r["applied"])
        self.assertEqual(self.table.get("d").effective_status, POLICY_STATUS_DELETED)
        self.assertGreater(self.table.get("d").deleted_at, 0)
        log = self.audit.audit_policy_log(limit=0, action="archive")
        self.assertEqual(log["total"], 1)

    def test_delete_missing_raises(self):
        """删除不存在的策略 → GovernanceError"""
        with self.assertRaises(GovernanceError):
            self.gov.delete_policy("nope")

    def test_recycle_bin_lists_deleted(self):
        """recycle_bin 只列出 deleted 策略 (最新删除在前)"""
        self.table.upsert(trigger="x", strategy="s", kind="failure",
                          action_type="pick")
        self.table.upsert(trigger="y", strategy="s", kind="failure",
                          action_type="pick")
        self.gov.delete_policy("x")
        self.gov.delete_policy("y")
        r = self.gov.recycle_bin()
        triggers = {e["trigger"] for e in r["entries"]}
        self.assertEqual(triggers, {"x", "y"})
        self.assertNotIn("z", triggers)

    def test_restore_from_recycle_bin(self):
        """回收站恢复 → active + 审计 restore"""
        self.table.upsert(trigger="d", strategy="s", kind="failure",
                          action_type="pick")
        self.gov.delete_policy("d")
        r = self.gov.restore_policy("d")
        self.assertTrue(r["applied"])
        self.assertEqual(self.table.get("d").effective_status, POLICY_STATUS_ACTIVE)
        log = self.audit.audit_policy_log(limit=0, action="restore")
        self.assertEqual(log["total"], 1)

    def test_restore_archived_policy(self):
        """归档策略也能恢复 (V4.4 兼容)"""
        self.table.upsert(trigger="a", strategy="s", kind="failure",
                          action_type="pick")
        self.table.archive_policy("a")
        self.gov.restore_policy("a")
        self.assertEqual(self.table.get("a").effective_status, POLICY_STATUS_ACTIVE)

    def test_purge_without_confirm_raises(self):
        """purge 不可逆 → confirm=False 拒绝"""
        self.table.upsert(trigger="p", strategy="s", kind="failure",
                          action_type="pick")
        with self.assertRaises(GovernanceError):
            self.gov.purge_policy("p", confirm=False)

    def test_purge_removes_permanently(self):
        """purge → 彻底删除 (当前表 + 历史移除)"""
        self.table.upsert(trigger="p", strategy="s", kind="failure",
                          action_type="pick")
        self.table.upsert_version(trigger="p", strategy="s2", kind="failure",
                                  action_type="pick")
        r = self.gov.purge_policy("p", confirm=True)
        self.assertTrue(r["applied"])
        self.assertIsNone(self.table.get("p"))
        self.assertEqual(self.table.all_versions("p"), [])
        log = self.audit.audit_policy_log(limit=0, action="purge")
        self.assertEqual(log["total"], 1)

    def test_purge_missing_raises(self):
        """purge 不存在的策略 → GovernanceError"""
        with self.assertRaises(GovernanceError):
            self.gov.purge_policy("nope", confirm=True)


class TestGovernanceThroughService(unittest.TestCase):
    """治理 API 经 Service 门面访问 (策略表 + 审计日志双向一致性)"""

    def setUp(self):
        self.svc = EmbodiedService()
        self.svc.load_config({
            "embodied_enabled": True,
            "embodied_policy_min_archive_age_days": 30,
            "embodied_policy_min_archive_hit_rate": 0.3,
        })
        self.table = self.svc._experience.table

    def test_service_exposes_governance(self):
        """Service.governance 门面可用"""
        gov = self.svc.governance
        self.assertIsInstance(gov, StrategyGovernance)
        status = gov.status()
        self.assertEqual(status["version"], "9.5.0")
        self.assertEqual(status["mode"], "rule_based")

    def test_redundant_through_service(self):
        """冗余检测经 Service"""
        self.table.upsert(trigger="a", strategy="s", kind="failure",
                          action_type="pick", scene="room")
        self.table.upsert(trigger="b", strategy="s", kind="failure",
                          action_type="pick", scene="room")
        r = self.svc.redundant_policies()
        self.assertEqual(r["total"], 1)
        self.assertEqual(self.svc.archive_redundant_policies(dry_run=False)["total"], 1)
        self.assertEqual(
            self.svc.audit_policy_log(limit=0, action="archive_redundant")["total"],
            1,
        )

    def test_config_driven_thresholds(self):
        """阈值经配置注入"""
        svc = EmbodiedService()
        svc.load_config({
            "embodied_policy_min_archive_age_days": 7,
            "embodied_policy_min_archive_hit_rate": 0.5,
        })
        th = svc.governance.thresholds()
        self.assertEqual(th["min_archive_age_days"], 7.0)
        self.assertEqual(th["min_archive_hit_rate"], 0.5)

    def test_governance_does_not_touch_permission(self):
        """治理动作不触碰 Permission 层 (默认拒绝保持)"""
        self.svc.load_config({"embodied_enabled": False})
        self.table.upsert(trigger="a", strategy="s", kind="failure",
                          action_type="pick", scene="room")
        self.table.upsert(trigger="b", strategy="s", kind="failure",
                          action_type="pick", scene="room")
        r = self.svc.archive_redundant_policies(dry_run=False)
        self.assertEqual(len(r["archived"]), 1)
        perm = self.svc.get_permission()
        self.assertFalse(perm["embodied_enabled"])

    def test_restore_policy_service_compat(self):
        """Service.restore_policy 返回 dict / None (V4.4 兼容)"""
        self.table.upsert(trigger="d", strategy="s", kind="failure",
                          action_type="pick")
        self.svc.delete_policy("d")
        d = self.svc.restore_policy("d")
        self.assertIsInstance(d, dict)
        self.assertEqual(self.svc.restore_policy("missing"), None)


if __name__ == "__main__":
    unittest.main()
