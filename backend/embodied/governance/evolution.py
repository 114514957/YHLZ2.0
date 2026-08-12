"""
YHLZ Embodied AI V4.5 - 策略体系进化 (Strategy Evolution)

职责:
    - 策略同化: consolidate_similar_policies()
      不同 trigger 但相同 action_sequence → Policy Family (共享父级统计, 子策略保留独立历史)
    - 策略分裂: split_policy()
      按 scene 或 goal_type 拆分 (如 pick_object → warehouse_pick / home_pick)
    - 版本比较: compare_policy_versions()
      输出 version / updated_at / action_sequence / hit_rate / acceptance_rate /
      source_goal_id, 并判断 healthy or regression
    - 策略回滚: rollback_policy()
      只有最新版本 regression 才允许; 旧版本保留历史

安全约束:
    - 只影响策略表 / 审计日志 / 体系快照 (不触碰 Permission / Agent Memory)
    - 纯规则 + 统计 + 阈值 (禁止黑盒优化 / 自主修改策略内容)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import hashlib
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


class EvolutionError(Exception):
    """策略进化操作异常"""


class PolicyEvolution:
    """策略体系进化 (同化 / 分裂 / 版本比较 / 回滚)

    用法:
        evo = PolicyEvolution(table, audit)
        fam = evo.consolidate_similar_policies(dry_run=True)
        split = evo.split_policy('pick_object', by='scene', values=['warehouse', 'home'])
        cmp = evo.compare_policy_versions('pick_object')
        rb = evo.rollback_policy('pick_object', dry_run=True)
    """

    def __init__(
        self,
        table: PolicyTable,
        audit: PolicyAuditLog,
    ):
        self._lock = threading.RLock()
        self._table = table
        self._audit = audit

    # ── 1. 策略同化 (Policy Family) ───────────────────────────────
    @staticmethod
    def _freeze(seq) -> tuple:
        """序列化动作序列为可哈希形式 (dict → 排序 key=value 元组)"""
        return tuple(
            tuple(sorted(d.items()))
            if isinstance(d, dict)
            else (("value", d),)
            for d in (seq or [])
        )

    def _family_signature(self, p: Any) -> Optional[tuple]:
        """同化签名 (可解释):
            - kind=success → action_sequence 一致
            - kind=failure → strategy + action_type 一致
        """
        if p.kind == "success":
            return ("success", self._freeze(p.action_sequence))
        if p.kind == "failure":
            return ("failure", p.strategy, p.action_type)
        return None

    @staticmethod
    def _family_id(signature: tuple) -> str:
        """确定性 family_id: 内容签名哈希 (同签名 → 同 family)"""
        raw = "|".join(
            str(s) for s in signature
        ).encode("utf-8")
        return "fam_" + hashlib.sha256(raw).hexdigest()[:12]

    def consolidate_similar_policies(self, dry_run: bool = True) -> Dict[str, Any]:
        """策略同化: 不同 trigger 相同内容 → Policy Family

        规则 (可解释):
            - 参与: active / degraded 策略 (stale / archived / deleted 不参与)
            - success: action_sequence 一致; failure: strategy + action_type 一致
            - 同签名组 >= 2 个不同 trigger → 形成 Family
            - 共享父级统计 (成员聚合); 子策略保留独立历史

        Args:
            dry_run: True=只检测不写 family_id

        Returns:
            {
                'dry_run', 'rule',
                'families': [{'family_id', 'signature', 'kind',
                              'members': [...], 'parent_stats': {...}}, ...],
                'total': n,
            }
        """
        with self._lock:
            policies = [
                p for p in self._table.all(limit=0)
                if p.effective_status in (POLICY_STATUS_ACTIVE, POLICY_STATUS_DEGRADED)
            ]
        groups: Dict[tuple, List[Any]] = {}
        for p in policies:
            sig = self._family_signature(p)
            if sig is None:
                continue
            groups.setdefault(sig, []).append(p)
        families: List[Dict[str, Any]] = []
        for sig, members in groups.items():
            triggers = {m.trigger for m in members}
            if len(triggers) < 2:
                continue
            fid = self._family_id(sig)
            suggest = sum(m.suggest_count for m in members)
            accepted = sum(m.accepted_count for m in members)
            success = sum(m.success_count for m in members)
            family = {
                "family_id": fid,
                "signature": {
                    "kind": sig[0],
                    "content": (
                        sig[1] if sig[0] == "success" else {
                            "strategy": sig[1], "action_type": sig[2],
                        }
                    ),
                },
                "kind": sig[0],
                "members": [m.to_dict() for m in members],
                "member_count": len(members),
                "parent_stats": {
                    "suggest_count": suggest,
                    "accepted_count": accepted,
                    "success_count": success,
                    "hit_rate": round(success / accepted, 4) if accepted else 0.0,
                    "acceptance_rate": round(accepted / suggest, 4) if suggest else 0.0,
                },
            }
            families.append(family)
            if not dry_run:
                for m in members:
                    self._table.set_family(m.trigger, fid)
                    self._audit.record(
                        trigger=m.trigger, action="consolidate", applied=False,
                        reason=f"策略同化: 加入 Policy Family {fid} (共享父级统计)",
                    )
        if not dry_run and families:
            logger.info(
                f"[Evolution] 策略同化: 形成 {len(families)} 个 Policy Family"
            )
        return {
            "dry_run": dry_run,
            "rule": "不同 trigger 相同 action_sequence (success) / strategy+action_type (failure) → Policy Family",
            "families": families,
            "total": len(families),
        }

    # ── 2. 策略分裂 ───────────────────────────────────────────────
    def split_policy(
        self,
        trigger: str,
        by: str = "scene",
        values: Optional[List[str]] = None,
        dry_run: bool = True,
    ) -> Dict[str, Any]:
        """策略分裂: 按 scene / goal_type 拆分

        规则 (可解释):
            - by: 'scene' | 'goal_type'
            - values: 目标维度值列表 (如 ['warehouse', 'home'])
            - 每个值生成新策略: trigger = f"{trigger}_{value}", 维度指定, 内容继承
            - 原策略归档 (保留在历史, 可追溯), 新策略 active 独立统计

        Args:
            trigger: 原策略 trigger
            by: 拆分维度 (scene / goal_type)
            values: 维度值列表 (非空, 不重复)
            dry_run: True=只预演 (返回将创建/归档的清单)

        Returns:
            {
                'dry_run', 'by', 'original': {...} | None,
                'would_archive': bool,
                'created': [{'trigger', 'scene', 'goal_type', ...}, ...],
            }

        Raises:
            EvolutionError: 参数不合法 / 策略不存在 / 目标 trigger 冲突
        """
        if by not in ("scene", "goal_type"):
            raise EvolutionError(f"by 必须为 scene / goal_type, 当前: {by}")
        values = list(values or [])
        if not values:
            raise EvolutionError("values 不能为空 (至少一个拆分目标值)")
        if len(set(values)) != len(values):
            raise EvolutionError(f"values 不能重复: {values}")
        with self._lock:
            original = self._table.get(trigger)
        if original is None:
            raise EvolutionError(f"策略不存在: {trigger}")
        created: List[Dict[str, Any]] = []
        for v in values:
            new_trigger = f"{trigger}_{v}"
            with self._lock:
                if self._table.get(new_trigger) is not None:
                    raise EvolutionError(
                        f"目标 trigger 已存在: {new_trigger} (无法分裂)"
                    )
            created.append({
                "trigger": new_trigger,
                "kind": original.kind,
                "strategy": original.strategy,
                "detail": original.detail,
                "action_type": original.action_type,
                "action_sequence": original.action_sequence,
                by: v,
                "source_goal_ids": list(original.source_goal_ids),
            })
        result: Dict[str, Any] = {
            "dry_run": dry_run,
            "by": by,
            "original": original.to_dict(),
            "would_archive": True,
            "created": created,
            "total": len(created),
        }
        if dry_run:
            return result
        # 执行: 原策略归档 + 创建新策略
        self._table.archive_policy(trigger)
        self._audit.record(
            trigger=trigger, action="split", applied=False,
            reason=f"策略分裂: 按 {by} 拆分为 {[c['trigger'] for c in created]}",
        )
        for c in created:
            kwargs = {by: c[by]}
            new_policy = self._table.upsert(
                trigger=c["trigger"],
                strategy=c["strategy"],
                kind=c["kind"],
                detail=c["detail"],
                action_type=c["action_type"],
                action_sequence=c["action_sequence"],
                source_goal_id=c["source_goal_ids"][0] if c["source_goal_ids"] else "",
                **kwargs,
            )
            for gid in c["source_goal_ids"][1:]:
                if gid not in new_policy.source_goal_ids:
                    new_policy.source_goal_ids.append(gid)
        logger.info(
            f"[Evolution] 策略分裂: {trigger} 按 {by} → "
            f"{[c['trigger'] for c in created]}"
        )
        return result

    # ── 3. 版本比较 ───────────────────────────────────────────────
    def compare_policy_versions(self, trigger: str) -> Dict[str, Any]:
        """版本比较: 全部版本逐版本对比, 判断 healthy / regression

        规则 (可解释):
            - 按版本顺序 (最旧 → 最新) 逐版本与上一版本比较
            - regression: 当前 hit_rate < 上一版本 hit_rate
            - 无历史版本 → 单版本 (healthy 基准)

        Returns:
            {
                'trigger', 'rule',
                'versions': [
                    {'version', 'updated_at', 'action_sequence',
                     'hit_rate', 'acceptance_rate', 'source_goal_id',
                     'verdict': 'healthy'|'regression'|'baseline'}, ...
                ],
                'latest_verdict': 'healthy'|'regression',
                'latest_version': n,
            }
        """
        versions = self._table.all_versions(trigger)
        entries: List[Dict[str, Any]] = []
        for i, v in enumerate(versions):
            prev = versions[i - 1] if i > 0 else None
            verdict = "baseline"
            if prev is not None:
                verdict = "regression" if v.hit_rate < prev.hit_rate else "healthy"
            entries.append({
                "version": v.version,
                "updated_at": v.updated_at,
                "action_sequence": v.action_sequence,
                "hit_rate": v.hit_rate,
                "acceptance_rate": v.acceptance_rate,
                "source_goal_id": (
                    v.source_goal_ids[-1] if v.source_goal_ids else ""
                ),
                "verdict": verdict,
            })
        latest_verdict = entries[-1]["verdict"] if entries else "baseline"
        return {
            "trigger": trigger,
            "rule": "当前版本 hit_rate < 上一版本 hit_rate → regression, 否则 healthy",
            "versions": entries,
            "latest_verdict": latest_verdict,
            "latest_version": entries[-1]["version"] if entries else 0,
        }

    # ── 4. 策略回滚 ───────────────────────────────────────────────
    def rollback_policy(
        self,
        trigger: str,
        dry_run: bool = True,
        now: Optional[float] = None,
    ) -> Dict[str, Any]:
        """策略回滚: 仅最新版本 regression 才允许

        规则 (可解释):
            - 必须有历史版本 (>= 2 版本)
            - 最新版本 verdict == regression 才允许回滚
            - 回滚后: 当前版本入历史 (archived), 最近历史版本提升为当前 active
            - 旧版本保留历史 (可追溯)

        Args:
            trigger: 策略 trigger
            dry_run: True=只预演 (返回是否允许 + 将执行的动作)

        Returns:
            {
                'dry_run', 'trigger', 'allowed', 'reason',
                'compare': {...},              # 版本比较结果
                'would_rollback_to': n | None, # 回滚目标版本
            }
        """
        compare = self.compare_policy_versions(trigger)
        versions = self._table.all_versions(trigger)
        if len(versions) < 2:
            return {
                "dry_run": dry_run, "trigger": trigger, "allowed": False,
                "reason": "无历史版本, 无法回滚", "compare": compare,
                "would_rollback_to": None,
            }
        if compare["latest_verdict"] != "regression":
            return {
                "dry_run": dry_run, "trigger": trigger, "allowed": False,
                "reason": (
                    f"最新版本 v{compare['latest_version']} 未 regression "
                    f"(healthy), 禁止回滚"
                ),
                "compare": compare,
                "would_rollback_to": None,
            }
        prev = versions[-2]
        result: Dict[str, Any] = {
            "dry_run": dry_run, "trigger": trigger, "allowed": True,
            "reason": (
                f"最新版本 v{compare['latest_version']} regression "
                f"(hit_rate {versions[-1].hit_rate} < "
                f"{prev.hit_rate}), 回滚到 v{prev.version}"
            ),
            "compare": compare,
            "would_rollback_to": prev.version,
        }
        if dry_run:
            return result
        rolled = self._table.rollback_policy(trigger)
        self._audit.record(
            trigger=trigger, action="rollback", applied=False,
            reason=result["reason"],
        )
        result["rolled_to"] = rolled.version if rolled else None
        logger.info(
            f"[Evolution] 策略回滚: {trigger} → v{result['rolled_to']}"
        )
        return result

    # ── 状态 ──────────────────────────────────────────────────────
    def families(self) -> Dict[str, Any]:
        """当前 Policy Family 汇总 (共享父级统计)"""
        return self._table.families()


__all__ = ["PolicyEvolution", "EvolutionError"]
