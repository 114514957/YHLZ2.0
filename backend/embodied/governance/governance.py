"""
YHLZ Embodied AI V4.5 - 策略治理 (Policy Governance)

职责:
    - 冗余策略检测: redundant_policies()
      同 scene × goal_type × kind × action_type 存在多个 active 策略,
      且 action_sequence / strategy / detail 一致 → 判定冗余 (输出候选 + 建议动作)
    - 冗余归档: archive_redundant_policies(dry_run=True) 支持预演
    - 冲突策略检测: conflicting_policies()
      同一 trigger 多个 active version → 最新版本优先, 旧版本建议归档
    - 冲突解决: resolve_conflicts(dry_run=True)
    - 低效策略归档: archive_candidates()
      年龄 > min_archive_age_days 且 hit_rate < min_archive_hit_rate (默认 30 天 / 0.3)
      流程: 检测 → 建议 → 人工确认 → 执行 (apply_archival(trigger, confirm=True))
    - 策略回收站: 两阶段删除 archived → deleted(retained) → purge
      delete_policy / restore_policy / purge_policy / recycle_bin

安全约束:
    - 不是自动删除: 归档必须经检测 → 建议 → 人工确认
    - 治理动作只影响策略表 + 审计日志 (不触碰 Permission / Agent Memory)
    - 纯规则 + 统计 + 阈值 (禁止黑盒优化)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List, Optional

from backend.embodied.experience.policy import (
    POLICY_STATUS_ACTIVE,
    POLICY_STATUS_DEGRADED,
    PolicyTable,
)
from backend.embodied.strategy.audit import PolicyAuditLog

logger = logging.getLogger(__name__)


class GovernanceError(Exception):
    """策略治理操作异常"""


class PolicyGovernance:
    """策略治理 (冗余 / 冲突 / 低效归档 / 回收站)

    用法:
        gov = PolicyGovernance(table, audit,
                               min_archive_age_days=30, min_archive_hit_rate=0.3)
        dup = gov.redundant_policies()
        gov.archive_redundant_policies(dry_run=True)
        conflicts = gov.conflicting_policies()
        gov.resolve_conflicts(dry_run=False)
        cands = gov.archive_candidates()
        gov.apply_archival('recipe_pick', confirm=True)
    """

    def __init__(
        self,
        table: PolicyTable,
        audit: PolicyAuditLog,
        min_archive_age_days: float = 30.0,
        min_archive_hit_rate: float = 0.3,
    ):
        if min_archive_age_days <= 0:
            raise GovernanceError(
                f"min_archive_age_days 必须 > 0, 当前: {min_archive_age_days}"
            )
        if not (0.0 <= min_archive_hit_rate <= 1.0):
            raise GovernanceError(
                f"min_archive_hit_rate 必须在 [0,1], 当前: {min_archive_hit_rate}"
            )
        self._lock = threading.RLock()
        self._table = table
        self._audit = audit
        self._min_archive_age_days = float(min_archive_age_days)
        self._min_archive_hit_rate = float(min_archive_hit_rate)

    # ── 1. 冗余策略检测 ───────────────────────────────────────────
    @staticmethod
    def _freeze(seq) -> tuple:
        """序列化动作序列为可哈希形式 (dict → 排序 key=value 元组)"""
        return tuple(
            tuple(sorted(d.items()))
            if isinstance(d, dict)
            else (("value", d),)
            for d in (seq or [])
        )

    def _content_signature(self, p: Any) -> tuple:
        """策略内容签名 (可解释): action_sequence + strategy + detail"""
        return (
            self._freeze(p.action_sequence),
            p.strategy,
            p.detail,
        )

    def redundant_policies(self) -> Dict[str, Any]:
        """冗余策略检测

        规则 (可解释):
            - 仅 active 策略参与
            - 按 scene × goal_type × kind × action_type 分组
            - 组内 action_sequence / strategy / detail 一致 → 冗余 (保留最早创建的)

        Returns:
            {
                'rule': '同 scene×goal_type×kind×action_type 且内容一致 → 冗余',
                'groups': [{'key', 'scene', 'goal_type', 'kind', 'action_type',
                            'members': [...], 'keeper', 'redundant': [...]}, ...],
                'candidates': [{'trigger', 'keeper', 'reason'}, ...],
                'total': n,
            }
        """
        with self._lock:
            policies = [
                p for p in self._table.all(limit=0)
                if p.effective_status == POLICY_STATUS_ACTIVE
            ]
        groups: Dict[tuple, List[Any]] = {}
        for p in policies:
            key = (
                p.scene, p.goal_type, p.kind, p.action_type,
            )
            groups.setdefault(key, []).append(p)
        out_groups: List[Dict[str, Any]] = []
        candidates: List[Dict[str, Any]] = []
        for (scene, goal_type, kind, action_type), members in groups.items():
            if len(members) < 2:
                continue
            # 内容一致性分组
            by_content: Dict[tuple, List[Any]] = {}
            for m in members:
                by_content.setdefault(self._content_signature(m), []).append(m)
            for sig, same in by_content.items():
                if len(same) < 2:
                    continue
                same_sorted = sorted(same, key=lambda p: p.created_at)
                keeper = same_sorted[0]
                redundant = same_sorted[1:]
                key = f"{scene or '*'}/{goal_type or '*'}/{kind}/{action_type or '*'}"
                out_groups.append({
                    "key": key,
                    "scene": scene,
                    "goal_type": goal_type,
                    "kind": kind,
                    "action_type": action_type,
                    "members": [m.to_dict() for m in same],
                    "keeper": keeper.trigger,
                    "redundant": [r.trigger for r in redundant],
                })
                for r in redundant:
                    candidates.append({
                        "trigger": r.trigger,
                        "keeper": keeper.trigger,
                        "reason": (
                            f"冗余策略: 与 {keeper.trigger} 在 {key} 内容一致 "
                            f"(action_sequence/strategy/detail 相同), 建议归档"
                        ),
                    })
        return {
            "rule": "同 scene×goal_type×kind×action_type 且 action_sequence/strategy/detail 一致 → 冗余",
            "groups": out_groups,
            "candidates": candidates,
            "total": len(candidates),
        }

    def archive_redundant_policies(self, dry_run: bool = True) -> Dict[str, Any]:
        """冗余策略归档 (支持 dry_run 预演)

        Args:
            dry_run: True=只检测不执行 (返回候选 + 建议动作)

        Returns:
            {
                'dry_run', 'rule', 'candidates': [...], 'total',
                'archived': [{'trigger', 'keeper', 'reason'}],  # dry_run=False 时
            }
        """
        det = self.redundant_policies()
        result: Dict[str, Any] = {
            "dry_run": dry_run,
            "rule": det["rule"],
            "candidates": det["candidates"],
            "total": det["total"],
            "archived": [],
        }
        if dry_run:
            return result
        for c in det["candidates"]:
            self._table.archive_policy(c["trigger"])
            self._audit.record(
                trigger=c["trigger"], action="archive_redundant", applied=False,
                reason=c["reason"],
            )
            result["archived"].append(c)
        logger.info(
            f"[Governance] 冗余策略归档: {len(result['archived'])} 条"
        )
        return result

    # ── 2. 冲突策略检测 ───────────────────────────────────────────
    def conflicting_policies(self) -> Dict[str, Any]:
        """冲突策略检测

        规则 (可解释):
            - 同一 trigger 的全部版本 (历史 + 当前) 中存在 >= 2 个 active
            - 最新版本 (version 最大) 优先, 其余 active 旧版本建议归档

        Returns:
            {
                'rule': '同一 trigger 多个 active version → 最新版本优先, 旧版本建议归档',
                'conflicts': [{'trigger', 'active_versions': [...], 'keeper',
                               'outdated': [...]}, ...],
                'total': n,
            }
        """
        with self._lock:
            triggers = {p.trigger for p in self._table.all(limit=0)}
        conflicts: List[Dict[str, Any]] = []
        for trigger in sorted(triggers):
            versions = self._table.all_versions(trigger)
            actives = [
                v for v in versions if v.effective_status == POLICY_STATUS_ACTIVE
            ]
            if len(actives) < 2:
                continue
            keeper = max(actives, key=lambda v: v.version)
            outdated = [v for v in actives if v is not keeper]
            conflicts.append({
                "trigger": trigger,
                "active_versions": [
                    {"version": v.version, "status": v.effective_status,
                     "updated_at": v.updated_at}
                    for v in actives
                ],
                "keeper": keeper.version,
                "outdated": [v.version for v in outdated],
            })
        return {
            "rule": "同一 trigger 多个 active version → 最新版本优先, 旧版本建议归档",
            "conflicts": conflicts,
            "total": len(conflicts),
        }

    def resolve_conflicts(self, dry_run: bool = True) -> Dict[str, Any]:
        """冲突策略解决 (最新版本优先, 旧 active 版本归档)

        Args:
            dry_run: True=只检测不执行

        Returns:
            {
                'dry_run', 'rule', 'conflicts': [...],
                'resolved': [{'trigger', 'archived_versions': [...]}],  # 执行时
            }
        """
        det = self.conflicting_policies()
        result: Dict[str, Any] = {
            "dry_run": dry_run,
            "rule": det["rule"],
            "conflicts": det["conflicts"],
            "total": det["total"],
            "resolved": [],
        }
        if dry_run:
            return result
        for c in det["conflicts"]:
            versions = self._table.all_versions(c["trigger"])
            outdated = [
                v for v in versions
                if v.effective_status == POLICY_STATUS_ACTIVE
                and v.version != c["keeper"]
            ]
            archived_versions = []
            for v in outdated:
                v.set_status("archived")
                v.archived_at = time.time()
                archived_versions.append(v.version)
            self._audit.record(
                trigger=c["trigger"], action="resolve_conflict", applied=False,
                reason=(
                    f"冲突解决: {len(archived_versions)} 个旧 active 版本归档, "
                    f"保留 v{c['keeper']} (最新版本优先)"
                ),
            )
            result["resolved"].append({
                "trigger": c["trigger"],
                "archived_versions": archived_versions,
            })
        logger.info(f"[Governance] 冲突解决: {len(result['resolved'])} 组")
        return result

    # ── 3. 低效策略归档 (检测 → 建议 → 人工确认 → 执行) ───────────
    def archive_candidates(self, now: Optional[float] = None) -> Dict[str, Any]:
        """低效策略归档候选

        规则 (可解释):
            - active / degraded 策略
            - 年龄 > min_archive_age_days 天 (基于 last_activity_at)
            - 且 hit_rate < min_archive_hit_rate
            - 不是自动删除: 仅检测 + 建议, 需人工确认后 apply_archival 执行

        Returns:
            {
                'rule', 'thresholds': {'min_archive_age_days', 'min_archive_hit_rate'},
                'candidates': [{'trigger', 'age_days', 'hit_rate', 'status', 'reason'}, ...],
                'total': n,
            }
        """
        now = now if now is not None else time.time()
        max_age_sec = self._min_archive_age_days * 86400.0
        candidates: List[Dict[str, Any]] = []
        with self._lock:
            policies = [
                p for p in self._table.all(limit=0)
                if p.effective_status in (POLICY_STATUS_ACTIVE, POLICY_STATUS_DEGRADED)
            ]
        for p in policies:
            age_days = max(0.0, (now - p.last_activity_at) / 86400.0)
            if age_days <= self._min_archive_age_days:
                continue
            if p.hit_rate >= self._min_archive_hit_rate:
                continue
            candidates.append({
                "trigger": p.trigger,
                "age_days": round(age_days, 2),
                "hit_rate": p.hit_rate,
                "status": p.effective_status,
                "reason": (
                    f"低效策略: 年龄 {age_days:.1f} 天 > "
                    f"{self._min_archive_age_days} 天, hit_rate {p.hit_rate} < "
                    f"{self._min_archive_hit_rate}, 建议归档 (需人工确认)"
                ),
            })
        candidates.sort(key=lambda c: c["age_days"], reverse=True)
        return {
            "rule": "年龄 > min_archive_age_days 且 hit_rate < min_archive_hit_rate → 建议归档",
            "thresholds": {
                "min_archive_age_days": self._min_archive_age_days,
                "min_archive_hit_rate": self._min_archive_hit_rate,
            },
            "candidates": candidates,
            "total": len(candidates),
        }

    def apply_archival(self, trigger: str, confirm: bool = True) -> Dict[str, Any]:
        """执行低效策略归档 (人工确认后)

        Args:
            trigger: 目标策略 trigger
            confirm: 人工确认标记 (False → 拒绝执行, 保证"检测→建议→人工确认→执行"流程)

        Returns:
            {'applied': bool, 'trigger', 'policy': {...}, 'reason'}

        Raises:
            GovernanceError: 未确认 / 策略不存在 / 非归档候选
        """
        if not confirm:
            raise GovernanceError(
                f"归档需要人工确认: {trigger} (apply_archival(trigger, confirm=True))"
            )
        with self._lock:
            policy = self._table.get(trigger)
        if policy is None:
            raise GovernanceError(f"策略不存在: {trigger}")
        if policy.effective_status == "archived":
            return {
                "applied": True, "trigger": trigger,
                "policy": policy.to_dict(), "reason": "策略已归档, 幂等",
            }
        # 校验候选资格 (防止任意归档绕过治理流程)
        cands = self.archive_candidates()
        is_candidate = any(c["trigger"] == trigger for c in cands["candidates"])
        if not is_candidate:
            raise GovernanceError(
                f"策略不是归档候选 (未满足年龄/hit_rate 阈值): {trigger}"
            )
        self._table.archive_policy(trigger)
        cand_reason = next(
            c["reason"] for c in cands["candidates"] if c["trigger"] == trigger
        )
        self._audit.record(
            trigger=trigger, action="apply_archival", applied=False,
            reason=f"低效策略归档 (人工确认): {cand_reason}",
        )
        logger.info(f"[Governance] 低效策略归档执行: {trigger}")
        return {
            "applied": True, "trigger": trigger,
            "policy": self._table.get(trigger).to_dict(),
            "reason": "低效策略归档 (人工确认后执行)",
        }

    # ── 4. 策略回收站 (两阶段删除) ────────────────────────────────
    def delete_policy(self, trigger: str) -> Dict[str, Any]:
        """软删除 → 回收站 (deleted, retained): 任意状态 → deleted"""
        with self._lock:
            policy = self._table.get(trigger)
        if policy is None:
            raise GovernanceError(f"策略不存在: {trigger}")
        if policy.effective_status == "deleted":
            return {
                "applied": True, "trigger": trigger,
                "policy": policy.to_dict(),
                "reason": "策略已在回收站, 幂等",
            }
        self._table.delete_policy(trigger)
        self._audit.record(
            trigger=trigger, action="archive", applied=False,
            reason="移入回收站 (deleted, retained, 可恢复 / purge 彻底删除)",
        )
        return {
            "applied": True, "trigger": trigger,
            "policy": self._table.get(trigger).to_dict(),
            "reason": "策略已移入回收站",
        }

    def restore_policy(self, trigger: str) -> Dict[str, Any]:
        """回收站恢复: deleted / archived → active"""
        with self._lock:
            policy = self._table.get(trigger)
        if policy is None:
            raise GovernanceError(f"策略不存在: {trigger}")
        self._table.restore_policy(trigger)
        self._audit.record(
            trigger=trigger, action="restore", applied=False,
            reason="回收站恢复 (deleted → active)",
        )
        return {
            "applied": True, "trigger": trigger,
            "policy": self._table.get(trigger).to_dict(),
            "reason": "策略已从回收站恢复",
        }

    def purge_policy(self, trigger: str, confirm: bool = True) -> Dict[str, Any]:
        """彻底删除 (purge): 从当前表 + 版本历史移除, 不可恢复

        Args:
            trigger: 目标策略
            confirm: 人工确认 (purge 不可逆, 必须确认)
        """
        if not confirm:
            raise GovernanceError(
                f"purge 不可逆, 需要人工确认: {trigger} (purge_policy(trigger, confirm=True))"
            )
        with self._lock:
            policy = self._table.get(trigger)
        if policy is None:
            raise GovernanceError(f"策略不存在: {trigger}")
        self._table.purge_policy(trigger)
        self._audit.record(
            trigger=trigger, action="purge", applied=False,
            reason="彻底删除 (purge, 不可恢复)",
        )
        logger.info(f"[Governance] 策略彻底删除: {trigger}")
        return {"applied": True, "trigger": trigger, "reason": "策略已彻底删除 (purge)"}

    def recycle_bin(self, limit: int = 100) -> Dict[str, Any]:
        """回收站内容 (全部 deleted 策略)"""
        entries = self._table.recycle_bin(limit=limit)
        return {"rule": "archived → deleted(retained) → purge", "entries": entries}

    # ── 状态 ──────────────────────────────────────────────────────
    def thresholds(self) -> Dict[str, float]:
        with self._lock:
            return {
                "min_archive_age_days": self._min_archive_age_days,
                "min_archive_hit_rate": self._min_archive_hit_rate,
            }


__all__ = ["PolicyGovernance", "GovernanceError"]
