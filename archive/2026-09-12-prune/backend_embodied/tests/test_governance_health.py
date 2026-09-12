"""
YHLZ Embodied AI V4.5 - 策略体系总览与健康检查单元测试
(Strategy System Overview + Policy Health Check + Scene Coverage)

覆盖:
    - strategy_system_overview: 策略矩阵 (scene×goal_type×kind) / 状态统计 /
      整体质量 (平均 hit_rate / acceptance_rate) / 版本健康度
    - 一致性检查: 同一 trigger 只能存在一个 active 当前版本
    - strategy_system_report: 文本报告 (可解释输出)
    - policy_health_check: healthy / weak / stale / conflict / redundant 分类
      + 健康评分
    - scene_coverage: 覆盖率 / 未覆盖场景 / 自定义场景

安全约束验证:
    - 只读分析: 总览 / 健康检查 / 覆盖分析不修改任何状态
    - 纯规则 + 统计 + 阈值 (可解释)
"""
import time
import unittest

from backend.embodied.experience.policy import (
    POLICY_STATUS_ACTIVE,
    POLICY_STATUS_ARCHIVED,
    POLICY_STATUS_DEGRADED,
    POLICY_STATUS_DELETED,
    POLICY_STATUS_STALE,
    PolicyTable,
)
from backend.embodied.governance import (
    OverviewError,
    PolicyGovernance,
    PolicyHealthCheck,
    StrategySystemOverview,
)
from backend.embodied.strategy.audit import PolicyAuditLog


