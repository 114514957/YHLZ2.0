"""
YHLZ Embodied AI V4.7 - 长期任务规划器 (Long Horizon Planner)

职责:
    - create_long_goal(goal): 创建长期目标
    - decompose_goal(goal_id): 目标拆解 → 完整任务树 (里程碑 + 子目标)
    - generate_milestones(goal_id): 自动生成里程碑 (规则模板)
    - track_progress(goal_id): 进度跟踪
    - adjust_plan(goal_id): 计划调整 (触发条件 → 方案, 不自动执行)
    - 集成 V4.6 Cross Goal Planner: 里程碑 → 子规划 (跨目标规划)
    - 集成 Experience Memory: 只读历史参考 (失败模式提醒 / 策略推荐)

数据流:
    Long Goal → Milestone → Cross Goal Planner → Strategy Selection → Execution

安全约束:
    - 规划只输出方案: 不自动执行, 不绕过 Permission Layer
    - 允许读取 Experience Memory, 禁止修改
    - 纯规则 + 状态机: 禁止黑盒优化
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

from backend.embodied.planning.adjustment import PlanAdjuster
from backend.embodied.planning.dependency_graph import DependencyGraph
from backend.embodied.planning.milestone import (
    LongGoal,
    LongHorizonError,
    Milestone,
    MilestoneManager,
)
from backend.embodied.planning.progress_tracker import ProgressTracker
from backend.embodied.schema import EmbodiedGoal
from backend.embodied.strategy.audit import PolicyAuditLog

logger = logging.getLogger(__name__)


class LongHorizonPlannerError(Exception):
    """长期任务规划器操作异常"""


class LongHorizonPlanner:
    """长期任务规划器 (门面)

    用法:
        planner = LongHorizonPlanner(audit=audit)
        goal = planner.create_long_goal(title="整理房间")
        planner.decompose_goal(goal.goal_id, ["收集", "分类", "整理", "检查", "维护"])
        progress = planner.track_progress(goal.goal_id)
        adjustment = planner.adjust_plan(goal.goal_id)
    """

    def __init__(
        self,
        audit: Optional[PolicyAuditLog] = None,
        milestone_manager: Optional[MilestoneManager] = None,
        dependency_graph: Optional[DependencyGraph] = None,
        progress_tracker: Optional[ProgressTracker] = None,
        plan_adjuster: Optional[PlanAdjuster] = None,
        min_goals_per_milestone: int = 1,
    ):
        self._lock = threading.RLock()
        self._audit = audit
        self._milestones = milestone_manager or MilestoneManager()
        self._graph = dependency_graph or DependencyGraph()
        self._tracker = progress_tracker or ProgressTracker(self._graph)
        self._adjuster = plan_adjuster or PlanAdjuster(self._tracker)
        self._min_goals_per_milestone = min_goals_per_milestone

    # ── 1. 创建长期目标 ───────────────────────────────────────────
    def create_long_goal(
        self,
        title: str,
        description: str = "",
        priority: str = "medium",
        deadline: float = 0.0,
        record_audit: bool = True,
    ) -> Dict[str, Any]:
        """创建长期目标 (status=pending)"""
        with self._lock:
            goal = self._milestones.create_long_goal(
                title=title, description=description,
                priority=priority, deadline=deadline,
            )
            if record_audit and self._audit is not None:
                self._audit.record(
                    trigger=goal.goal_id,
                    action="create_long_goal",
                    applied=True,
                    goal_id=goal.goal_id,
                    kind="long_horizon",
                    reason=f"长期目标创建: {title} (pending)",
                )
            return goal.to_dict()

    # ── 2. 目标分解 → 任务树 ──────────────────────────────────────
    def decompose_goal(
        self,
        goal_id: str,
        phases: List[str],
        sub_goals_map: Optional[Dict[str, List[str]]] = None,
        record_audit: bool = True,
    ) -> Dict[str, Any]:
        """目标拆解 → 完整任务树 (里程碑 + 子目标)"""
        with self._lock:
            goal = self._milestones.get(goal_id)
            if goal is None:
                raise LongHorizonPlannerError(f"长期目标不存在: {goal_id}")
            self._milestones.decompose_goal(goal, phases, sub_goals_map)
            if record_audit and self._audit is not None:
                self._audit.record(
                    trigger=goal_id,
                    action="decompose_goal",
                    applied=True,
                    goal_id=goal_id,
                    kind="long_horizon",
                    reason=f"目标拆解: {len(phases)} 个里程碑",
                )
            return self._task_tree(goal)

    # ── 3. 自动生成里程碑 (规则模板) ──────────────────────────────
    def generate_milestones(self, goal_id: str) -> Dict[str, Any]:
        """自动生成里程碑: 按意图关键词规则模板

        规则 (可解释):
            - 整理/收拾 → [收集, 分类, 整理, 检查, 维护]
            - 学习 → [基础阶段, 进阶阶段, 项目实践, 复习评估]
            - 巡逻/巡检 → [感知, 检查, 报告, 维护]
            - 默认 → [准备, 执行, 检查, 收尾]
        """
        with self._lock:
            goal = self._milestones.get(goal_id)
            if goal is None:
                raise LongHorizonPlannerError(f"长期目标不存在: {goal_id}")
            text = (goal.title + " " + goal.description).lower()
            templates = (
                ("整理", ["收集物品", "分类", "整理", "检查", "维护"]),
                ("收拾", ["收集物品", "分类", "整理", "检查", "维护"]),
                ("学习", ["基础阶段", "进阶阶段", "项目实践", "复习评估"]),
                ("巡逻", ["感知环境", "逐区检查", "记录报告", "维护反馈"]),
                ("巡检", ["感知环境", "逐区检查", "记录报告", "维护反馈"]),
                ("维修", ["故障诊断", "备件准备", "执行修复", "验证测试"]),
                ("搬", ["规划路线", "搬运执行", "归位整理", "验收检查"]),
            )
            phases = next(
                (ph for kw, ph in templates if kw in text),
                ["准备", "执行", "检查", "收尾"],
            )
            self._milestones.decompose_goal(goal, phases)
            if self._audit is not None:
                self._audit.record(
                    trigger=goal_id,
                    action="decompose_goal",
                    applied=True,
                    goal_id=goal_id,
                    kind="long_horizon",
                    reason=f"自动拆解 (模板): {len(phases)} 个里程碑",
                )
            return {
                "goal_id": goal_id,
                "template_used": phases,
                "milestones": [m.to_dict() for m in goal.milestones],
            }

    # ── 任务树 ────────────────────────────────────────────────────
    def _task_tree(self, goal: LongGoal) -> Dict[str, Any]:
        return {
            "goal_id": goal.goal_id,
            "title": goal.title,
            "status": goal.status,
            "milestones": [
                {
                    "milestone_id": m.milestone_id,
                    "title": m.title,
                    "order": m.order,
                    "status": m.status,
                    "sub_goals": m.sub_goals,
                }
                for m in goal.milestones
            ],
        }

    # ── 4. 进度跟踪 ───────────────────────────────────────────────
    def track_progress(self, goal_id: str) -> Dict[str, Any]:
        """进度跟踪 (百分比 / 完成数 / 阻塞 / 下一步)"""
        with self._lock:
            goal = self._milestones.get(goal_id)
            if goal is None:
                raise LongHorizonPlannerError(f"长期目标不存在: {goal_id}")
            self._tracker.update_progress(goal)
            return self._tracker.get_progress(goal)

    def progress_report(self, goal_id: str) -> str:
        """进度文本报告"""
        with self._lock:
            goal = self._milestones.get(goal_id)
            if goal is None:
                raise LongHorizonPlannerError(f"长期目标不存在: {goal_id}")
            return self._tracker.progress_report(goal)

    # ── 5. 里程碑管理 ─────────────────────────────────────────────
    def complete_milestone(
        self,
        goal_id: str,
        milestone_id: str,
        record_audit: bool = True,
    ) -> Dict[str, Any]:
        """完成里程碑"""
        with self._lock:
            goal = self._milestones.get(goal_id)
            if goal is None:
                raise LongHorizonPlannerError(f"长期目标不存在: {goal_id}")
            m = self._milestones.complete_milestone(goal, milestone_id)
            if record_audit and self._audit is not None:
                self._audit.record(
                    trigger=goal_id,
                    action="milestone_complete",
                    applied=True,
                    goal_id=goal_id,
                    kind="long_horizon",
                    reason=f"里程碑完成: {m.title}",
                )
            return m.to_dict()

    def rollback_milestone(
        self,
        goal_id: str,
        milestone_id: str,
        record_audit: bool = True,
    ) -> Dict[str, Any]:
        """里程碑回滚"""
        with self._lock:
            goal = self._milestones.get(goal_id)
            if goal is None:
                raise LongHorizonPlannerError(f"长期目标不存在: {goal_id}")
            m = self._milestones.rollback_milestone(goal, milestone_id)
            if record_audit and self._audit is not None:
                self._audit.record(
                    trigger=goal_id,
                    action="plan_adjust",
                    applied=True,
                    goal_id=goal_id,
                    kind="long_horizon",
                    reason=f"里程碑回滚 (计划调整): {m.title}",
                )
            return m.to_dict()

    # ── 6. 依赖关系 ───────────────────────────────────────────────
    def set_dependencies(
        self,
        goal_id: str,
        deps: Dict[str, List[str]],
        record_audit: bool = True,
    ) -> Dict[str, Any]:
        """设置里程碑依赖"""
        with self._lock:
            goal = self._milestones.get(goal_id)
            if goal is None:
                raise LongHorizonPlannerError(f"长期目标不存在: {goal_id}")
            self._graph.set_dependencies(goal, deps)
            if record_audit and self._audit is not None:
                self._audit.record(
                    trigger=goal_id,
                    action="decompose_goal",
                    applied=True,
                    goal_id=goal_id,
                    kind="long_horizon",
                    reason=f"依赖关系更新: {len(deps)} 条",
                )
            return self.dependency_graph(goal_id)

    def dependency_graph(self, goal_id: str) -> Dict[str, Any]:
        """依赖关系图 (前置/后续/阻塞原因)"""
        with self._lock:
            goal = self._milestones.get(goal_id)
            if goal is None:
                raise LongHorizonPlannerError(f"长期目标不存在: {goal_id}")
            return self._graph.dependency_graph(goal)

    # ── 7. 状态管理 ───────────────────────────────────────────────
    def pause_goal(self, goal_id: str, reason: str = "") -> Dict[str, Any]:
        """暂停长期目标 (可恢复)"""
        with self._lock:
            goal = self._milestones.set_status(
                goal_id, "paused", reason=reason or "用户暂停",
            )
            self._record_status_audit(goal_id, "goal_pause", goal)
            return goal.to_dict()

    def resume_goal(self, goal_id: str, reason: str = "") -> Dict[str, Any]:
        """恢复长期目标"""
        with self._lock:
            goal = self._milestones.set_status(
                goal_id, "active", reason=reason or "用户恢复",
            )
            self._record_status_audit(goal_id, "goal_resume", goal)
            return goal.to_dict()

    def fail_goal(self, goal_id: str, reason: str = "") -> Dict[str, Any]:
        """标记长期目标失败 (可重试)"""
        with self._lock:
            goal = self._milestones.set_status(
                goal_id, "failed", reason=reason or "执行失败",
            )
            self._record_status_audit(goal_id, "goal_fail", goal)
            return goal.to_dict()

    def archive_goal(self, goal_id: str, reason: str = "") -> Dict[str, Any]:
        """归档长期目标"""
        with self._lock:
            goal = self._milestones.set_status(
                goal_id, "archived", reason=reason or "任务归档",
            )
            self._record_status_audit(goal_id, "goal_pause", goal)
            return goal.to_dict()

    def _record_status_audit(self, goal_id: str, action: str, goal: LongGoal) -> None:
        if self._audit is not None:
            self._audit.record(
                trigger=goal_id,
                action=action,
                applied=True,
                goal_id=goal_id,
                kind="long_horizon",
                reason=goal.explainable_reason,
            )

    # ── 8. 计划调整 ───────────────────────────────────────────────
    def adjust_plan(
        self,
        goal_id: str,
        trigger: str = "time_change",
        reason: str = "",
        record_audit: bool = True,
    ) -> Dict[str, Any]:
        """计划调整 (触发条件 → 方案, 禁止自动执行)"""
        with self._lock:
            goal = self._milestones.get(goal_id)
            if goal is None:
                raise LongHorizonPlannerError(f"长期目标不存在: {goal_id}")
            result = self._adjuster.adjust_plan(goal, trigger=trigger, reason=reason)
            if record_audit and self._audit is not None:
                self._audit.record(
                    trigger=goal_id,
                    action="plan_adjust",
                    applied=True,
                    goal_id=goal_id,
                    kind="long_horizon",
                    reason=f"计划调整 (触发: {trigger}): {reason}",
                )
            return result

    # ── 9. 风险预测 / 时间规划 / 快照 (P1) ────────────────────────
    def predict_risk(
        self,
        goal_id: str,
        failure_history: Optional[Dict[str, int]] = None,
    ) -> Dict[str, Any]:
        """风险预测 (历史失败经验 → low/medium/high)"""
        with self._lock:
            goal = self._milestones.get(goal_id)
            if goal is None:
                raise LongHorizonPlannerError(f"长期目标不存在: {goal_id}")
            return self._adjuster.predict_risk(goal, failure_history)

    def time_plan(self, goal_id: str) -> Dict[str, Any]:
        """时间规划 (deadline / estimated_duration / time_window)"""
        with self._lock:
            goal = self._milestones.get(goal_id)
            if goal is None:
                raise LongHorizonPlannerError(f"长期目标不存在: {goal_id}")
            return self._adjuster.time_plan(goal)

    def snapshot(self, goal_id: str) -> Dict[str, Any]:
        """Goal Snapshot (支持恢复)"""
        with self._lock:
            goal = self._milestones.get(goal_id)
            if goal is None:
                raise LongHorizonPlannerError(f"长期目标不存在: {goal_id}")
            return self._tracker.snapshot(goal)

    # ── 10. 与 V4.6 集成 (里程碑 → 跨目标规划) ────────────────────
    def plan_milestone_goals(
        self,
        goal_id: str,
        cross_goal_planner: Any = None,
    ) -> Dict[str, Any]:
        """里程碑 → V4.6 跨目标规划 (阶段内子规划)

        流程: Milestone → 子目标 (EmbodiedGoal) → Cross Goal Planner

        Returns:
            {
                'goal_id', 'milestone_plans': [
                    {'milestone_id', 'title', 'plan': CrossGoalPlan | None}, ...
                ],
            }
        """
        with self._lock:
            goal = self._milestones.get(goal_id)
            if goal is None:
                raise LongHorizonPlannerError(f"长期目标不存在: {goal_id}")
            out: List[Dict[str, Any]] = []
            for m in goal.milestones:
                sub_goals: List[EmbodiedGoal] = []
                for sg in m.sub_goals:
                    sub_goals.append(EmbodiedGoal.create(
                        description=sg.get("title", ""),
                        intent=sg.get("intent", ""),
                        scene="",
                    ))
                entry: Dict[str, Any] = {
                    "milestone_id": m.milestone_id,
                    "title": m.title,
                    "sub_goal_count": len(sub_goals),
                }
                if cross_goal_planner is not None and sub_goals:
                    try:
                        entry["plan"] = cross_goal_planner.plan(
                            sub_goals, record_audit=False,
                        )
                    except Exception as e:
                        entry["plan"] = None
                        entry["plan_error"] = str(e)
                else:
                    entry["plan"] = None
                out.append(entry)
            return {"goal_id": goal_id, "milestone_plans": out}

    # ── 11. Dry Run ───────────────────────────────────────────────
    def long_horizon_dry_run(
        self,
        title: str,
        description: str = "",
        phases: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """长期任务预演: 任务拆解 / 时间估计 / 风险点 / 依赖关系

        禁止: 执行任何动作 (纯模拟)

        Returns:
            {
                'dry_run': True,
                'goal': {...},          # 模拟拆解结果
                'task_breakdown': [...], # 任务拆解
                'time_estimate': {...},  # 时间估计
                'risk_points': [...],    # 风险点
                'dependencies': {...},   # 依赖关系
                'protection_checks': {...},
            }
        """
        with self._lock:
            # 模拟拆解 (不落地, 用临时对象)
            temp = LongGoal.create(title=title, description=description)
            phases = phases or self._infer_phases(title, description)
            for i, phase in enumerate(phases):
                temp.milestones.append(Milestone.create(
                    title=phase, goal_id=temp.goal_id, order=i,
                    estimated_duration=5.0,
                ))
            temp.status = "active"
            total_min = sum(m.estimated_duration for m in temp.milestones)
            risk = self._adjuster.predict_risk(temp)
            deps = self._graph.dependency_graph(temp)
            return {
                "dry_run": True,
                "goal": temp.to_dict(),
                "task_breakdown": self._task_tree(temp),
                "time_estimate": {
                    "estimated_total_minutes": total_min,
                    "per_milestone": [
                        {"title": m.title,
                         "estimated_duration": m.estimated_duration}
                        for m in temp.milestones
                    ],
                },
                "risk_points": risk,
                "dependencies": deps,
                "protection_checks": {
                    "checks": [
                        {"name": "no_execution", "passed": True,
                         "reason": "预演不执行任何动作"},
                        {"name": "no_memory_write", "passed": True,
                         "reason": "预演不写入 Agent Memory"},
                        {"name": "no_device_control", "passed": True,
                         "reason": "预演不控制任何设备"},
                        {"name": "rule_based_only", "passed": True,
                         "reason": "纯规则 + 状态机, 无黑盒优化"},
                    ],
                    "passed": True,
                },
            }

    @staticmethod
    def _infer_phases(title: str, description: str) -> List[str]:
        """推断阶段 (模板规则, 供 dry_run)"""
        text = (title + " " + description).lower()
        templates = (
            ("整理", ["收集物品", "分类", "整理", "检查", "维护"]),
            ("学习", ["基础阶段", "进阶阶段", "项目实践", "复习评估"]),
            ("巡逻", ["感知环境", "逐区检查", "记录报告", "维护反馈"]),
        )
        return next(
            (ph for kw, ph in templates if kw in text),
            ["准备", "执行", "检查", "收尾"],
        )

    # ── 状态 ──────────────────────────────────────────────────────
    def list_goals(self) -> List[Dict[str, Any]]:
        """全部长期目标 (简要)"""
        with self._lock:
            return [
                {
                    "goal_id": g.goal_id,
                    "title": g.title,
                    "status": g.status,
                    "progress": g.progress,
                    "milestone_count": len(g.milestones),
                    "priority": g.priority,
                }
                for g in self._milestones.all()
            ]

    def thresholds(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "min_goals_per_milestone": self._min_goals_per_milestone,
                "risk_failure_threshold": self._adjuster._risk_failure_threshold,
                "risk_blocked_threshold": self._adjuster._risk_blocked_threshold,
            }


__all__ = [
    "LongHorizonPlanner",
    "LongHorizonPlannerError",
]
