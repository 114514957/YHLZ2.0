"""
YHLZ Embodied AI V4.5 - 策略健康检查 (Policy Health Check) + 场景覆盖 (Scene Coverage)

职责:
    - policy_health_check(): 输出 healthy / weak / stale / conflict / redundant
      并生成整体健康评分 (0.0 ~ 1.0)
    - scene_coverage(): 策略覆盖范围分析 → 覆盖率 / 未覆盖场景

健康分类规则 (可解释):
    - conflict:    同一 trigger 存在多个 active 版本 (冲突)
    - redundant:   active 且被冗余检测判定 (同维度同内容)
    - stale:       status == stale (老化)
    - weak:        status == degraded 或 hit_rate < weak 阈值 或 acceptance_rate < 0.2
    - healthy:     其余
    - archived / deleted: 单独标记 (不参与健康评分)

安全约束:
    - 只读分析: 本模块不修改任何状态
    - 纯规则 + 统计 + 阈值 (禁止黑盒)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List

from backend.embodied.environment.mock import SCENES
from backend.embodied.experience.policy import (
    POLICY_STATUS_ACTIVE,
    POLICY_STATUS_DEGRADED,
    POLICY_STATUS_DELETED,
    POLICY_STATUS_STALE,
    PolicyTable,
)

logger = logging.getLogger(__name__)


class HealthError(Exception):
    """策略健康检查操作异常"""


class PolicyHealthCheck:
    """策略健康检查 (规则驱动)

    用法:
        hc = PolicyHealthCheck(table, weak_hit_rate=0.3, weak_acceptance_rate=0.2)
        report = hc.policy_health_check()
        coverage = hc.scene_coverage()
    """

    def __init__(
        self,
        table: PolicyTable,
        weak_hit_rate: float = 0.3,
        weak_acceptance_rate: float = 0.2,
    ):
        if not (0.0 <= weak_hit_rate <= 1.0):
            raise HealthError(f"weak_hit_rate 必须在 [0,1], 当前: {weak_hit_rate}")
        if not (0.0 <= weak_acceptance_rate <= 1.0):
            raise HealthError(
                f"weak_acceptance_rate 必须在 [0,1], 当前: {weak_acceptance_rate}"
            )
        self._lock = threading.RLock()
        self._table = table
        self._weak_hit_rate = float(weak_hit_rate)
        self._weak_acceptance_rate = float(weak_acceptance_rate)

    # ── 健康检查 ──────────────────────────────────────────────────
    @staticmethod
    def _freeze(seq) -> tuple:
        """序列化动作序列为可哈希形式 (dict → 排序 key=value 元组)"""
        return tuple(
            tuple(sorted(d.items()))
            if isinstance(d, dict)
            else (("value", d),)
            for d in (seq or [])
        )

    def _conflict_triggers(self) -> set:
        """冲突 trigger 集合 (同一 trigger 多个 active 版本)"""
        triggers = {p.trigger for p in self._table.all(limit=0)}
        out: set = set()
        for trigger in triggers:
            actives = [
                v for v in self._table.all_versions(trigger)
                if v.effective_status == POLICY_STATUS_ACTIVE
            ]
            if len(actives) > 1:
                out.add(trigger)
        return out

    def _redundant_triggers(self) -> set:
        """冗余 trigger 集合 (同维度同内容 active)"""
        groups: Dict[tuple, List[Any]] = {}
        for p in self._table.all(limit=0):
            if p.effective_status != POLICY_STATUS_ACTIVE:
                continue
            key = (p.scene, p.goal_type, p.kind, p.action_type,
                   self._freeze(p.action_sequence),
                   p.strategy, p.detail)
            groups.setdefault(key, []).append(p)
        out: set = set()
        for key, members in groups.items():
            if len(members) > 1:
                same_sorted = sorted(members, key=lambda p: p.created_at)
                for r in same_sorted[1:]:
                    out.add(r.trigger)
        return out

    def _classify(self, p: Any, conflict_set: set, redundant_set: set) -> str:
        """单策略健康分类 (规则驱动, 优先级: conflict > redundant > stale > weak)"""
        status = p.effective_status
        if status == POLICY_STATUS_DELETED:
            return "deleted"
        if status == "archived":
            return "archived"
        if p.trigger in conflict_set:
            return "conflict"
        if p.trigger in redundant_set:
            return "redundant"
        if status == POLICY_STATUS_STALE:
            return "stale"
        if status == POLICY_STATUS_DEGRADED:
            return "weak"
        if p.accepted_count > 0 and p.hit_rate < self._weak_hit_rate:
            return "weak"
        if p.suggest_count > 0 and p.acceptance_rate < self._weak_acceptance_rate:
            return "weak"
        return "healthy"

    def policy_health_check(self) -> Dict[str, Any]:
        """策略健康检查

        Returns:
            {
                'mode': 'rule_based',
                'thresholds': {'weak_hit_rate', 'weak_acceptance_rate'},
                'policies': [
                    {'trigger', 'status', 'version', 'health',
                     'hit_rate', 'acceptance_rate', 'reason'}, ...
                ],
                'summary': {'healthy', 'weak', 'stale', 'conflict',
                            'redundant', 'archived', 'deleted'},
                'health_score': 0.0 ~ 1.0,   # healthy / 非删除总数
            }
        """
        with self._lock:
            policies = self._table.all(limit=0)
        conflict_set = self._conflict_triggers()
        redundant_set = self._redundant_triggers()
        reasons: Dict[str, str] = {
            "healthy": "质量达标, 无冲突 / 冗余 / 老化",
            "weak": f"低质量: degraded 或 hit_rate < {self._weak_hit_rate} "
                    f"或 acceptance_rate < {self._weak_acceptance_rate}",
            "stale": "老化: 超过 max_age_days 无使用",
            "conflict": "冲突: 同一 trigger 存在多个 active 版本",
            "redundant": "冗余: 同维度同内容存在多个 active 策略",
            "archived": "已归档 (不参与建议)",
            "deleted": "回收站 (deleted, retained)",
        }
        entries: List[Dict[str, Any]] = []
        summary: Dict[str, int] = {
            "healthy": 0, "weak": 0, "stale": 0, "conflict": 0,
            "redundant": 0, "archived": 0, "deleted": 0,
        }
        for p in policies:
            health = self._classify(p, conflict_set, redundant_set)
            summary[health] = summary.get(health, 0) + 1
            entries.append({
                "trigger": p.trigger,
                "status": p.effective_status,
                "version": p.version,
                "health": health,
                "hit_rate": p.hit_rate,
                "acceptance_rate": p.acceptance_rate,
                "reason": reasons[health],
            })
        entries.sort(key=lambda e: (e["health"], e["trigger"]))
        scored_total = sum(
            n for k, n in summary.items() if k not in ("archived", "deleted")
        )
        health_score = (
            round(summary["healthy"] / scored_total, 4) if scored_total else 0.0
        )
        return {
            "mode": "rule_based",
            "thresholds": {
                "weak_hit_rate": self._weak_hit_rate,
                "weak_acceptance_rate": self._weak_acceptance_rate,
            },
            "policies": entries,
            "summary": summary,
            "health_score": health_score,
        }

    # ── 场景覆盖 (P1) ─────────────────────────────────────────────
    def scene_coverage(self) -> Dict[str, Any]:
        """策略覆盖范围分析

        Returns:
            {
                'known_scenes': ['room', 'warehouse'],
                'covered_scenes': [...],
                'uncovered_scenes': [...],
                'custom_scenes': [...],        # 策略中出现但不在内置场景表
                'coverage_rate': 0.0 ~ 1.0,
                'by_scene': {'room': {'policy_count': n, 'active': n}, ...},
            }
        """
        known = set(SCENES.keys())
        with self._lock:
            policies = [
                p for p in self._table.all(limit=0)
                if p.effective_status != POLICY_STATUS_DELETED
            ]
        covered: set = set()
        custom: set = set()
        by_scene: Dict[str, Dict[str, int]] = {}
        for p in policies:
            scene = p.scene or "*"
            if p.scene:
                (covered if p.scene in known else custom).add(p.scene)
            cell = by_scene.setdefault(scene, {"policy_count": 0, "active": 0})
            cell["policy_count"] += 1
            if p.effective_status == POLICY_STATUS_ACTIVE:
                cell["active"] += 1
        uncovered = known - covered
        coverage_rate = (
            round(len(covered & known) / len(known), 4) if known else 0.0
        )
        return {
            "known_scenes": sorted(known),
            "covered_scenes": sorted(covered & known),
            "uncovered_scenes": sorted(uncovered),
            "custom_scenes": sorted(custom),
            "coverage_rate": coverage_rate,
            "by_scene": dict(sorted(by_scene.items())),
        }


__all__ = ["PolicyHealthCheck", "HealthError"]
