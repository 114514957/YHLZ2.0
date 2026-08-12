"""
YHLZ Embodied AI V4.5 - 元策略治理模块 (Meta Strategy Management)

架构:
    StrategyGovernance (门面, Service 唯一入口)
        ├── StrategySystemOverview  (策略体系总览: 矩阵 / 质量 / 一致性)
        ├── PolicyGovernance        (策略治理: 冗余 / 冲突 / 低效归档 / 回收站)
        ├── PolicyEvolution         (策略进化: 同化 / 分裂 / 版本比较 / 回滚)
        ├── PolicyHealthCheck       (健康检查 + 场景覆盖)
        └── GovernanceDryRun        (治理预演统一入口 + 体系快照)

约束 (必须保持):
    - 纯规则 + 统计 + 阈值 + 可解释排序, 禁止神经网络训练 / 梯度更新 / 黑盒优化
    - 禁止自主修改策略内容 (治理动作只改变状态/归属, 内容修改仅来自经验学习规则)
    - 治理动作只影响: 策略表 → 审计日志 → 体系快照
    - 不能绕过 Permission Layer, 不写入 Agent Memory, 不控制真实设备
"""
from backend.embodied.experience.policy import PolicyTable
from backend.embodied.governance.dry_run import (
    GOVERNANCE_DRY_RUN_ACTIONS,
    DryRunError,
    GovernanceDryRun,
    SystemSnapshot,
)
from backend.embodied.governance.evolution import EvolutionError, PolicyEvolution
from backend.embodied.governance.governance import GovernanceError, PolicyGovernance
from backend.embodied.governance.health import HealthError, PolicyHealthCheck
from backend.embodied.governance.overview import OverviewError, StrategySystemOverview
from backend.embodied.strategy.audit import PolicyAuditLog

__all__ = [
    "DryRunError",
    "EvolutionError",
    "GOVERNANCE_DRY_RUN_ACTIONS",
    "GovernanceDryRun",
    "GovernanceError",
    "HealthError",
    "OverviewError",
    "PolicyEvolution",
    "PolicyGovernance",
    "PolicyHealthCheck",
    "StrategyGovernance",
    "StrategySystemOverview",
    "SystemSnapshot",
]


class StrategyGovernance:
    """元策略治理门面 (V4.5, Service 唯一接入点)

    用法:
        gov = StrategyGovernance(
            table, audit,
            min_archive_age_days=30.0, min_archive_hit_rate=0.3,
        )
        overview = gov.strategy_system_overview()
        candidates = gov.redundant_policies()
        result = gov.governance_dry_run('rollback', trigger='pick_object')
    """

    def __init__(
        self,
        table: PolicyTable,
        audit: PolicyAuditLog,
        min_archive_age_days: float = 30.0,
        min_archive_hit_rate: float = 0.3,
        weak_acceptance_rate: float = 0.2,
    ):
        self._table = table
        self._audit = audit
        self._min_archive_age_days = float(min_archive_age_days)
        self._min_archive_hit_rate = float(min_archive_hit_rate)
        self._weak_acceptance_rate = float(weak_acceptance_rate)
        self._overview = StrategySystemOverview(
            table, audit,
            min_archive_age_days=min_archive_age_days,
            min_archive_hit_rate=min_archive_hit_rate,
        )
        self._governance = PolicyGovernance(
            table, audit,
            min_archive_age_days=min_archive_age_days,
            min_archive_hit_rate=min_archive_hit_rate,
        )
        self._evolution = PolicyEvolution(table, audit)
        self._health = PolicyHealthCheck(
            table,
            weak_hit_rate=min_archive_hit_rate,
            weak_acceptance_rate=weak_acceptance_rate,
        )
        self._dry_run = GovernanceDryRun(
            self._governance, self._evolution, self._health,
        )

    # ── 一、Strategy System Overview ──────────────────────────────
    def strategy_system_overview(self) -> dict:
        """策略体系总览 (矩阵 / 质量 / 一致性检查)"""
        return self._overview.strategy_system_overview()

    def strategy_system_report(self) -> str:
        """策略体系总览文本报告"""
        return self._overview.strategy_system_report()

    # ── 二、Strategy Governance ───────────────────────────────────
    def redundant_policies(self) -> dict:
        return self._governance.redundant_policies()

    def archive_redundant_policies(self, dry_run: bool = True) -> dict:
        return self._governance.archive_redundant_policies(dry_run=dry_run)

    def conflicting_policies(self) -> dict:
        return self._governance.conflicting_policies()

    def resolve_conflicts(self, dry_run: bool = True) -> dict:
        return self._governance.resolve_conflicts(dry_run=dry_run)

    def archive_candidates(self) -> dict:
        return self._governance.archive_candidates()

    def apply_archival(self, trigger: str, confirm: bool = True) -> dict:
        return self._governance.apply_archival(trigger, confirm=confirm)

    def delete_policy(self, trigger: str) -> dict:
        return self._governance.delete_policy(trigger)

    def restore_policy(self, trigger: str) -> dict:
        return self._governance.restore_policy(trigger)

    def purge_policy(self, trigger: str, confirm: bool = True) -> dict:
        return self._governance.purge_policy(trigger, confirm=confirm)

    def recycle_bin(self, limit: int = 100) -> dict:
        return self._governance.recycle_bin(limit=limit)

    # ── 三、Strategy Evolution ────────────────────────────────────
    def consolidate_similar_policies(self, dry_run: bool = True) -> dict:
        return self._evolution.consolidate_similar_policies(dry_run=dry_run)

    def split_policy(
        self,
        trigger: str,
        by: str = "scene",
        values=None,
        dry_run: bool = True,
    ) -> dict:
        return self._evolution.split_policy(
            trigger, by=by, values=values, dry_run=dry_run,
        )

    def compare_policy_versions(self, trigger: str) -> dict:
        return self._evolution.compare_policy_versions(trigger)

    def rollback_policy(self, trigger: str, dry_run: bool = True) -> dict:
        return self._evolution.rollback_policy(trigger, dry_run=dry_run)

    def policy_families(self) -> dict:
        """Policy Family 汇总 (共享父级统计)"""
        return self._evolution.families()

    # ── P1 增强: 健康检查 + 场景覆盖 ──────────────────────────────
    def policy_health_check(self) -> dict:
        return self._health.policy_health_check()

    def scene_coverage(self) -> dict:
        return self._health.scene_coverage()

    # ── 五、治理 Dry Run 体系化 ───────────────────────────────────
    def governance_dry_run(self, action: str, **kwargs) -> dict:
        """治理预演统一入口 (只模拟不执行)"""
        return self._dry_run.run(action, **kwargs)

    # ── 状态 ──────────────────────────────────────────────────────
    def thresholds(self) -> dict:
        return self._governance.thresholds()

    def status(self) -> dict:
        return {
            "version": "9.5.0",
            "mode": "rule_based",
            "thresholds": self.thresholds(),
            "dry_run_actions": list(GOVERNANCE_DRY_RUN_ACTIONS),
        }
