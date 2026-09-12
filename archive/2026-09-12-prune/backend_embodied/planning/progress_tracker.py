"""
YHLZ Embodied AI V4.7 - 进度跟踪与任务快照 (Progress Tracking & Goal Snapshot)

职责:
    - get_progress(goal_id): 长期任务进度 (0.0 ~ 1.0)
    - update_progress(goal_id): 进度重算 (里程碑完成数 / 总数)
    - progress_report(goal_id): 文本报告 (Goal 60% / Completed 3/5 / Blocked 1 / Next)
    - snapshot(goal_id): Goal Snapshot (当前状态 / 完成情况 / 阻塞点 / 下一步骤,
      支持恢复)

设计原则:
    - 只读/纯计算 (进度来源: 里程碑状态)
    - 可解释输出
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List, Optional

from backend.embodied.planning.dependency_graph import DependencyGraph
from backend.embodied.planning.milestone import LongGoal, LongHorizonError

logger = logging.getLogger(__name__)


class ProgressError(Exception):
    """进度跟踪操作异常"""


class ProgressTracker:
    """进度跟踪器

    用法:
        tracker = ProgressTracker()
        progress = tracker.get_progress(goal)
        report = tracker.progress_report(goal)
        snap = tracker.snapshot(goal)
    """

    def __init__(self, dependency_graph: Optional[DependencyGraph] = None):
        self._lock = threading.RLock()
        self._graph = dependency_graph or DependencyGraph()

    # ── 进度计算 ──────────────────────────────────────────────────
    @staticmethod
    def _compute_progress(goal: LongGoal) -> float:
        """进度 = 已完成里程碑 / 里程碑总数 (0.0 ~ 1.0)"""
        if not goal.milestones:
            return 0.0
        done = sum(1 for m in goal.milestones if m.status == "completed")
        return round(done / len(goal.milestones), 4)

    def get_progress(self, goal: LongGoal) -> Dict[str, Any]:
        """获取进度: 百分比 / 完成数 / 阻塞数 / 下一步"""
        with self._lock:
            if goal is None:
                raise ProgressError("目标不能为空")
            progress = self._compute_progress(goal)
            total = len(goal.milestones)
            done = sum(1 for m in goal.milestones if m.status == "completed")
            blocked = len(self._graph.compute_blocked(goal))
            next_m = next(
                (m for m in sorted(goal.milestones, key=lambda x: x.order)
                 if m.status == "pending"), None,
            )
            return {
                "goal_id": goal.goal_id,
                "status": goal.status,
                "progress": progress,
                "percent": int(progress * 100),
                "completed": done,
                "total": total,
                "blocked": blocked,
                "next": (
                    {"milestone_id": next_m.milestone_id,
                     "title": next_m.title}
                    if next_m else None
                ),
            }

    def update_progress(self, goal: LongGoal) -> LongGoal:
        """更新目标 progress 字段 (从里程碑状态重算)"""
        with self._lock:
            if goal is None:
                raise ProgressError("目标不能为空")
            goal.progress = self._compute_progress(goal)
            goal.updated_at = time.time()
            if goal.progress >= 1.0 and goal.milestones:
                if goal.status in ("active", "pending"):
                    goal.set_status("completed", reason="进度 100%, 自动完成")
            return goal

    # ── 报告 ──────────────────────────────────────────────────────
    def progress_report(self, goal: LongGoal) -> str:
        """进度文本报告 (可解释)

        输出示例:
            Goal: 整理房间 (60%)
            Completed: 3/5 milestones
            Blocked: 1
            Next: Milestone 4 (检查)
        """
        with self._lock:
            p = self.get_progress(goal)
            lines = [
                f"Goal: {goal.title} ({p['percent']}%)",
                f"Completed: {p['completed']}/{p['total']} milestones",
                f"Blocked: {p['blocked']}",
            ]
            if p["next"]:
                idx = next(
                    (i + 1 for i, m in enumerate(goal.milestones)
                     if m.milestone_id == p["next"]["milestone_id"]), 0,
                )
                lines.append(
                    f"Next: Milestone {idx} ({p['next']['title']})"
                )
            else:
                lines.append("Next: None (全部完成或全部阻塞)")
            return "\n".join(lines)

    # ── Goal Snapshot (P1, 支持恢复) ──────────────────────────────
    def snapshot(self, goal: LongGoal) -> Dict[str, Any]:
        """Goal Snapshot: 当前状态 / 完成情况 / 阻塞点 / 下一步骤

        Returns:
            {
                'snapshot_id', 'goal_id', 'title', 'status',
                'progress', 'completed_milestones', 'total_milestones',
                'blocked_milestones': [...], 'next_step': {...},
                'milestones': [...], 'dependencies': {...},
                'created_at',
            }
        """
        with self._lock:
            import uuid
            p = self.get_progress(goal)
            blocked_milestones = [
                m.to_dict() for m in goal.milestones
                if m.milestone_id in self._graph.compute_blocked(goal)
            ]
            return {
                "snapshot_id": "snap_" + uuid.uuid4().hex[:8],
                "goal_id": goal.goal_id,
                "title": goal.title,
                "status": goal.status,
                "progress": p["progress"],
                "completed_milestones": p["completed"],
                "total_milestones": p["total"],
                "blocked_milestones": blocked_milestones,
                "next_step": p["next"],
                "milestones": [m.to_dict() for m in goal.milestones],
                "dependencies": dict(goal.dependencies),
                "created_at": time.time(),
            }

    # ── 快照恢复 (P1) ─────────────────────────────────────────────
    def restore_from_snapshot(self, goal: LongGoal, snap: Dict[str, Any]) -> LongGoal:
        """从快照恢复里程碑状态 (支持断点恢复)

        规则 (可解释):
            - 按 order 匹配 (快照里程碑顺序 ↔ 目标里程碑顺序, 跨会话 ID 不同)
            - completed 里程碑 → 状态 completed
            - 其余按快照状态还原 (failed → pending 可重试)
        """
        with self._lock:
            if goal is None or not snap:
                raise ProgressError("恢复需要目标与快照")
            snap_by_order = {
                int(m.get("order", i)): m
                for i, m in enumerate(snap.get("milestones", []))
            }
            for m in goal.milestones:
                sm = snap_by_order.get(m.order)
                if sm is None:
                    continue
                status = sm.get("status", "pending")
                if status == "completed":
                    try:
                        m.set_status("completed")
                    except LongHorizonError:
                        pass
                elif status in ("failed", "blocked", "paused"):
                    try:
                        m.set_status("pending")
                    except LongHorizonError:
                        pass
                elif status == "running":
                    try:
                        m.set_status("running")
                    except LongHorizonError:
                        pass
            # 依赖按 order 重新映射 (跨会话 ID 不同)
            order_to_id = {m.order: m.milestone_id for m in goal.milestones}
            restored_deps: Dict[str, List[str]] = {}
            for mid, prereqs in (snap.get("dependencies", {}) or {}).items():
                src_order = self._order_of(snap_by_order, mid)
                dst_id = order_to_id.get(src_order)
                if dst_id is None:
                    continue
                mapped_prereqs = [
                    order_to_id[self._order_of(snap_by_order, p)]
                    for p in prereqs
                    if self._order_of(snap_by_order, p) in order_to_id
                ]
                restored_deps[dst_id] = mapped_prereqs
            goal.dependencies = restored_deps
            goal.progress = self._compute_progress(goal)
            goal.updated_at = time.time()
            goal.explainable_reason = "从快照恢复 (断点恢复)"
            return goal

    @staticmethod
    def _order_of(snap_by_order: Dict[int, Any], milestone_id: str) -> Optional[int]:
        """快照里程碑 ID → order"""
        for order, m in snap_by_order.items():
            if m.get("milestone_id") == milestone_id:
                return order
        return None


__all__ = [
    "ProgressError",
    "ProgressTracker",
]
