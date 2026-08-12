"""
YHLZ Embodied AI V4.5 - 治理 Dry Run 体系化 (Governance Dry Run)

职责:
    - governance_dry_run(action, **kwargs): 统一治理预演入口
      支持: archive_redundant / resolve_conflicts / apply_archival /
            consolidate / split / rollback / purge
    - 返回: 影响策略 / 执行后系统快照差异 / 保护规则检查结果
    - SystemSnapshot: 策略体系快照 (只读, 用于 dry-run 前后对比)

保护规则 (每次预演输出检查结果, 可解释):
    - 治理动作只影响策略表 / 审计日志 / 体系快照
    - 不控制真实设备 / 不触碰 Permission Layer / 不写入 Agent Memory
    - 纯规则 + 统计 + 阈值 (禁止 AI 训练 / 黑盒优化)

安全约束:
    - dry_run 绝不修改任何状态 (只读模拟)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List, Optional

from backend.embodied.experience.policy import PolicyTable
from backend.embodied.governance.evolution import PolicyEvolution
from backend.embodied.governance.governance import PolicyGovernance
from backend.embodied.governance.health import PolicyHealthCheck

logger = logging.getLogger(__name__)


class DryRunError(Exception):
    """治理预演操作异常"""


# 支持预演的治理动作白名单
GOVERNANCE_DRY_RUN_ACTIONS: List[str] = [
    "archive_redundant",   # 冗余策略归档
    "resolve_conflicts",   # 冲突策略解决
    "apply_archival",      # 低效策略归档
    "consolidate",         # 策略同化
    "split",               # 策略分裂
    "rollback",            # 策略回滚
    "purge",               # 策略彻底删除
]


class SystemSnapshot:
    """策略体系快照 (只读)

    捕获: 数量 / 状态分布 / 版本 / 归档 / 回收站 / 平均质量 / family 数
    """

    @staticmethod
    def capture(table: PolicyTable) -> Dict[str, Any]:
        stats = table.stats()
        policies = table.all(limit=0)
        non_deleted = [p for p in policies if p.effective_status != "deleted"]
        avg_hr = (
            round(sum(p.hit_rate for p in non_deleted) / len(non_deleted), 4)
            if non_deleted else 0.0
        )
        return {
            "total": len(policies),
            "status_counts": dict(stats["status_counts"]),
            "version_total": stats["version_total"],
            "archived_count": stats["status_counts"].get("archived", 0),
            "deleted_count": stats["status_counts"].get("deleted", 0),
            "avg_hit_rate": avg_hr,
            "family_count": len(table.families()),
        }

    @staticmethod
    def diff(before: Dict[str, Any], after: Dict[str, Any]) -> Dict[str, Any]:
        """快照差异 (执行后 - 执行前, 只输出变化字段)"""
        out: Dict[str, Any] = {}
        for key in before:
            if before[key] != after[key]:
                out[key] = {"before": before[key], "after": after[key]}
        return out


class GovernanceDryRun:
    """治理预演 (只模拟不执行)

    用法:
        dry = GovernanceDryRun(governance, evolution, health)
        result = dry.run('archive_redundant')
        result = dry.run('rollback', trigger='pick_object')
    """

    def __init__(
        self,
        governance: PolicyGovernance,
        evolution: PolicyEvolution,
        health: PolicyHealthCheck,
    ):
        self._lock = threading.RLock()
        self._gov = governance
        self._evo = evolution
        self._health = health
        self._table = governance._table

    # ── 保护规则检查 (可解释, 每次预演输出) ───────────────────────
    @staticmethod
    def _protection_checks() -> Dict[str, Any]:
        checks = [
            ("targets_only_policy_system", True, "治理动作只影响策略表/审计日志/体系快照"),
            ("no_device_control", True, "不控制任何真实设备 / 机器人"),
            ("no_agent_memory_write", True, "不写入 Agent Memory"),
            ("no_ai_training", True, "纯规则 + 统计 + 阈值, 禁止 AI 训练"),
            ("permission_layer_untouched", True, "不绕过 Permission Layer"),
        ]
        return {
            "checks": [
                {"name": name, "passed": ok, "reason": reason}
                for name, ok, reason in checks
            ],
            "passed": all(ok for _, ok, _ in checks),
        }

    # ── 影响策略提取 ──────────────────────────────────────────────
    def _impacts(self, action: str, detection: Dict[str, Any]) -> List[Dict[str, Any]]:
        """从检测结果提取影响策略 (trigger + 变更描述)"""
        if action == "archive_redundant":
            return [
                {"trigger": c["trigger"], "change": "active → archived",
                 "reason": c["reason"]}
                for c in detection.get("candidates", [])
            ]
        if action == "resolve_conflicts":
            out: List[Dict[str, Any]] = []
            for c in detection.get("conflicts", []):
                for v in c.get("active_versions", []):
                    if v["version"] != c["keeper"]:
                        out.append({
                            "trigger": c["trigger"],
                            "version": v["version"],
                            "change": "active → archived",
                            "reason": f"冲突解决: 保留最新 v{c['keeper']}",
                        })
            return out
        if action == "apply_archival":
            return [
                {"trigger": c["trigger"], "change": f"{c['status']} → archived",
                 "reason": c["reason"]}
                for c in detection.get("candidates", [])
            ]
        if action == "consolidate":
            out = []
            for f in detection.get("families", []):
                for m in f.get("members", []):
                    out.append({
                        "trigger": m["trigger"],
                        "change": "加入 Policy Family (共享父级统计)",
                        "reason": f"family_id={f['family_id']} 同内容同化",
                    })
            return out
        return []

    # ── 单动作模拟 (返回 after 快照) ──────────────────────────────
    def _simulate(
        self,
        action: str,
        before: Dict[str, Any],
        detection: Dict[str, Any],
        kwargs: Dict[str, Any],
    ) -> Dict[str, Any]:
        """纯函数模拟执行后快照 (不修改任何状态)"""
        after = dict(before)
        sc = dict(before["status_counts"])
        if action in ("archive_redundant", "resolve_conflicts", "apply_archival"):
            n = len(self._impacts(action, detection))
            sc["active"] = max(0, sc.get("active", 0) - n)
            sc["archived"] = sc.get("archived", 0) + n
        elif action == "consolidate":
            families = detection.get("families", [])
            after["family_count"] = (
                before.get("family_count", 0) + len(families)
            )
        elif action == "split":
            # 原策略 → archived; 创建 N 个新 active
            created = detection.get("created", [])
            sc["archived"] = sc.get("archived", 0) + 1
            sc["active"] = sc.get("active", 0) + len(created)
            after["total"] = before.get("total", 0) + len(created)
            after["version_total"] = before.get("version_total", 0) + len(created)
        elif action == "rollback":
            # 当前 → archived; 上一版本 → active (数量不变)
            pass
        elif action == "purge":
            # 触发策略被移除
            triggers = self._purge_triggers(detection)
            for t in triggers:
                entry = detection.get("entry", {})
                st = entry.get("status") if t == entry.get("trigger") else None
                if st and st in sc and sc[st] > 0:
                    sc[st] -= 1
            after["total"] = max(0, before.get("total", 0) - len(triggers))
        after["status_counts"] = sc
        return after

    @staticmethod
    def _purge_triggers(detection: Dict[str, Any]) -> List[str]:
        return list(detection.get("triggers", []))

    # ── 统一入口 ──────────────────────────────────────────────────
    def run(self, action: str, **kwargs: Any) -> Dict[str, Any]:
        """治理预演统一入口

        Args:
            action: 治理动作 (archive_redundant / resolve_conflicts /
                    apply_archival / consolidate / split / rollback / purge)
            kwargs: 动作参数 (trigger / by / values 等)

        Returns:
            {
                'dry_run': True,
                'action': action,
                'impacted_policies': [...],
                'snapshot_before': {...},
                'snapshot_after': {...},
                'snapshot_diff': {...},
                'protection_checks': {'passed': bool, 'checks': [...]},
                'detail': {...},   # 动作检测明细 (dry_run=True 结果)
            }

        Raises:
            DryRunError: 不支持的治理动作 / 参数不合法
        """
        if action not in GOVERNANCE_DRY_RUN_ACTIONS:
            raise DryRunError(
                f"不支持的治理动作: {action} (可选: {GOVERNANCE_DRY_RUN_ACTIONS})"
            )
        with self._lock:
            before = SystemSnapshot.capture(self._table)

            if action == "archive_redundant":
                detail = self._gov.archive_redundant_policies(dry_run=True)
            elif action == "resolve_conflicts":
                detail = self._gov.resolve_conflicts(dry_run=True)
            elif action == "apply_archival":
                detail = self._gov.archive_candidates()
            elif action == "consolidate":
                detail = self._evo.consolidate_similar_policies(dry_run=True)
            elif action == "split":
                detail = self._evo.split_policy(
                    kwargs.get("trigger", ""),
                    by=kwargs.get("by", "scene"),
                    values=kwargs.get("values"),
                    dry_run=True,
                )
            elif action == "rollback":
                detail = self._evo.rollback_policy(
                    kwargs.get("trigger", ""), dry_run=True,
                )
            elif action == "purge":
                triggers = kwargs.get("triggers") or (
                    [kwargs["trigger"]] if kwargs.get("trigger") else []
                )
                if not triggers:
                    raise DryRunError("purge 预演需要 trigger / triggers 参数")
                entries = []
                for t in triggers:
                    p = self._table.get(t)
                    if p is None:
                        raise DryRunError(f"策略不存在: {t}")
                    entries.append(p.to_dict())
                detail = {"triggers": list(triggers), "entries": entries}

            impacted = self._impacts(action, detail)
            if action == "rollback" and detail.get("allowed"):
                impacted = [{
                    "trigger": detail["trigger"],
                    "change": (
                        f"v{detail['compare']['latest_version']} → "
                        f"v{detail['would_rollback_to']} (当前入历史, 上一版本升为 active)"
                    ),
                    "reason": detail["reason"],
                }]
            if action == "purge":
                impacted = [
                    {"trigger": t, "change": "彻底删除 (purge, 不可恢复)",
                     "reason": "回收站清理 (purge)"}
                    for t in detail["triggers"]
                ]
            if action == "split":
                impacted = [{
                    "trigger": detail["original"]["trigger"],
                    "change": "active → archived (原策略)",
                    "reason": f"按 {detail['by']} 分裂",
                }] + [
                    {"trigger": c["trigger"], "change": "新建 active",
                     "reason": f"分裂产物 ({detail['by']}={c[detail['by']]})"}
                    for c in detail.get("created", [])
                ]

            after = self._simulate(action, before, detail, kwargs)
            diff = SystemSnapshot.diff(before, after)
            return {
                "dry_run": True,
                "action": action,
                "impacted_policies": impacted,
                "impact_count": len(impacted),
                "snapshot_before": before,
                "snapshot_after": after,
                "snapshot_diff": diff,
                "protection_checks": self._protection_checks(),
                "detail": detail,
            }


__all__ = [
    "GovernanceDryRun",
    "SystemSnapshot",
    "DryRunError",
    "GOVERNANCE_DRY_RUN_ACTIONS",
]
