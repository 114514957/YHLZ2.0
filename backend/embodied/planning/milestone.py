"""
YHLZ Embodied AI V4.7 - 长期目标与里程碑 (Long Goal & Milestone)

职责:
    - LongGoal: 长期任务数据模型 (goal_id / title / description / created_at /
      status / milestones / dependencies / progress / priority / explainable_reason)
    - status 状态机: pending → active → paused → completed / failed / archived
    - Milestone: 长期目标阶段管理 (milestone_id / goal_id / title / sub_goals /
      order / status / completion_rate)
    - 里程碑生命周期: add_milestone / complete_milestone / rollback_milestone
    - 子目标分解: decompose_goal → 完整任务树

设计原则:
    - 纯规则 + 状态机: 禁止黑盒优化
    - 可解释: 每个状态变更记录 reason
    - 数据独立: 不写入 Agent Memory
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class LongHorizonError(Exception):
    """长期任务规划操作异常"""


# 长期目标状态机 (可解释)
LONG_GOAL_STATUSES: List[str] = [
    "pending",    # 已创建, 待激活
    "active",     # 执行中
    "paused",     # 暂停 (可恢复)
    "completed",  # 完成
    "failed",     # 失败 (可重试)
    "archived",   # 归档 (不再参与)
]

# 里程碑状态机
MILESTONE_STATUSES: List[str] = [
    "pending",    # 待执行
    "running",    # 执行中
    "completed",  # 完成
    "failed",     # 失败
    "blocked",    # 被依赖阻塞
]

# 里程碑间默认转换规则 (状态机, 可解释)
MILESTONE_TRANSITIONS: Dict[str, List[str]] = {
    "pending": ["running", "blocked", "completed"],  # 可直接完成 (跳过)
    "running": ["completed", "failed", "paused"],
    "completed": ["failed"],          # 支持回滚 (rollback_milestone)
    "failed": ["running", "blocked", "completed"],  # 失败可重试
    "blocked": ["running", "pending", "completed"],
}


@dataclass
class LongGoal:
    """长期目标 (Long Horizon Task)

    Attributes:
        goal_id:           长期目标唯一 ID
        title:             标题
        description:       描述
        created_at:        创建时间
        status:            状态 (pending/active/paused/completed/failed/archived)
        milestones:        里程碑列表 (List[Milestone])
        dependencies:      依赖关系 (milestone_id → [前置 milestone_id])
        progress:          进度 (0.0 ~ 1.0)
        priority:          优先级 (low/medium/high)
        deadline:          截止时间 (时间戳, 0=无)
        explainable_reason:可解释原因 (最近一次状态变更说明)
        updated_at:        更新时间
    """
    goal_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    title: str = ""
    description: str = ""
    created_at: float = field(default_factory=time.time)
    status: str = "pending"
    milestones: List["Milestone"] = field(default_factory=list)
    dependencies: Dict[str, List[str]] = field(default_factory=dict)
    progress: float = 0.0
    priority: str = "medium"
    deadline: float = 0.0
    explainable_reason: str = ""
    updated_at: float = field(default_factory=time.time)

    def set_status(self, status: str, reason: str = "") -> None:
        """状态变更 (状态机校验 + 可解释原因)"""
        if status not in LONG_GOAL_STATUSES:
            raise LongHorizonError(
                f"非法长期目标状态: {status} (可选: {LONG_GOAL_STATUSES})"
            )
        self.status = status
        self.updated_at = time.time()
        self.explainable_reason = reason or f"状态变更为 {status}"
        logger.info(f"[LongGoal] {self.goal_id} → {status}: {self.explainable_reason}")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "goal_id": self.goal_id,
            "title": self.title,
            "description": self.description,
            "created_at": self.created_at,
            "status": self.status,
            "milestones": [m.to_dict() for m in self.milestones],
            "dependencies": dict(self.dependencies),
            "progress": round(self.progress, 4),
            "priority": self.priority,
            "deadline": self.deadline,
            "explainable_reason": self.explainable_reason,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "LongGoal":
        goal = cls(
            goal_id=d.get("goal_id", uuid.uuid4().hex),
            title=d.get("title", ""),
            description=d.get("description", ""),
            created_at=float(d.get("created_at", time.time())),
            status=d.get("status", "pending"),
            dependencies=dict(d.get("dependencies", {}) or {}),
            progress=float(d.get("progress", 0.0)),
            priority=d.get("priority", "medium"),
            deadline=float(d.get("deadline", 0.0)),
            explainable_reason=d.get("explainable_reason", ""),
            updated_at=float(d.get("updated_at", time.time())),
        )
        goal.milestones = [
            Milestone.from_dict(m) for m in (d.get("milestones") or [])
        ]
        return goal

    @classmethod
    def create(
        cls,
        title: str,
        description: str = "",
        priority: str = "medium",
        deadline: float = 0.0,
    ) -> "LongGoal":
        """创建长期目标"""
        return cls(
            title=title, description=description,
            priority=priority, deadline=deadline,
            explainable_reason="长期目标创建 (pending)",
        )


@dataclass
class Milestone:
    """里程碑 (长期目标阶段)

    Attributes:
        milestone_id:     里程碑唯一 ID
        goal_id:          所属长期目标 ID
        title:            阶段标题
        sub_goals:        子目标列表 (List[Dict]: title/description/intent)
        order:            执行顺序 (0 起)
        status:           状态 (pending/running/completed/failed/blocked)
        completion_rate:  完成率 (0.0 ~ 1.0)
        estimated_duration: 预计耗时 (分钟, 0=未知)
        created_at:       创建时间
    """
    milestone_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    goal_id: str = ""
    title: str = ""
    sub_goals: List[Dict[str, Any]] = field(default_factory=list)
    order: int = 0
    status: str = "pending"
    completion_rate: float = 0.0
    estimated_duration: float = 0.0
    created_at: float = field(default_factory=time.time)

    def set_status(self, status: str) -> None:
        """状态变更 (状态机校验)"""
        if status not in MILESTONE_STATUSES:
            raise LongHorizonError(
                f"非法里程碑状态: {status} (可选: {MILESTONE_STATUSES})"
            )
        allowed = MILESTONE_TRANSITIONS.get(self.status, [])
        if status not in allowed:
            raise LongHorizonError(
                f"非法里程碑状态迁移: {self.status} → {status} "
                f"(可选: {allowed})"
            )
        self.status = status
        if status == "completed":
            self.completion_rate = 1.0
        logger.info(
            f"[Milestone] {self.milestone_id} ({self.title}) → {status}"
        )

    def add_sub_goal(self, title: str, description: str = "",
                     intent: str = "") -> "Milestone":
        """添加子目标"""
        self.sub_goals.append({
            "sub_goal_id": uuid.uuid4().hex,
            "title": title,
            "description": description,
            "intent": intent,
        })
        return self

    def to_dict(self) -> Dict[str, Any]:
        return {
            "milestone_id": self.milestone_id,
            "goal_id": self.goal_id,
            "title": self.title,
            "sub_goals": self.sub_goals,
            "order": self.order,
            "status": self.status,
            "completion_rate": round(self.completion_rate, 4),
            "estimated_duration": self.estimated_duration,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Milestone":
        return cls(
            milestone_id=d.get("milestone_id", uuid.uuid4().hex),
            goal_id=d.get("goal_id", ""),
            title=d.get("title", ""),
            sub_goals=list(d.get("sub_goals", []) or []),
            order=int(d.get("order", 0)),
            status=d.get("status", "pending"),
            completion_rate=float(d.get("completion_rate", 0.0)),
            estimated_duration=float(d.get("estimated_duration", 0.0)),
            created_at=float(d.get("created_at", time.time())),
        )

    @classmethod
    def create(cls, title: str, goal_id: str = "", order: int = 0,
               estimated_duration: float = 0.0) -> "Milestone":
        """创建里程碑"""
        return cls(
            title=title, goal_id=goal_id, order=order,
            estimated_duration=estimated_duration,
        )


class MilestoneManager:
    """里程碑管理器 (长期目标阶段管理)

    用法:
        mgr = MilestoneManager()
        goal = mgr.create_long_goal(title="整理房间")
        mgr.decompose_goal(goal, phases=["收集", "分类", "整理", "检查", "维护"])
        mgr.complete_milestone(goal, milestone_id)
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._goals: Dict[str, LongGoal] = {}

    # ── Long Goal 生命周期 ────────────────────────────────────────
    def create_long_goal(
        self,
        title: str,
        description: str = "",
        priority: str = "medium",
        deadline: float = 0.0,
    ) -> LongGoal:
        """创建长期目标 (status=pending)"""
        with self._lock:
            goal = LongGoal.create(
                title=title, description=description,
                priority=priority, deadline=deadline,
            )
            self._goals[goal.goal_id] = goal
            return goal

    def get(self, goal_id: str) -> Optional[LongGoal]:
        with self._lock:
            return self._goals.get(goal_id)

    def all(self) -> List[LongGoal]:
        with self._lock:
            return list(self._goals.values())

    def set_status(self, goal_id: str, status: str, reason: str = "") -> LongGoal:
        """长期目标状态变更 (active/paused/completed/failed/archived)"""
        with self._lock:
            goal = self._goals.get(goal_id)
            if goal is None:
                raise LongHorizonError(f"长期目标不存在: {goal_id}")
            goal.set_status(status, reason)
            return goal

    # ── 目标分解 (Sub Goal 分解) ─────────────────────────────────
    def decompose_goal(
        self,
        goal: LongGoal,
        phases: List[str],
        sub_goals_map: Optional[Dict[str, List[str]]] = None,
    ) -> LongGoal:
        """长期目标拆解: 阶段 (Milestone) + 子目标 (Sub Goal) → 任务树

        Args:
            goal: 长期目标
            phases: 阶段标题列表 (如 ['收集物品', '分类', '整理', '检查', '维护'])
            sub_goals_map: 阶段 → 子目标标题列表 (可选)

        Returns:
            goal (milestones 已填充, 状态 → active)
        """
        with self._lock:
            if goal is None or not phases:
                raise LongHorizonError("分解需要非空阶段列表")
            existing = self._goals.get(goal.goal_id)
            if existing is None:
                raise LongHorizonError(f"长期目标不存在: {goal.goal_id}")
            if existing.milestones:
                raise LongHorizonError(
                    f"长期目标已分解: {goal.goal_id} (重复分解禁止)"
                )
            for i, phase in enumerate(phases):
                m = Milestone.create(
                    title=phase, goal_id=goal.goal_id, order=i,
                    estimated_duration=5.0,
                )
                for sub in (sub_goals_map or {}).get(phase, []):
                    m.add_sub_goal(title=sub)
                existing.milestones.append(m)
            existing.set_status(
                "active", reason=f"目标分解为 {len(phases)} 个里程碑"
            )
            return existing

    # ── Milestone 生命周期 ────────────────────────────────────────
    def get_milestone(self, goal: LongGoal, milestone_id: str) -> Milestone:
        """按 ID 查里程碑"""
        for m in goal.milestones:
            if m.milestone_id == milestone_id:
                return m
        raise LongHorizonError(f"里程碑不存在: {milestone_id}")

    def complete_milestone(self, goal: LongGoal, milestone_id: str) -> Milestone:
        """完成里程碑 (running → completed)"""
        with self._lock:
            m = self.get_milestone(goal, milestone_id)
            m.set_status("completed")
            # 完成进度重算
            done = sum(1 for x in goal.milestones
                       if x.status == "completed")
            goal.progress = round(done / len(goal.milestones), 4) \
                if goal.milestones else 0.0
            goal.updated_at = time.time()
            goal.explainable_reason = f"里程碑完成: {m.title} ({done}/{len(goal.milestones)})"
            if all(x.status == "completed" for x in goal.milestones):
                goal.set_status("completed", reason="全部里程碑完成")
            return m

    def rollback_milestone(self, goal: LongGoal, milestone_id: str) -> Milestone:
        """里程碑回滚 (completed → failed, 支持重排)"""
        with self._lock:
            m = self.get_milestone(goal, milestone_id)
            m.set_status("failed")
            goal.progress = round(
                sum(1 for x in goal.milestones if x.status == "completed")
                / len(goal.milestones), 4,
            ) if goal.milestones else 0.0
            goal.updated_at = time.time()
            goal.explainable_reason = f"里程碑回滚: {m.title}"
            if goal.status == "completed":
                goal.set_status("active", reason="里程碑回滚, 任务重新激活")
            return m

    # ── 查询 ──────────────────────────────────────────────────────
    def query_progress(self, goal: LongGoal) -> Dict[str, Any]:
        """里程碑进度查询"""
        with self._lock:
            total = len(goal.milestones)
            done = sum(1 for m in goal.milestones
                       if m.status == "completed")
            blocked = sum(1 for m in goal.milestones
                          if m.status == "blocked")
            next_m = next(
                (m for m in sorted(goal.milestones, key=lambda x: x.order)
                 if m.status == "pending"), None,
            )
            return {
                "goal_id": goal.goal_id,
                "goal_status": goal.status,
                "progress": goal.progress,
                "completed": done,
                "total": total,
                "blocked": blocked,
                "next": (
                    {"milestone_id": next_m.milestone_id,
                     "title": next_m.title, "order": next_m.order}
                    if next_m else None
                ),
                "milestones": [m.to_dict() for m in goal.milestones],
            }

    # ── 清理 ──────────────────────────────────────────────────────
    def clear(self) -> int:
        with self._lock:
            n = len(self._goals)
            self._goals.clear()
            logger.info(f"[LongGoal] 清理 {n} 个长期目标")
            return n

    def remove(self, goal_id: str) -> bool:
        """移除长期目标 (测试清理)"""
        with self._lock:
            return self._goals.pop(goal_id, None) is not None


__all__ = [
    "LONG_GOAL_STATUSES",
    "MILESTONE_STATUSES",
    "MILESTONE_TRANSITIONS",
    "LongGoal",
    "LongHorizonError",
    "Milestone",
    "MilestoneManager",
]