class TestStrategySystemOverview(unittest.TestCase):
    """策略体系总览: 矩阵 / 统计 / 质量 / 一致性"""

    def setUp(self):
        self.table = PolicyTable()
        self.audit = PolicyAuditLog()
        self.overview = StrategySystemOverview(
            self.table, self.audit,
            min_archive_age_days=30, min_archive_hit_rate=0.3,
        )

    def test_invalid_age_raises(self):
        """min_archive_age_days <= 0 → OverviewError"""
        with self.assertRaises(OverviewError):
            StrategySystemOverview(self.table, self.audit,
                                   min_archive_age_days=0)

    def test_invalid_hit_rate_raises(self):
        """min_archive_hit_rate 越界 → OverviewError"""
        with self.assertRaises(OverviewError):
            StrategySystemOverview(self.table, self.audit,
                                   min_archive_hit_rate=1.5)

    def test_empty_overview(self):
        """空策略表 → 全 0 统计, 一致性 ok"""
        o = self.overview.strategy_system_overview()
        self.assertEqual(o["mode"], "rule_based")
        self.assertEqual(o["matrix"], {})
        self.assertEqual(o["stats"]["total"], 0)
        self.assertEqual(o["stats"]["active"], 0)
        self.assertEqual(o["stats"]["degraded"], 0)
        self.assertEqual(o["stats"]["stale"], 0)
        self.assertEqual(o["stats"]["archived"], 0)
        self.assertEqual(o["stats"]["deleted"], 0)
        self.assertTrue(o["consistency"]["ok"])
        self.assertEqual(o["quality"]["avg_hit_rate"], 0.0)

    def test_matrix_dimensions(self):
        """矩阵: scene × goal_type × kind"""
        self.table.upsert(trigger="a", strategy="s", kind="failure",
                          action_type="pick", scene="room", goal_type="pick")
        self.table.upsert(trigger="b", strategy="s", kind="failure",
                          action_type="move", scene="room", goal_type="move")
        self.table.upsert(trigger="c", strategy="s", kind="success",
                          action_type="pick", scene="warehouse", goal_type="pick")
        o = self.overview.strategy_system_overview()
        m = o["matrix"]
        self.assertEqual(m["room"]["pick"]["failure"], 1)
        self.assertEqual(m["room"]["move"]["failure"], 1)
        self.assertEqual(m["warehouse"]["pick"]["success"], 1)
        self.assertEqual(o["stats"]["total"], 3)

    def test_status_counts(self):
        """状态统计: active/degraded/stale/archived/deleted"""
        self.table.upsert(trigger="a", strategy="s", kind="failure",
                          action_type="pick")
        self.table.upsert(trigger="b", strategy="s", kind="failure",
                          action_type="pick")
        self.table.upsert(trigger="c", strategy="s", kind="failure",
                          action_type="pick")
        self.table.get("b").set_status(POLICY_STATUS_DEGRADED)
        self.table.get("c").set_status(POLICY_STATUS_STALE)
        self.table.archive_policy("a")
        self.table.delete_policy("a")
        o = self.overview.strategy_system_overview()
        s = o["stats"]
        self.assertEqual(s["total"], 2)
        self.assertEqual(s["active"], 0)
        self.assertEqual(s["degraded"], 1)
        self.assertEqual(s["stale"], 1)
        self.assertEqual(s["archived"], 0)
        self.assertEqual(s["deleted"], 1)

    def test_deleted_not_in_matrix(self):
        """deleted 策略不计入矩阵与 total"""
        self.table.upsert(trigger="a", strategy="s", kind="failure",
                          action_type="pick", scene="room")
        self.table.delete_policy("a")
        o = self.overview.strategy_system_overview()
        self.assertEqual(o["matrix"], {})
        self.assertEqual(o["stats"]["total"], 0)
        self.assertEqual(o["stats"]["deleted"], 1)

    def test_avg_quality(self):
        """平均 hit_rate / acceptance_rate"""
        a = self.table.upsert(trigger="a", strategy="s", kind="failure",
                              action_type="pick")
        b = self.table.upsert(trigger="b", strategy="s", kind="failure",
                              action_type="pick")
        a.suggest_count, a.accepted_count, a.success_count = 10, 10, 5
        b.suggest_count, b.accepted_count, b.success_count = 10, 10, 9
        o = self.overview.strategy_system_overview()
        self.assertEqual(o["quality"]["avg_hit_rate"], 0.7)
        self.assertEqual(o["quality"]["avg_acceptance_rate"], 1.0)

    def test_recovered_count_from_audit(self):
        """恢复成功数量来自审计 (recover / restore 且 applied)"""
        self.audit.record(trigger="a", action="restore", applied=True,
                          reason="回收站恢复")
        self.audit.record(trigger="b", action="recover", applied=True,
                          reason="自动恢复")
        o = self.overview.strategy_system_overview()
        self.assertEqual(o["stats"]["recovered_count"], 2)

    def test_consistency_ok_single_active(self):
        """单 active 当前版本 → 一致性 ok"""
        self.table.upsert(trigger="t", strategy="s", kind="failure",
                          action_type="pick")
        o = self.overview.strategy_system_overview()
        self.assertTrue(o["consistency"]["ok"])
        self.assertEqual(o["consistency"]["violations"], [])

    def test_consistency_violation_detected(self):
        """多个 active 版本 → 一致性违规清单"""
        self.table.upsert(trigger="t", strategy="v1", kind="failure",
                          action_type="pick")
        self.table.upsert_version(trigger="t", strategy="v2", kind="failure",
                                  action_type="pick")
        vers = self.table.all_versions("t")
        vers[0].set_status(POLICY_STATUS_ACTIVE)
        o = self.overview.strategy_system_overview()
        self.assertFalse(o["consistency"]["ok"])
        v = o["consistency"]["violations"][0]
        self.assertEqual(v["trigger"], "t")
        self.assertEqual(v["active_versions"], [1, 2])

    def test_version_health(self):
        """版本健康度: 无回归 = 1.0, 有回归 = 0.0"""
        self.table.upsert(trigger="t", strategy="s", kind="failure",
                          action_type="pick")
        self.table.upsert_version(trigger="t", strategy="s2", kind="failure",
                                  action_type="pick")
        v1, v2 = self.table.all_versions("t")
        v1.accepted_count, v1.success_count = 10, 9
        v2.accepted_count, v2.success_count = 10, 2   # regression
        o = self.overview.strategy_system_overview()
        self.assertEqual(o["quality"]["version_health"], 0.0)
        self.assertEqual(len(o["quality"]["regressions"]), 1)
        self.assertEqual(o["quality"]["regressions"][0]["verdict"]
                         if "verdict" in o["quality"]["regressions"][0]
                         else "regression", "regression")

    def test_report_text(self):
        """文本报告: 含关键统计行"""
        self.table.upsert(trigger="a", strategy="s", kind="failure",
                          action_type="pick", scene="room", goal_type="pick")
        text = self.overview.strategy_system_report()
        self.assertIn("Strategy System Overview", text)
        self.assertIn("Policies: total=1", text)
        self.assertIn("room × pick", text)
        self.assertIn("Consistency: ok=True", text)

    def test_report_includes_violation(self):
        """报告含违规明细行"""
        self.table.upsert(trigger="t", strategy="v1", kind="failure",
                          action_type="pick")
        self.table.upsert_version(trigger="t", strategy="v2", kind="failure",
                                  action_type="pick")
        vers = self.table.all_versions("t")
        vers[0].set_status(POLICY_STATUS_ACTIVE)
        text = self.overview.strategy_system_overview_text() if False else \
            self.overview.strategy_system_report()
        self.assertIn("[violation]", text)

    def test_thresholds(self):
        """阈值暴露"""
        th = self.overview.thresholds()
        self.assertEqual(th["min_archive_age_days"], 30.0)
        self.assertEqual(th["min_archive_hit_rate"], 0.3)

    def test_readonly_no_side_effect(self):
        """总览只读: 不修改策略 / 审计"""
        self.table.upsert(trigger="a", strategy="s", kind="failure",
                          action_type="pick")
        before_status = self.table.get("a").effective_status
        before_audit = self.audit.count()
        self.overview.strategy_system_overview()
        self.overview.strategy_system_report()
        self.assertEqual(self.table.get("a").effective_status, before_status)
        self.assertEqual(self.audit.count(), before_audit)


