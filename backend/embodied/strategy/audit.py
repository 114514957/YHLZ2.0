"""
YHLZ Embodied AI V4.6 - 决策审计日志 (Policy Audit Log)

职责:
    - 独立 Audit Log: 记录策略应用 / 策略拒绝 / 排序结果 (可解释"为什么使用该策略")
    - 审计条目格式: {timestamp, goal_id, trigger, kind, action, scene, applied, reason}
    - audit_policy_log(limit, action=None): 输出应用次数 / 拒绝次数 / 原因汇总 (可按动作过滤)
    - V4.5 治理追踪: 新增治理动作白名单
      (consolidate / split / rollback / purge / resolve_conflict /
       archive_redundant / apply_archival)
    - V4.6 跨目标规划追踪: cross_goal (一次规划服务多目标)
    - JSONL 持久化 (embodied_policy_audit.jsonl, 跨进程可加载)

安全约束:
    - 审计数据独立存储: 禁止进入 Agent Memory
    - 只记录不执行: 本模块不产生任何动作
    - 线程安全 (RLock)
    - 可重置 (测试隔离)
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections import Counter, deque
from typing import Any, Deque, Dict, List, Optional

logger = logging.getLogger(__name__)

# 审计动作白名单 (边界防御: 白名单枚举)
AUDIT_ACTIONS: List[str] = [
    "suggest",   # 策略建议
    "apply",     # 策略应用 (模板采纳)
    "reject",    # 策略拒绝 (建议未采纳)
    "rank",      # 排序结果
    "archive",   # 策略归档
    "restore",   # 策略恢复
    "degrade",   # 自动降级
    "recover",   # 自动恢复
    "stale",     # 策略老化
    "version",   # 版本升级
    # ── V4.5 治理追踪 (Meta Strategy Management) ──
    "consolidate",        # 策略同化 (Policy Family)
    "split",              # 策略分裂
    "rollback",           # 策略回滚
    "purge",              # 策略彻底删除 (回收站清理)
    "resolve_conflict",   # 冲突策略解决
    "archive_redundant",  # 冗余策略归档
    "apply_archival",     # 低效策略归档 (人工确认后执行)
    # ── V4.6 跨目标规划追踪 (Cross-Goal Strategic Planning) ──
    "cross_goal",         # 跨目标战略规划
    # ── V4.7 长期任务追踪 (Long Horizon Planning Layer) ──
    "create_long_goal",   # 长期目标创建
    "decompose_goal",     # 目标拆解
    "milestone_complete", # 里程碑完成
    "plan_adjust",        # 计划调整
    "goal_pause",         # 目标暂停
    "goal_resume",        # 目标恢复
    "goal_fail",          # 目标失败
    # ── V5.0 伙伴架构追踪 (Adaptive Companion Architecture) ──
    "companion_handle",   # 主伙伴 Agent 请求处理
]


class PolicyAuditError(Exception):
    """决策审计日志操作异常"""


class PolicyAuditLog:
    """决策审计日志 (独立存储)

    用法:
        audit = PolicyAuditLog(max_entries=500)
        audit.record(goal_id='g-1', trigger='recipe_pick', kind='success',
                     action='apply', scene='room', applied=True,
                     reason='模板应用到规划')
        summary = audit.audit_policy_log(limit=20)
        audit.save_to_file(path) / audit.load_from_file(path)
    """

    def __init__(self, max_entries: int = 500):
        if max_entries <= 0:
            raise PolicyAuditError(f"max_entries 必须 > 0, 当前: {max_entries}")
        self._lock = threading.RLock()
        self._entries: Deque[Dict[str, Any]] = deque(maxlen=max_entries)
        self._max_entries = max_entries

    # ── 记录 ──────────────────────────────────────────────────────
    def record(
        self,
        trigger: str,
        action: str,
        applied: bool = True,
        goal_id: str = "",
        kind: str = "",
        scene: str = "",
        reason: str = "",
        timestamp: Optional[float] = None,
    ) -> Dict[str, Any]:
        """记录一条决策审计

        Args:
            trigger: 策略触发标识 (必填)
            action:  审计动作 (白名单: suggest/apply/reject/rank/archive/restore/...)
            applied: 是否应用 (True=应用, False=拒绝/未应用)
            goal_id: 关联目标 ID
            kind:    策略类型 (failure / success)
            scene:   场景 (room / warehouse / custom)
            reason:  原因 (可解释)
            timestamp: 记录时间 (None=当前)

        Returns:
            已记录的审计条目 dict
        """
        if not trigger or not trigger.strip():
            raise PolicyAuditError("审计 trigger 不能为空")
        if action not in AUDIT_ACTIONS:
            raise PolicyAuditError(
                f"非法审计动作: {action} (可选: {AUDIT_ACTIONS})"
            )
        entry = {
            "timestamp": timestamp if timestamp is not None else time.time(),
            "goal_id": goal_id,
            "trigger": trigger,
            "kind": kind,
            "action": action,
            "scene": scene,
            "applied": bool(applied),
            "reason": reason,
        }
        with self._lock:
            self._entries.append(entry)
        logger.info(
            f"[Audit] {action} trigger={trigger} applied={entry['applied']} "
            f"scene={scene or '-'} reason={reason[:40] if reason else '-'}"
        )
        return entry

    # ── 聚合查询 (V4.4: 应用次数 / 拒绝次数 / 原因; V4.5: 按动作过滤) ──
    def audit_policy_log(
        self,
        limit: int = 50,
        action: Optional[str] = None,
    ) -> Dict[str, Any]:
        """审计汇总: 应用次数 / 拒绝次数 / 动作分布 / 原因汇总 / 近期明细

        Args:
            limit: 近期明细条数 (最新在前)
            action: 按审计动作过滤 (V4.5, 如 'apply' / 'consolidate', None=全部)

        Returns:
            {
                'total': ...,
                'applied_count': ...,
                'rejected_count': ...,
                'by_action': {'apply': ..., 'reject': ..., ...},
                'by_trigger': {'recipe_pick': {'applied': n, 'rejected': n}, ...},
                'top_reasons': [{'reason': ..., 'count': n}, ...],
                'recent': [...],
            }
        """
        with self._lock:
            entries = list(self._entries)
        if action is not None:
            if action not in AUDIT_ACTIONS:
                raise PolicyAuditError(
                    f"非法审计动作过滤: {action} (可选: {AUDIT_ACTIONS})"
                )
            entries = [e for e in entries if e["action"] == action]
        by_action = Counter(e["action"] for e in entries)
        by_trigger: Dict[str, Dict[str, int]] = {}
        for e in entries:
            t = by_trigger.setdefault(e["trigger"], {"applied": 0, "rejected": 0})
            t["applied"] += 1 if e["applied"] else 0
            t["rejected"] += 1 if not e["applied"] else 0
        reason_counter: Counter = Counter()
        for e in entries:
            r = e["reason"].strip()
            if r:
                reason_counter[r] += 1
        top_reasons = [
            {"reason": r, "count": c}
            for r, c in reason_counter.most_common(10)
        ]
        recent = list(reversed(entries))
        if limit > 0:
            recent = recent[:limit]
        return {
            "total": len(entries),
            "applied_count": sum(1 for e in entries if e["applied"]),
            "rejected_count": sum(1 for e in entries if not e["applied"]),
            "by_action": dict(by_action),
            "by_trigger": by_trigger,
            "top_reasons": top_reasons,
            "recent": recent,
        }

    def entries(self, limit: int = 100) -> List[Dict[str, Any]]:
        """原始审计明细 (最新在前)"""
        with self._lock:
            entries = list(reversed(self._entries))
        return entries[:limit] if limit > 0 else entries

    def count(self) -> int:
        with self._lock:
            return len(self._entries)

    # ── 持久化 (JSONL) ────────────────────────────────────────────
    def save_to_file(self, path: str) -> int:
        """保存审计日志到 JSONL 文件 (embodied_policy_audit.jsonl)"""
        with self._lock:
            entries = list(self._entries)
        with open(path, "w", encoding="utf-8") as f:
            for e in entries:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
        logger.info(f"[Audit] 已保存到 {path}, 共 {len(entries)} 条")
        return len(entries)

    def load_from_file(self, path: str) -> int:
        """从 JSONL 文件加载审计日志 (追加, 坏行跳过)"""
        if not os.path.isfile(path):
            logger.warning(f"[Audit] 审计文件不存在, 跳过: {path}")
            return 0
        loaded = 0
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                    self.record(
                        trigger=d.get("trigger", ""),
                        action=d.get("action", ""),
                        applied=bool(d.get("applied", True)),
                        goal_id=d.get("goal_id", ""),
                        kind=d.get("kind", ""),
                        scene=d.get("scene", ""),
                        reason=d.get("reason", ""),
                        timestamp=float(d.get("timestamp", 0.0)),
                    )
                    loaded += 1
                except (json.JSONDecodeError, TypeError, PolicyAuditError) as e:
                    logger.warning(f"[Audit] 跳过坏行: {e}")
        logger.info(f"[Audit] 已从 {path} 加载 {loaded} 条")
        return loaded

    # ── 生命周期 ──────────────────────────────────────────────────
    def clear(self) -> int:
        with self._lock:
            n = len(self._entries)
            self._entries.clear()
        logger.info(f"[Audit] 审计日志已清空, 清理 {n} 条")
        return n

    @property
    def max_entries(self) -> int:
        with self._lock:
            return self._max_entries


__all__ = ["PolicyAuditLog", "PolicyAuditError", "AUDIT_ACTIONS"]
