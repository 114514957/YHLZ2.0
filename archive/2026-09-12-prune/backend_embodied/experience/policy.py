"""
YHLZ Embodied AI V4.5 - 经验策略表 (Experience Policy Table, Adaptive Layer)

职责:
    - 存储可解释策略: 失败策略 (trigger + strategy) + 成功配方 (recipe)
    - V4.4 策略调度维度: scene (场景) + goal_type (目标类型) → 候选 → 质量排序
    - V4.4 策略生命周期: active / degraded / stale / archived (不是删除, 可恢复)
    - V4.4 策略版本化: 同一 trigger 多版本 (v1 / v2 / v3), 支持 policy_history
    - V4.4 策略恢复: 连续 N 次 建议+采纳+成功 → 自动从 degraded 恢复 active
    - V4.4 策略老化: 超过 max_age_days 无使用 → stale, 不参与建议
    - V4.5 策略回收站: 两阶段删除 archived → deleted(retained) → purge (彻底清除)
    - V4.5 策略回滚: rollback_policy (最新版本 regression 才允许, 旧版本保留历史)
    - V4.5 Policy Family: 同化策略共享 family_id (父级统计, 子策略保留独立历史)
    - 策略质量指标: suggest_count / accepted_count / success_count / hit_rate
    - JSONL 持久化 (embodied_policy.jsonl, 跨进程可加载, 旧 V4.3 数据兼容)

设计原则:
    - 规则表 + 模板匹配: 策略全部可解释, 禁止黑盒学习 (规则 + 统计 + 阈值)
    - 数据独立存储: 绝不写入 Agent Memory
    - 治理动作只影响策略表 / 审计日志 / 体系快照 (不触碰 Permission / Memory)
    - 线程安全 (RLock)
    - 可重置 (测试隔离)
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# V4.4 策略生命周期状态 (规则表)
POLICY_STATUS_ACTIVE = "active"
POLICY_STATUS_DEGRADED = "degraded"
POLICY_STATUS_STALE = "stale"
POLICY_STATUS_ARCHIVED = "archived"
# V4.5 回收站状态: 已删除 (保留待清理, 可恢复)
POLICY_STATUS_DELETED = "deleted"
POLICY_STATUSES: List[str] = [
    POLICY_STATUS_ACTIVE,
    POLICY_STATUS_DEGRADED,
    POLICY_STATUS_STALE,
    POLICY_STATUS_ARCHIVED,
    POLICY_STATUS_DELETED,
]


class PolicyTableError(Exception):
    """经验策略表操作异常"""


@dataclass
class ExperiencePolicy:
    """可解释经验策略 (失败策略 / 成功配方, V4.4 生命周期版本)

    Attributes:
        policy_id:       策略唯一 ID
        trigger:         触发标识 (如 'pick_failure_location' / 'recipe_pick')
        strategy:        建议策略 (如 'scan_before_pick')
        kind:            类型: 'failure' (失败策略) / 'success' (成功配方)
        detail:          策略说明 (可解释, 供 Agent 上下文)
        action_type:     关联动作类型 (失败策略)
        cause:           关联失败因果 (失败策略)
        action_sequence: 成功动作序列 (成功配方, List[Dict]: action_type / parameters)
        preconditions:   先决条件 (成功配方)
        required_action: 采纳该策略所需执行的核心动作 (失败策略)
        scene:           适用场景 (V4.4, 空=全场景)
        goal_type:       适用目标类型 (V4.4, 空=全部: pick/move/place/inspect/scan)
        family_id:       Policy Family 标识 (V4.5, 同化策略共享, 空=独立)
        version:         策略版本 (V4.4, 同 trigger 多版本)
        status:          生命周期状态 (V4.4: active/degraded/stale/archived; V4.5: +deleted)
        suggest_count:   被建议次数
        accepted_count:  被采纳次数 (建议后规划实际采用)
        success_count:   采纳后最终成功次数
        degraded:        是否已降级 (V4.3 兼容字段, 与 status 同步)
        recovery_streak: 连续"建议+采纳+成功"次数 (V4.4 恢复机制)
        last_suggested_at: 最近建议时间 (V4.4 老化判定)
        last_accepted_at:  最近采纳时间 (V4.4 老化判定)
        archived_at:     归档时间 (V4.4)
        deleted_at:      软删除时间 (V4.5, 回收站, 0=未删除)
        created_at:      创建时间
        updated_at:      更新时间
        source_goal_ids: 来源目标 ID 列表 (可追溯)
    """
    policy_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    trigger: str = ""
    strategy: str = ""
    kind: str = "failure"
    detail: str = ""
    action_type: str = ""
    cause: str = ""
    action_sequence: List[Dict[str, Any]] = field(default_factory=list)
    preconditions: List[str] = field(default_factory=list)
    required_action: str = ""
    scene: str = ""
    goal_type: str = ""
    family_id: str = ""
    version: int = 1
    status: str = POLICY_STATUS_ACTIVE
    suggest_count: int = 0
    accepted_count: int = 0
    success_count: int = 0
    degraded: bool = False
    recovery_streak: int = 0
    last_suggested_at: float = 0.0
    last_accepted_at: float = 0.0
    archived_at: float = 0.0
    deleted_at: float = 0.0
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    source_goal_ids: List[str] = field(default_factory=list)

    @property
    def hit_rate(self) -> float:
        """命中率: 采纳后成功比例 (0.0 ~ 1.0)"""
        if self.accepted_count <= 0:
            return 0.0
        return round(self.success_count / self.accepted_count, 4)

    @property
    def acceptance_rate(self) -> float:
        """采纳率: 被采纳 / 被建议"""
        if self.suggest_count <= 0:
            return 0.0
        return round(self.accepted_count / self.suggest_count, 4)

    @property
    def effective_status(self) -> str:
        """有效状态: status 合法则用 status, 否则 active"""
        return self.status if self.status in POLICY_STATUSES else POLICY_STATUS_ACTIVE

    @property
    def last_activity_at(self) -> float:
        """最近活动时间 (老化判定): 建议/采纳/更新/创建 的最大值"""
        return max(
            self.last_suggested_at, self.last_accepted_at,
            self.updated_at, self.created_at,
        )

    def set_status(self, status: str) -> None:
        """设置生命周期状态 (与 V4.3 degraded 字段同步)"""
        if status not in POLICY_STATUSES:
            raise PolicyTableError(
                f"非法策略状态: {status} (可选: {POLICY_STATUSES})"
            )
        self.status = status
        self.degraded = status == POLICY_STATUS_DEGRADED
        self.updated_at = time.time()
        if status == POLICY_STATUS_DELETED:
            self.deleted_at = time.time()
        elif self.deleted_at:
            self.deleted_at = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "policy_id": self.policy_id,
            "trigger": self.trigger,
            "strategy": self.strategy,
            "kind": self.kind,
            "detail": self.detail,
            "action_type": self.action_type,
            "cause": self.cause,
            "action_sequence": self.action_sequence,
            "preconditions": self.preconditions,
            "required_action": self.required_action,
            "scene": self.scene,
            "goal_type": self.goal_type,
            "family_id": self.family_id,
            "version": self.version,
            "status": self.effective_status,
            "suggest_count": self.suggest_count,
            "accepted_count": self.accepted_count,
            "success_count": self.success_count,
            "hit_rate": self.hit_rate,
            "acceptance_rate": self.acceptance_rate,
            "degraded": self.degraded,
            "recovery_streak": self.recovery_streak,
            "last_suggested_at": self.last_suggested_at,
            "last_accepted_at": self.last_accepted_at,
            "archived_at": self.archived_at,
            "deleted_at": self.deleted_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "source_goal_ids": self.source_goal_ids,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ExperiencePolicy":
        status = d.get("status", "")
        if not status or status not in POLICY_STATUSES:
            status = (
                POLICY_STATUS_DEGRADED if d.get("degraded", False)
                else POLICY_STATUS_ACTIVE
            )
        return cls(
            policy_id=d.get("policy_id", uuid.uuid4().hex),
            trigger=d.get("trigger", ""),
            strategy=d.get("strategy", ""),
            kind=d.get("kind", "failure"),
            detail=d.get("detail", ""),
            action_type=d.get("action_type", ""),
            cause=d.get("cause", ""),
            action_sequence=list(d.get("action_sequence", []) or []),
            preconditions=list(d.get("preconditions", []) or []),
            required_action=d.get("required_action", ""),
            scene=d.get("scene", ""),
            goal_type=d.get("goal_type", ""),
            family_id=d.get("family_id", ""),
            version=int(d.get("version", 1)),
            status=status,
            suggest_count=int(d.get("suggest_count", 0)),
            accepted_count=int(d.get("accepted_count", 0)),
            success_count=int(d.get("success_count", 0)),
            degraded=bool(d.get("degraded", status == POLICY_STATUS_DEGRADED)),
            recovery_streak=int(d.get("recovery_streak", 0)),
            last_suggested_at=float(d.get("last_suggested_at", 0.0)),
            last_accepted_at=float(d.get("last_accepted_at", 0.0)),
            archived_at=float(d.get("archived_at", 0.0)),
            deleted_at=float(d.get("deleted_at", 0.0)),
            created_at=float(d.get("created_at", time.time())),
            updated_at=float(d.get("updated_at", time.time())),
            source_goal_ids=list(d.get("source_goal_ids", []) or []),
        )

    @classmethod
    def create(
        cls,
        trigger: str,
        strategy: str,
        kind: str = "failure",
        detail: str = "",
        action_type: str = "",
        cause: str = "",
        action_sequence: Optional[List[Dict[str, Any]]] = None,
        preconditions: Optional[List[str]] = None,
        required_action: str = "",
        scene: str = "",
        goal_type: str = "",
        family_id: str = "",
        version: int = 1,
        source_goal_ids: Optional[List[str]] = None,
    ) -> "ExperiencePolicy":
        return cls(
            trigger=trigger, strategy=strategy, kind=kind, detail=detail,
            action_type=action_type, cause=cause,
            action_sequence=action_sequence or [],
            preconditions=preconditions or [],
            required_action=required_action,
            scene=scene, goal_type=goal_type, family_id=family_id,
            version=version,
            source_goal_ids=source_goal_ids or [],
        )


class PolicyTable:
    """经验策略表 (按 trigger 索引, 多版本, 生命周期管理)

    用法:
        table = PolicyTable()
        table.upsert(trigger='pick_failure_location', strategy='scan_before_pick',
                     kind='failure', scene='room', goal_type='pick')
        policy = table.get('pick_failure_location')
        table.record_suggested(trigger)
        table.record_accepted(trigger, success=True)
        table.archive_policy(trigger) / table.restore_policy(trigger)
        table.evaluate_aging(max_age_days) / table.evaluate_recovery(threshold)
        table.candidates(scene='room', goal_type='pick', kind='failure')
        table.delete_policy(trigger) / table.recycle_bin() / table.purge_policy(trigger)
        table.rollback_policy(trigger) / table.set_family(trigger, family_id)
        table.save_to_file(path) / table.load_from_file(path)
    """

    def __init__(self, max_policies: int = 100):
        if max_policies <= 0:
            raise PolicyTableError(f"max_policies 必须 > 0, 当前: {max_policies}")
        self._lock = threading.RLock()
        self._policies: Dict[str, ExperiencePolicy] = {}
        self._versions: Dict[str, List[ExperiencePolicy]] = {}
        self._max_policies = max_policies

    # ── 增改 (V4.4: 版本化) ───────────────────────────────────────
    def upsert(
        self,
        trigger: str,
        strategy: str,
        kind: str = "failure",
        detail: str = "",
        action_type: str = "",
        cause: str = "",
        action_sequence: Optional[List[Dict[str, Any]]] = None,
        preconditions: Optional[List[str]] = None,
        required_action: str = "",
        source_goal_id: str = "",
        scene: str = "",
        goal_type: str = "",
    ) -> ExperiencePolicy:
        """新增或合并策略 (V4.3 合并语义保持, 兼容既有调用)

        合并规则:
            - 保留累计统计 (suggest / accepted / success)
            - 更新策略内容 (strategy / detail / action_sequence / preconditions)
            - 追加来源目标 ID (去重)
        版本化: 内容替换走 upsert_version (V4.4), 本方法不自动升版本
        """
        if not trigger or not trigger.strip():
            raise PolicyTableError("trigger 不能为空")
        with self._lock:
            existing = self._policies.get(trigger)
            if existing is None:
                if len(self._policies) >= self._max_policies:
                    raise PolicyTableError(
                        f"策略表已满 ({self._max_policies}), 无法新增: {trigger}"
                    )
                policy = ExperiencePolicy.create(
                    trigger=trigger, strategy=strategy, kind=kind, detail=detail,
                    action_type=action_type, cause=cause,
                    action_sequence=action_sequence,
                    preconditions=preconditions,
                    required_action=required_action,
                    scene=scene, goal_type=goal_type,
                    version=1,
                    source_goal_ids=[source_goal_id] if source_goal_id else [],
                )
                self._policies[trigger] = policy
                logger.info(f"[Policy] 新增策略 trigger={trigger} strategy={strategy} "
                            f"v{policy.version}")
                return policy
            # 合并更新 (同版本内容更新)
            existing.strategy = strategy
            existing.kind = kind
            existing.detail = detail
            existing.action_type = action_type or existing.action_type
            existing.cause = cause or existing.cause
            if action_sequence:
                existing.action_sequence = action_sequence
            if preconditions is not None:
                existing.preconditions = preconditions
            existing.required_action = required_action or existing.required_action
            if scene:
                existing.scene = scene
            if goal_type:
                existing.goal_type = goal_type
            if source_goal_id and source_goal_id not in existing.source_goal_ids:
                existing.source_goal_ids.append(source_goal_id)
            existing.updated_at = time.time()
            logger.info(f"[Policy] 合并策略 trigger={trigger} v{existing.version}")
            return existing

    def upsert_version(
        self,
        trigger: str,
        strategy: str,
        kind: str = "failure",
        detail: str = "",
        action_type: str = "",
        cause: str = "",
        action_sequence: Optional[List[Dict[str, Any]]] = None,
        preconditions: Optional[List[str]] = None,
        required_action: str = "",
        source_goal_id: str = "",
        scene: str = "",
        goal_type: str = "",
    ) -> ExperiencePolicy:
        """策略版本升级 (V4.4): 同 trigger 新内容 → 生成新版本

        规则 (可解释):
            - 当前版本保留统计并进入版本历史 (policy_history 可查)
            - 新版本 version+1, 统计从 0 开始 (策略内容不同, 质量独立评估)
            - 新版本继承来源目标 ID (可追溯完整演进)

        Returns:
            新版本策略 (原版本入历史, 状态 archived)
        """
        if not trigger or not trigger.strip():
            raise PolicyTableError("trigger 不能为空")
        with self._lock:
            existing = self._policies.get(trigger)
            if existing is None:
                if len(self._policies) >= self._max_policies:
                    raise PolicyTableError(
                        f"策略表已满 ({self._max_policies}), 无法新增: {trigger}"
                    )
                policy = ExperiencePolicy.create(
                    trigger=trigger, strategy=strategy, kind=kind, detail=detail,
                    action_type=action_type, cause=cause,
                    action_sequence=action_sequence,
                    preconditions=preconditions,
                    required_action=required_action,
                    scene=scene, goal_type=goal_type,
                    version=1,
                    source_goal_ids=[source_goal_id] if source_goal_id else [],
                )
                self._policies[trigger] = policy
                return policy
            old = existing
            old.set_status(POLICY_STATUS_ARCHIVED)
            old.archived_at = time.time()
            history = self._versions.setdefault(trigger, [])
            history.insert(0, old)
            policy = ExperiencePolicy.create(
                trigger=trigger, strategy=strategy, kind=kind, detail=detail,
                action_type=action_type or old.action_type,
                cause=cause or old.cause,
                action_sequence=action_sequence or old.action_sequence,
                preconditions=preconditions,
                required_action=required_action or old.required_action,
                scene=scene or old.scene,
                goal_type=goal_type or old.goal_type,
                version=old.version + 1,
                source_goal_ids=old.source_goal_ids,
            )
            if source_goal_id and source_goal_id not in policy.source_goal_ids:
                policy.source_goal_ids.append(source_goal_id)
            self._policies[trigger] = policy
            logger.info(
                f"[Policy] 策略升级版本 trigger={trigger} "
                f"v{old.version} → v{policy.version}"
            )
            return policy

    def upsert_from_dict(self, d: Dict[str, Any]) -> ExperiencePolicy:
        """从 dict 合并策略 (加载 / 外部构造, 兼容 V4.3 旧数据)"""
        policy = ExperiencePolicy.from_dict(d)
        with self._lock:
            existing = self._policies.get(policy.trigger)
            if existing is None:
                if len(self._policies) >= self._max_policies:
                    raise PolicyTableError(
                        f"策略表已满 ({self._max_policies}), 无法新增: {policy.trigger}"
                    )
                self._policies[policy.trigger] = policy
                return policy
            existing.strategy = policy.strategy
            existing.kind = policy.kind
            existing.detail = policy.detail
            existing.action_type = policy.action_type or existing.action_type
            existing.cause = policy.cause or existing.cause
            if policy.action_sequence:
                existing.action_sequence = policy.action_sequence
            if policy.preconditions:
                existing.preconditions = policy.preconditions
            existing.required_action = policy.required_action or existing.required_action
            if policy.scene:
                existing.scene = policy.scene
            if policy.goal_type:
                existing.goal_type = policy.goal_type
            existing.suggest_count += policy.suggest_count
            existing.accepted_count += policy.accepted_count
            existing.success_count += policy.success_count
            existing.recovery_streak = max(
                existing.recovery_streak, policy.recovery_streak
            )
            if policy.effective_status in (
                POLICY_STATUS_DEGRADED, POLICY_STATUS_STALE, POLICY_STATUS_ARCHIVED
            ):
                existing.set_status(policy.effective_status)
            for gid in policy.source_goal_ids:
                if gid not in existing.source_goal_ids:
                    existing.source_goal_ids.append(gid)
            existing.updated_at = time.time()
            return existing

    # ── 查询 ──────────────────────────────────────────────────────
    def get(self, trigger: str) -> Optional[ExperiencePolicy]:
        with self._lock:
            return self._policies.get(trigger)

    def all(self, limit: int = 100) -> List[ExperiencePolicy]:
        with self._lock:
            policies = list(self._policies.values())
        policies.sort(key=lambda p: p.created_at)
        return policies[-limit:] if limit > 0 else policies

    def by_kind(self, kind: str, limit: int = 100) -> List[ExperiencePolicy]:
        out = [p for p in self.all(limit=0) if p.kind == kind]
        return out[-limit:] if limit > 0 else out

    def by_status(self, status: str, limit: int = 100) -> List[ExperiencePolicy]:
        """按生命周期状态查询 (V4.4)"""
        out = [p for p in self.all(limit=0) if p.effective_status == status]
        return out[-limit:] if limit > 0 else out

    def matching(self, action_type: str) -> List[ExperiencePolicy]:
        """按动作类型匹配失败策略 (供规划前查询)"""
        return [
            p for p in self.all(limit=0)
            if p.kind == "failure" and p.action_type == action_type
        ]

    def recipe(self, trigger: str) -> Optional[ExperiencePolicy]:
        """查询成功配方"""
        p = self.get(trigger)
        if p is not None and p.kind == "success":
            return p
        return None

    def count(self) -> int:
        with self._lock:
            return len(self._policies)

    # ── V4.4: 策略调度候选 (trigger → scene → goal_type → candidates) ──
    def candidates(
        self,
        action_type: Optional[str] = None,
        kind: Optional[str] = None,
        scene: Optional[str] = None,
        goal_type: Optional[str] = None,
        include_degraded: bool = False,
    ) -> List[ExperiencePolicy]:
        """按调度维度筛选候选策略 (V4.4)

        规则:
            - 仅 active (可选 degraded) 参与候选; stale / archived 不参与建议
            - scene: 策略场景为空 (全场景) 或与目标场景一致
            - goal_type: 策略目标类型为空 (全部) 或与目标类型一致
            - kind / action_type 精确匹配 (None=不限)
        """
        out: List[ExperiencePolicy] = []
        for p in self.all(limit=0):
            if p.effective_status == POLICY_STATUS_ARCHIVED:
                continue
            if p.effective_status == POLICY_STATUS_STALE:
                continue
            if p.effective_status == POLICY_STATUS_DELETED:
                continue
            if p.effective_status == POLICY_STATUS_DEGRADED and not include_degraded:
                continue
            if kind is not None and p.kind != kind:
                continue
            if action_type is not None and p.action_type != action_type:
                continue
            if scene and p.scene and p.scene != scene:
                continue
            if goal_type and p.goal_type and p.goal_type != goal_type:
                continue
            out.append(p)
        return out

    # ── V4.4: 策略生命周期 (归档 / 恢复 / 老化 / 恢复评估) ────────
    def archive_policy(self, trigger: str) -> Optional[ExperiencePolicy]:
        """归档策略: active/degraded/stale → archived (不是删除)

        归档策略不参与任何建议, 可通过 restore_policy 恢复。
        """
        with self._lock:
            p = self._policies.get(trigger)
            if p is None:
                return None
            if p.effective_status == POLICY_STATUS_ARCHIVED:
                logger.info(f"[Policy] 策略已归档, 忽略: {trigger}")
                return p
            p.set_status(POLICY_STATUS_ARCHIVED)
            p.archived_at = time.time()
        logger.info(f"[Policy] 策略归档: {trigger}")
        return p

    def restore_policy(self, trigger: str) -> Optional[ExperiencePolicy]:
        """恢复策略: archived/deleted → active (可重新参与建议)

        V4.5: 支持回收站恢复 (deleted → active)。
        """
        with self._lock:
            p = self._policies.get(trigger)
            if p is None:
                return None
            if p.effective_status not in (
                POLICY_STATUS_ARCHIVED, POLICY_STATUS_DELETED
            ):
                raise PolicyTableError(
                    f"只能恢复 archived / deleted 策略: {trigger} "
                    f"(当前: {p.effective_status})"
                )
            p.set_status(POLICY_STATUS_ACTIVE)
            p.archived_at = 0.0
            p.recovery_streak = 0
        logger.info(f"[Policy] 策略恢复: {trigger}")
        return p

    # ── V4.5: 策略回收站 (两阶段删除: archived → deleted(retained) → purge) ──
    def delete_policy(self, trigger: str) -> Optional[ExperiencePolicy]:
        """软删除策略: 任意状态 → deleted (保留在回收站, 可恢复, 不是彻底删除)

        删除后不参与任何建议 / 候选 / 审计统计。
        """
        with self._lock:
            p = self._policies.get(trigger)
            if p is None:
                return None
            if p.effective_status == POLICY_STATUS_DELETED:
                logger.info(f"[Policy] 策略已在回收站, 忽略: {trigger}")
                return p
            p.set_status(POLICY_STATUS_DELETED)
        logger.info(f"[Policy] 策略软删除 (回收站): {trigger}")
        return p

    def purge_policy(self, trigger: str) -> bool:
        """彻底删除策略 (purge): 从当前表 + 版本历史中移除, 不可恢复

        Returns:
            True=已清除 / False=策略不存在
        """
        with self._lock:
            if trigger not in self._policies:
                return False
            self._policies.pop(trigger, None)
            self._versions.pop(trigger, None)
        logger.info(f"[Policy] 策略彻底删除 (purge): {trigger}")
        return True

    def recycle_bin(self, limit: int = 100) -> List[Dict[str, Any]]:
        """回收站列表: 全部 deleted 策略 (最新删除在前)"""
        out = [
            p.to_dict()
            for p in self.all(limit=0)
            if p.effective_status == POLICY_STATUS_DELETED
        ]
        out.sort(key=lambda d: d.get("deleted_at", 0.0), reverse=True)
        return out[:limit] if limit > 0 else out

    # ── V4.5: 策略回滚 (仅最新版本 regression 允许) ─────────────────
    def all_versions(self, trigger: str) -> List[ExperiencePolicy]:
        """全部版本 (含历史 + 当前, 最旧在前)"""
        with self._lock:
            history = list(self._versions.get(trigger, []))
            current = self._policies.get(trigger)
        history.reverse()  # 最旧在前
        out = list(history)
        if current is not None:
            out.append(current)
        return out

    def rollback_policy(self, trigger: str) -> Optional[ExperiencePolicy]:
        """回滚策略: 当前版本入历史 (archived), 最近历史版本提升为当前 active

        Returns:
            回滚后成为当前版本的策略 / None (无历史版本可回滚)
        """
        with self._lock:
            current = self._policies.get(trigger)
            if current is None:
                return None
            history = self._versions.get(trigger, [])
            if not history:
                return None
            prev = history.pop(0)  # 最近历史版本 (历史最前端)
            current.set_status(POLICY_STATUS_ARCHIVED)
            current.archived_at = time.time()
            history.insert(0, current)
            prev.set_status(POLICY_STATUS_ACTIVE)
            prev.archived_at = 0.0
            prev.recovery_streak = 0
            self._policies[trigger] = prev
        logger.info(
            f"[Policy] 策略回滚: {trigger} v{current.version} → v{prev.version}"
        )
        return prev

    # ── V4.5: Policy Family (同化策略共享父级统计) ─────────────────
    def set_family(self, trigger: str, family_id: str) -> Optional[ExperiencePolicy]:
        """为策略设置 Policy Family 标识 (同化操作由 governance 调用)"""
        with self._lock:
            p = self._policies.get(trigger)
            if p is None:
                return None
            p.family_id = family_id
            p.updated_at = time.time()
        return p

    def families(self) -> Dict[str, Dict[str, Any]]:
        """Policy Family 汇总: family_id → 成员 + 共享父级统计

        父级统计 = 成员策略统计聚合 (suggest/accepted/success/avg hit_rate)
        """
        with self._lock:
            policies = list(self._policies.values())
        fam: Dict[str, List[ExperiencePolicy]] = {}
        for p in policies:
            if p.family_id:
                fam.setdefault(p.family_id, []).append(p)
        out: Dict[str, Dict[str, Any]] = {}
        for fid, members in fam.items():
            suggest = sum(m.suggest_count for m in members)
            accepted = sum(m.accepted_count for m in members)
            success = sum(m.success_count for m in members)
            out[fid] = {
                "family_id": fid,
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
        return out

    def policy_history(self, trigger: str) -> List[Dict[str, Any]]:
        """策略版本历史 (V4.4): 最旧 → 最新

        Returns:
            [{'version': 1, 'status': ..., 'strategy': ..., 'updated_at': ...}, ...]
        """
        with self._lock:
            current = self._policies.get(trigger)
            history = list(self._versions.get(trigger, []))
        history.reverse()  # 最旧在前
        entries = []
        for h in history:
            entries.append(h.to_dict())
        if current is not None:
            entries.append(current.to_dict())
        return entries

    def evaluate_aging(
        self,
        max_age_days: float,
        now: Optional[float] = None,
    ) -> List[str]:
        """策略老化评估 (V4.4): 超过 max_age_days 无使用 → stale

        规则 (可解释):
            - active / degraded 且 (now - last_activity_at) > max_age_days → stale
            - stale 策略不参与建议 (candidates 排除)
            - archived 不参与评估
        """
        if max_age_days <= 0:
            raise PolicyTableError(f"max_age_days 必须 > 0, 当前: {max_age_days}")
        now = now if now is not None else time.time()
        max_age_sec = float(max_age_days) * 86400.0
        aged: List[str] = []
        with self._lock:
            for p in self._policies.values():
                if p.effective_status not in (
                    POLICY_STATUS_ACTIVE, POLICY_STATUS_DEGRADED
                ):
                    continue
                if (now - p.last_activity_at) > max_age_sec:
                    p.set_status(POLICY_STATUS_STALE)
                    aged.append(p.trigger)
        if aged:
            logger.info(f"[Policy] 策略老化 → stale: {aged}")
        return aged

    def evaluate_recovery(self, recovery_threshold: int = 3) -> List[str]:
        """恢复评估 (V4.4): degraded 策略连续 N 次"建议+采纳+成功" → active

        规则 (可解释):
            - status == degraded 且 recovery_streak >= recovery_threshold
              → 自动恢复 active (重新参与建议)
        """
        if recovery_threshold <= 0:
            raise PolicyTableError(
                f"recovery_threshold 必须 > 0, 当前: {recovery_threshold}"
            )
        recovered: List[str] = []
        with self._lock:
            for p in self._policies.values():
                if p.effective_status != POLICY_STATUS_DEGRADED:
                    continue
                if p.recovery_streak >= recovery_threshold:
                    p.set_status(POLICY_STATUS_ACTIVE)
                    p.recovery_streak = 0
                    recovered.append(p.trigger)
        if recovered:
            logger.info(f"[Policy] 策略恢复评估 → active: {recovered}")
        return recovered

    # ── 质量指标 (V4.3 + V4.4) ────────────────────────────────────
    def record_suggested(self, trigger: str) -> None:
        """记录一次建议 (更新 last_suggested_at)"""
        with self._lock:
            p = self._policies.get(trigger)
            if p is None:
                return
            p.suggest_count += 1
            p.last_suggested_at = time.time()
            p.updated_at = time.time()

    def record_accepted(self, trigger: str, success: bool) -> None:
        """记录一次采纳 (success=最终是否成功, 更新恢复连胜)"""
        with self._lock:
            p = self._policies.get(trigger)
            if p is None:
                return
            p.accepted_count += 1
            if success:
                p.success_count += 1
                # V4.4 恢复机制: 连续采纳+成功 → recovery_streak+1; 失败清零
                if p.effective_status == POLICY_STATUS_DEGRADED:
                    p.recovery_streak += 1
            else:
                p.recovery_streak = 0
            p.last_accepted_at = time.time()
            p.updated_at = time.time()

    def evaluate_degradation(
        self,
        min_suggestions: int = 3,
        min_hit_rate: float = 0.5,
    ) -> List[str]:
        """自动降级评估: 低质量策略标记为 degraded

        规则 (规则表驱动, 可解释):
            - suggest_count >= min_suggestions 且 accepted_count == 0 → 降级 (从未被采纳)
            - suggest_count >= min_suggestions 且 hit_rate < min_hit_rate → 降级 (采纳后成功率过低)

        Returns:
            本次降级的 trigger 列表
        """
        degraded: List[str] = []
        with self._lock:
            for p in self._policies.values():
                if p.effective_status != POLICY_STATUS_ACTIVE:
                    continue
                if p.suggest_count >= min_suggestions and p.accepted_count == 0:
                    p.set_status(POLICY_STATUS_DEGRADED)
                    degraded.append(p.trigger)
                elif (
                    p.suggest_count >= min_suggestions
                    and p.hit_rate < min_hit_rate
                ):
                    p.set_status(POLICY_STATUS_DEGRADED)
                    degraded.append(p.trigger)
        if degraded:
            logger.info(f"[Policy] 自动降级策略: {degraded}")
        return degraded

    def stats(self) -> Dict[str, Any]:
        """策略统计: 数量 / 建议 / 采纳 / 成功 / 命中率 / 状态分布"""
        with self._lock:
            policies = list(self._policies.values())
        suggest = sum(p.suggest_count for p in policies)
        accepted = sum(p.accepted_count for p in policies)
        success = sum(p.success_count for p in policies)
        return {
            "total": len(policies),
            "failure_count": sum(1 for p in policies if p.kind == "failure"),
            "success_count": sum(1 for p in policies if p.kind == "success"),
            "degraded_count": sum(1 for p in policies if p.effective_status == POLICY_STATUS_DEGRADED),
            "status_counts": {
                s: sum(1 for p in policies if p.effective_status == s)
                for s in POLICY_STATUSES
            },
            "version_total": sum(1 + len(self._versions.get(p.trigger, [])) for p in policies),
            "suggest_count": suggest,
            "accepted_count": accepted,
            "success_count_executed": success,
            "hit_rate": round(success / accepted, 4) if accepted else 0.0,
            "acceptance_rate": round(accepted / suggest, 4) if suggest else 0.0,
            "mode": "rule_based",
        }

    # ── 持久化 (JSONL, 兼容 V4.3) ────────────────────────────────
    def save_to_file(self, path: str) -> int:
        """保存全部策略到 JSONL 文件 (embodied_policy.jsonl, 含版本历史)"""
        with self._lock:
            policies = list(self._policies.values())
            versions = [
                v for vs in self._versions.values() for v in vs
            ]
        with open(path, "w", encoding="utf-8") as f:
            for p in versions + policies:
                f.write(json.dumps(p.to_dict(), ensure_ascii=False) + "\n")
        logger.info(f"[Policy] 已保存到 {path}, 共 {len(versions) + len(policies)} 条")
        return len(versions) + len(policies)

    def load_from_file(self, path: str) -> int:
        """从 JSONL 文件加载策略 (追加/合并, 版本历史还原)

        版本还原规则 (V4.4):
            - 无当前版本 → 直接成为当前版本
            - 行版本号 > 当前版本 → 提升为当前版本, 旧当前版本入历史
            - 行版本号 == 当前版本 → 合并统计 (V4.3 语义)
            - 行版本号 < 当前版本 → 放入版本历史 (去重)
        """
        if not os.path.isfile(path):
            logger.warning(f"[Policy] 策略文件不存在, 跳过: {path}")
            return 0
        loaded = 0
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                    self._restore_one(d)
                    loaded += 1
                except (json.JSONDecodeError, TypeError, PolicyTableError) as e:
                    logger.warning(f"[Policy] 跳过坏行: {e}")
        logger.info(f"[Policy] 已从 {path} 加载 {loaded} 条")
        return loaded

    def _restore_one(self, d: Dict[str, Any]) -> None:
        """按版本号还原一条策略 (供 load_from_file 使用)"""
        trigger = d.get("trigger", "")
        version = int(d.get("version", 1))
        with self._lock:
            existing = self._policies.get(trigger)
            if existing is None:
                if len(self._policies) >= self._max_policies:
                    raise PolicyTableError(
                        f"策略表已满 ({self._max_policies}), 无法新增: {trigger}"
                    )
                self._policies[trigger] = ExperiencePolicy.from_dict(d)
                return
            if version > existing.version:
                # 高版本 → 提升为当前, 旧当前版本入历史
                self._versions.setdefault(trigger, []).insert(0, existing)
                self._policies[trigger] = ExperiencePolicy.from_dict(d)
                return
            if version == existing.version:
                self.upsert_from_dict(d)
                return
            # 低版本 → 历史 (按版本号去重)
            hist = self._versions.setdefault(trigger, [])
            if not any(h.version == version for h in hist):
                hist.append(ExperiencePolicy.from_dict(d))

    # ── 生命周期 ──────────────────────────────────────────────────
    def clear(self) -> int:
        with self._lock:
            n = len(self._policies)
            self._policies.clear()
            self._versions.clear()
        logger.info(f"[Policy] 策略已清空, 清理 {n} 条")
        return n

    @property
    def max_policies(self) -> int:
        with self._lock:
            return self._max_policies


__all__ = [
    "ExperiencePolicy",
    "PolicyTable",
    "PolicyTableError",
    "POLICY_STATUS_ACTIVE",
    "POLICY_STATUS_DEGRADED",
    "POLICY_STATUS_STALE",
    "POLICY_STATUS_ARCHIVED",
    "POLICY_STATUS_DELETED",
    "POLICY_STATUSES",
]