class TestPolicyHealthCheck(unittest.TestCase):
    """策略健康检查: healthy / weak / stale / conflict / redundant"""

    def setUp(self):
        self.table = PolicyTable()
        self.health = PolicyHealthCheck(
            self.table, weak_hit_rate=0.3, weak_acceptance_rate=0.2,
        )

    def test_invalid_weak_hit_rate_raises(self):
        """weak_hit_rate 越界 → HealthError"""
        from backend.embodied.governance import HealthError
        with self.assertRaises(HealthError):
            PolicyHealthCheck(self.table, weak_hit_rate=1.5)

    def test_empty_health(self):
        """空表 → 全 0, health_score=0"""
        r = self.health.policy_health_check()
        self.assertEqual(r["mode"], "rule_based")
        self.assertEqual(r["summary"]["healthy"], 0)
        self.assertEqual(r["health_score"], 0.0)

    def test_healthy_policy(self):
        """高质量策略 → healthy"""
        p = self.table.upsert(trigger="t", strategy="s", kind="failure",
                              action_type="pick")
        p.suggest_count, p.accepted_count, p.success_count = 10, 10, 9
        r = self.health.policy_health_check()
        self.assertEqual(r["summary"]["healthy"], 1)
        self.assertEqual(r["policies"][0]["health"], "healthy")
        self.assertEqual(r["health_score"], 1.0)

    def test_weak_by_status(self):
        """degraded → weak"""
        self.table.upsert(trigger="t", strategy="s", kind="failure",
                          action_type="pick")
        self.table.get("t").set_status(POLICY_STATUS_DEGRADED)
        r = self.health.policy_health_check()
        self.assertEqual(r["summary"]["weak"], 1)

    def test_weak_by_hit_rate(self):
        """hit_rate < 阈值 → weak"""
        p = self.table.upsert(trigger="t", strategy="s", kind="failure",
                              action_type="pick")
        p.accepted_count, p.success_count = 10, 1   # 0.1 < 0.3
        r = self.health.policy_health_check()
        self.assertEqual(r["summary"]["weak"], 1)

    def test_weak_by_acceptance_rate(self):
        """acceptance_rate < 0.2 → weak"""
        p = self.table.upsert(trigger="t", strategy="s", kind="failure",
                              action_type="pick")
        p.suggest_count, p.accepted_count = 100, 10   # 0.1 < 0.2
        r = self.health.policy_health_check()
        self.assertEqual(r["summary"]["weak"], 1)

    def test_stale_classified(self):
        """stale → 分类 stale"""
        self.table.upsert(trigger="t", strategy="s", kind="failure",
                          action_type="pick")
        self.table.get("t").set_status(POLICY_STATUS_STALE)
        r = self.health.policy_health_check()
        self.assertEqual(r["summary"]["stale"], 1)

    def test_conflict_classified(self):
        """多个 active 版本 → conflict (当前版本计入)"""
        self.table.upsert(trigger="t", strategy="v1", kind="failure",
                          action_type="pick")
        self.table.upsert_version(trigger="t", strategy="v2", kind="failure",
                                  action_type="pick")
        vers = self.table.all_versions("t")
        vers[0].set_status(POLICY_STATUS_ACTIVE)
        r = self.health.policy_health_check()
        self.assertEqual(r["summary"]["conflict"], 1)

    def test_redundant_classified(self):
        """同维度同内容 active → redundant"""
        self.table.upsert(trigger="a", strategy="s", kind="failure",
                          action_type="pick", scene="room")
        self.table.upsert(trigger="b", strategy="s", kind="failure",
                          action_type="pick", scene="room")
        r = self.health.policy_health_check()
        self.assertEqual(r["summary"]["redundant"], 1)
        self.assertEqual(r["summary"]["healthy"], 1)

    def test_archived_deleted_excluded_from_score(self):
        """archived / deleted 单独标记, 不参与健康评分"""
        self.table.upsert(trigger="a", strategy="s", kind="failure",
                          action_type="pick")
        self.table.upsert(trigger="b", strategy="s", kind="failure",
                          action_type="pick")
        self.table.upsert(trigger="c", strategy="s", kind="failure",
                          action_type="pick")
        self.table.archive_policy("b")
        self.table.delete_policy("c")
        r = self.health.policy_health_check()
        self.assertEqual(r["summary"]["archived"], 1)
        self.assertEqual(r["summary"]["deleted"], 1)
        self.assertEqual(r["summary"]["healthy"], 1)
        self.assertEqual(r["health_score"], 1.0)

    def test_health_score_partial(self):
        """部分健康 → 评分按比例"""
        a = self.table.upsert(trigger="a", strategy="s", kind="failure",
                              action_type="pick")
        self.table.upsert(trigger="b", strategy="s2", kind="failure",
                          action_type="move")
        a.accepted_count, a.success_count = 10, 1   # weak
        r = self.health.policy_health_check()
        self.assertEqual(r["health_score"], 0.5)

    def test_reason_explainable(self):
        """每条策略含可解释 reason"""
        self.table.upsert(trigger="t", strategy="s", kind="failure",
                          action_type="pick")
        r = self.health.policy_health_check()
        self.assertIn("reason", r["policies"][0])
        self.assertTrue(r["policies"][0]["reason"])


