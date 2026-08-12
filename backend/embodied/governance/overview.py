"""
YHLZ Embodied AI V4.5 - 策略体系总览 (Strategy System Overview)

职责:
    - strategy_system_overview(): 策略矩阵 (scene × goal_type × kind) + 全体系统计
    - 统计: 策略数量 / active / degraded / stale / archived / deleted / 整体质量
    - 质量: 平均 hit_rate / 平均 acceptance_rate / 版本数量 / 归档数量 / 老化数量
            恢复成功数量 (审计可追溯) / 版本健康度 / 最新质量变化
    - 一致性检查: 同一 trigger 只能存在一个 active 当前版本 (返回违规清单)
    - strategy_system_report(): 生成文本报告

设计原则:
    - 只读分析: 本模块不做任何状态修改 (治理动作由 governance 模块执行)
    - 规则 + 统计 + 阈值: 纯可解释输出, 禁止黑盒学习
    - 数据独立: 不写入 Agent Memory
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List, Optional

from backend.embodied.experience.policy import (
    POLICY_STATUS_ACTIVE,
    POLICY_STATUS_ARCHIVED,
    POLICY_STATUS_DEGRADED,
    POLICY_STATUS_DELETED,
    POLICY_STATUS_STALE,
    PolicyTable,
)
from backend.embodied.strategy.audit import PolicyAuditLog

logger = logging.getLogger(__name__)


class OverviewError(Exception):
    """策略体系总览操作异常"""


class StrategySystemOverview:
    """策略体系总览 (只读分析)

    用法:
        overview = StrategySystemOverview(table, audit)
        report = overview.strategy_system_overview()
        text = overview.strategy_system_report()
    """

    def __init__(
        self,
        table: PolicyTable,
        audit: PolicyAuditLog,
        min_archive_age_days: float = 30.0,
        min_archive_hit_rate: float = 0.3,
    ):
        if min_archive_age_days <= 0:
            raise OverviewError(
                f"min_archive_age_days 必须 > 0, 当前: {min_archive_age_days}"
            )
        if not (0.0 <= min_archive_hit_rate <= 1.0):
            raise OverviewError(
                f"min_archive_hit_rate 必须在 [0,1], 当前: {min_archive_hit_rate}"
            )
        self._lock = threading.RLock()
        self._table = table
        self._audit = audit
        self._min_archive_age_days = float(min_archive_age_days)
        self._min_archive_hit_rate = float(min_archive_hit_rate)

    # ── 策略矩阵 (scene × goal_type × kind) ───────────────────────
    def _build_matrix(self, policies: List[Any]) -> Dict[str, Any]:
        """策略矩阵: {scene: {goal_type: {kind: count}}}"""
        matrix: Dict[str, Dict[str, Dict[str, int]]] = {}
        for p in policies:
            scene = p.scene or "*"
            goal_type = p.goal_type or "*"
            kind = p.kind
            matrix.setdefault(scene, {}).setdefault(goal_type, {})
            c = matrix[scene][goal_type]
            c[kind] = c.get(kind, 0) + 1
        return matrix

    # ── 一致性检查: 同一 trigger 只能存在一个 active 当前版本 ─────
    def _consistency_violations(self) -> List[Dict[str, Any]]:
        """检查"同一 trigger 只能存在一个 active 当前版本"不变式

        违规 = 当前版本 active 且历史版本中存在 active 版本。
        """
        violations: List[Dict[str, Any]] = []
        for p in self._table.all(limit=0):
            if p.effective_status != POLICY_STATUS_ACTIVE:
                continue
            versions = self._table.all_versions(p.trigger)
            actives = [
                v for v in versions if v.effective_status == POLICY_STATUS_ACTIVE
            ]
            if len(actives) > 1:
                violations.append({
                    "trigger": p.trigger,
                    "active_versions": [v.version for v in actives],
                    "current_version": p.version,
                    "suggestion": "旧 active 版本应归档 (resolve_conflicts)",
                })
        return violations

    # ── 版本健康度 + 最新质量变化 ─────────────────────────────────
    def _version_analysis(self) -> Dict[str, Any]:
        """版本健康度 + 最新质量变化 (当前版本 vs 上一版本)"""
        healthy_versions = 0
        versioned_triggers = 0
        regressions: List[Dict[str, Any]] = []
        quality_changes: List[Dict[str, Any]] = []
        for p in self._table.all(limit=0):
            versions = self._table.all_versions(p.trigger)
            if len(versions) < 2:
                continue
            versioned_triggers += 1
            cur = versions[-1]
            prev = versions[-2]
            cur_hr = cur.hit_rate
            prev_hr = prev.hit_rate
            regression = cur_hr < prev_hr
            if not regression:
                healthy_versions += 1
            else:
                regressions.append({
                    "trigger": p.trigger,
                    "current_version": cur.version,
                    "previous_version": prev.version,
                    "current_hit_rate": cur_hr,
                    "previous_hit_rate": prev_hr,
                })
            quality_changes.append({
                "trigger": p.trigger,
                "current_version": cur.version,
                "previous_version": prev.version,
                "hit_rate_delta": round(cur_hr - prev_hr, 4),
                "verdict": "regression" if regression else "healthy",
            })
        return {
            "versioned_triggers": versioned_triggers,
            "healthy_versions": healthy_versions,
            "regressions": regressions,
            "quality_changes": quality_changes,
            "version_health": (
                round(healthy_versions / versioned_triggers, 4)
                if versioned_triggers else 0.0
            ),
        }

    # ── 总览 ──────────────────────────────────────────────────────
    def strategy_system_overview(self) -> Dict[str, Any]:
        """策略体系总览

        Returns:
            {
                'generated_at', 'mode': 'rule_based',
                'matrix': {scene: {goal_type: {kind: count}}},
                'stats': {
                    'total', 'active', 'degraded', 'stale', 'archived',
                    'deleted', 'version_total', 'archived_count',
                    'stale_count', 'recovered_count',
                },
                'quality': {
                    'avg_hit_rate', 'avg_acceptance_rate',
                    'version_health', 'latest_quality_changes',
                },
                'consistency': {
                    'ok', 'violations': [...],
                    'rule': '同一 trigger 只能存在一个 active 当前版本',
                },
            }
        """
        with self._lock:
            policies = self._table.all(limit=0)
        non_deleted = [
            p for p in policies if p.effective_status != POLICY_STATUS_DELETED
        ]
        active = [p for p in policies if p.effective_status == POLICY_STATUS_ACTIVE]
        degraded = [p for p in policies if p.effective_status == POLICY_STATUS_DEGRADED]
        stale = [p for p in policies if p.effective_status == POLICY_STATUS_STALE]
        archived = [p for p in policies if p.effective_status == POLICY_STATUS_ARCHIVED]
        deleted = [p for p in policies if p.effective_status == POLICY_STATUS_DELETED]

        # 平均质量 (非删除策略)
        def avg(fn, items):
            if not items:
                return 0.0
            return round(sum(fn(x) for x in items) / len(items), 4)

        # 恢复成功数量 (审计可追溯: 自动恢复 recover + 人工恢复 restore)
        audit = self._audit.audit_policy_log(limit=0)
        recovered_count = sum(
            e["applied"] and e["action"] in ("recover", "restore")
            for e in self._audit.entries(limit=0)
        )

        violations = self._consistency_violations()
        version_analysis = self._version_analysis()

        return {
            "generated_at": time.time(),
            "mode": "rule_based",
            "matrix": self._build_matrix(non_deleted),
            "stats": {
                "total": len(non_deleted),
                "active": len(active),
                "degraded": len(degraded),
                "stale": len(stale),
                "archived": len(archived),
                "deleted": len(deleted),
                "version_total": self._table.stats()["version_total"],
                "archived_count": len(archived),
                "stale_count": len(stale),
                "recovered_count": recovered_count,
            },
            "quality": {
                "avg_hit_rate": avg(lambda p: p.hit_rate, non_deleted),
                "avg_acceptance_rate": avg(lambda p: p.acceptance_rate, non_deleted),
                "version_health": version_analysis["version_health"],
                "latest_quality_changes": version_analysis["quality_changes"],
                "regressions": version_analysis["regressions"],
            },
            "consistency": {
                "ok": not violations,
                "violations": violations,
                "rule": "同一 trigger 只能存在一个 active 当前版本",
            },
        }

    # ── 文本报告 ──────────────────────────────────────────────────
    def strategy_system_report(self) -> str:
        """策略体系总览文本报告 (管理界面 / 审计展示)"""
        o = self.strategy_system_overview()
        s = o["stats"]
        q = o["quality"]
        c = o["consistency"]
        lines = [
            "[Strategy System Overview (V4.5 Meta Strategy Management)]",
            f"mode: {o['mode']}  generated_at: {o['generated_at']:.2f}",
            f"Policies: total={s['total']} active={s['active']} "
            f"degraded={s['degraded']} stale={s['stale']} "
            f"archived={s['archived']} deleted={s['deleted']}",
            f"Versions: version_total={s['version_total']} "
            f"archived_count={s['archived_count']} stale_count={s['stale_count']} "
            f"recovered_count={s['recovered_count']}",
            f"Quality: avg_hit_rate={q['avg_hit_rate']} "
            f"avg_acceptance_rate={q['avg_acceptance_rate']} "
            f"version_health={q['version_health']}",
            f"Consistency: ok={c['ok']} violations={len(c['violations'])}",
        ]
        for v in c["violations"]:
            lines.append(
                f"  [violation] trigger={v['trigger']} "
                f"active_versions={v['active_versions']}"
            )
        for r in q["regressions"]:
            lines.append(
                f"  [regression] {r['trigger']} v{r['current_version']} "
                f"hit_rate {r['previous_hit_rate']} → {r['current_hit_rate']}"
            )
        lines.append("Matrix (scene × goal_type × kind):")
        for scene, gtypes in sorted(o["matrix"].items()):
            for gt, kinds in sorted(gtypes.items()):
                parts = ", ".join(f"{k}={n}" for k, n in sorted(kinds.items()))
                lines.append(f"  {scene} × {gt}: {parts}")
        return "\n".join(lines)

    # ── 状态 ──────────────────────────────────────────────────────
    def thresholds(self) -> Dict[str, float]:
        with self._lock:
            return {
                "min_archive_age_days": self._min_archive_age_days,
                "min_archive_hit_rate": self._min_archive_hit_rate,
            }


__all__ = ["StrategySystemOverview", "OverviewError"]