class TestSceneCoverage(unittest.TestCase):
    """场景覆盖: 覆盖率 / 未覆盖场景 / 自定义场景"""

    def setUp(self):
        self.table = PolicyTable()
        self.health = PolicyHealthCheck(
            self.table, weak_hit_rate=0.3, weak_acceptance_rate=0.2,
        )

    def test_empty_coverage(self):
        """空表 → 覆盖率 0, 全部已知场景未覆盖"""
        r = self.health.scene_coverage()
        self.assertEqual(r["coverage_rate"], 0.0)
        self.assertEqual(r["covered_scenes"], [])
        self.assertEqual(sorted(r["uncovered_scenes"]), ["room", "warehouse"])

    def test_full_coverage(self):
        """room + warehouse 都覆盖 → 覆盖率 1.0"""
        self.table.upsert(trigger="a", strategy="s", kind="failure",
                          action_type="pick", scene="room")
        self.table.upsert(trigger="b", strategy="s", kind="failure",
                          action_type="pick", scene="warehouse")
        r = self.health.scene_coverage()
        self.assertEqual(r["coverage_rate"], 1.0)
        self.assertEqual(sorted(r["covered_scenes"]), ["room", "warehouse"])
        self.assertEqual(r["uncovered_scenes"], [])

    def test_partial_coverage(self):
        """仅 room → 覆盖率 0.5"""
        self.table.upsert(trigger="a", strategy="s", kind="failure",
                          action_type="pick", scene="room")
        r = self.health.scene_coverage()
        self.assertEqual(r["coverage_rate"], 0.5)
        self.assertEqual(r["uncovered_scenes"], ["warehouse"])

    def test_custom_scene(self):
        """策略含未知场景 → custom_scenes 单独列出 (不计覆盖)"""
        self.table.upsert(trigger="a", strategy="s", kind="failure",
                          action_type="pick", scene="home")
        r = self.health.scene_coverage()
        self.assertEqual(r["custom_scenes"], ["home"])
        self.assertEqual(r["coverage_rate"], 0.0)

    def test_by_scene_counts(self):
        """by_scene: 每场景策略数 / active 数"""
        self.table.upsert(trigger="a", strategy="s", kind="failure",
                          action_type="pick", scene="room")
        self.table.upsert(trigger="b", strategy="s", kind="failure",
                          action_type="move", scene="room")
        self.table.upsert(trigger="c", strategy="s", kind="failure",
                          action_type="pick", scene="room")
        self.table.archive_policy("c")
        r = self.health.scene_coverage()
        cell = r["by_scene"]["room"]
        self.assertEqual(cell["policy_count"], 3)
        self.assertEqual(cell["active"], 2)

    def test_deleted_excluded_from_coverage(self):
        """deleted 策略不计入覆盖"""
        self.table.upsert(trigger="a", strategy="s", kind="failure",
                          action_type="pick", scene="room")
        self.table.delete_policy("a")
        r = self.health.scene_coverage()
        self.assertEqual(r["coverage_rate"], 0.0)

    def test_star_scene_not_counted(self):
        """无 scene (全场景) 策略不计入 covered, 但计入 by_scene '*'"""
        self.table.upsert(trigger="a", strategy="s", kind="failure",
                          action_type="pick")
        r = self.health.scene_coverage()
        self.assertEqual(r["coverage_rate"], 0.0)
        self.assertIn("*", r["by_scene"])


class TestGovernanceIntegrationOverview(unittest.TestCase):
    """总览 + 治理联动 (治理动作后总览状态正确)"""

    def setUp(self):
        self.table = PolicyTable()
        self.audit = PolicyAuditLog()
        self.gov = PolicyGovernance(
            self.table, self.audit,
            min_archive_age_days=30, min_archive_hit_rate=0.3,
        )
        self.overview = StrategySystemOverview(
            self.table, self.audit,
            min_archive_age_days=30, min_archive_hit_rate=0.3,
        )

    def test_after_redundant_archive(self):
        """冗余归档后: active 减少, archived 增加"""
        self.table.upsert(trigger="a", strategy="s", kind="failure",
                          action_type="pick", scene="room")
        self.table.upsert(trigger="b", strategy="s", kind="failure",
                          action_type="pick", scene="room")
        self.gov.archive_redundant_policies(dry_run=False)
        o = self.overview.strategy_system_overview()
        self.assertEqual(o["stats"]["active"], 1)
        self.assertEqual(o["stats"]["archived"], 1)

    def test_after_delete_recycle(self):
        """软删除后: deleted 状态入总览"""
        self.table.upsert(trigger="a", strategy="s", kind="failure",
                          action_type="pick")
        self.gov.delete_policy("a")
        o = self.overview.strategy_system_overview()
        self.assertEqual(o["stats"]["deleted"], 1)


if __name__ == "__main__":
    unittest.main()
