"""
YHLZ Embodied AI V4.7 - 规划模块 (Planning: Cross-Goal + Long Horizon)

架构:
    CrossGoalPlanner (门面, V4.6 跨目标规划)
        ├── GoalDependencyAnalyzer (目标分组 / 共享步骤 / 信息复用)
        └── BudgetAllocator        (步骤预算分配 / 冲突检测)

    LongHorizonPlanner (门面, V4.7 长期任务规划)
        ├── MilestoneManager        (LongGoal / Milestone 生命周期 / 目标分解)
        ├── DependencyGraph         (依赖关系 / 阻塞 / 拓扑顺序)
        ├── ProgressTracker         (进度跟踪 / 报告 / 快照恢复)
        └── PlanAdjuster            (计划调整 / 风险预测 / 时间规划)

功能:
    - cross_goal_plan(goals, budget): 跨目标战略规划主入口
    - analyze_groups / shared_steps / allocate_budget / detect_conflict
    - create_long_goal / decompose_goal / generate_milestones
    - track_progress / progress_report / adjust_plan / dependency_graph
    - complete_milestone / rollback_milestone / pause / resume / fail
    - predict_risk / time_plan / snapshot / long_horizon_dry_run

约束 (必须保持):
    - 纯规则 + 统计 + 阈值 + 状态机, 禁止神经网络训练 / 黑盒优化
    - 规划只输出方案: 不修改策略表, 不绕过 Permission Layer
    - 规划动作只影响: 审计日志 → 规划结果 (不写 Agent Memory)
    - 允许读取 Experience Memory (历史参考), 禁止修改
    - 线程安全 (RLock)
"""
from backend.embodied.planning.adjustment import (
    ADJUSTMENT_TRIGGERS,
    AdjustmentError,
    PlanAdjuster,
    RISK_LEVELS,
)
from backend.embodied.planning.budget import (
    BudgetAllocator,
    BudgetError,
    DEFAULT_STEPS_BY_ACTION,
    PRIORITY_WEIGHTS,
)
from backend.embodied.planning.cross_goal import (
    CrossGoalError,
    CrossGoalPlanner,
    GROUP_PRIORITY_ORDER,
)
from backend.embodied.planning.dependency import (
    DependencyError,
    GoalDependencyAnalyzer,
    SHARABLE_ACTION_TYPES,
    infer_goal_type_of,
    plan_action_sequence,
)
from backend.embodied.planning.dependency_graph import (
    DependencyGraph,
    DependencyGraphError,
)
from backend.embodied.planning.long_horizon import (
    LongHorizonPlanner,
    LongHorizonPlannerError,
)
from backend.embodied.planning.milestone import (
    LONG_GOAL_STATUSES,
    MILESTONE_STATUSES,
    MILESTONE_TRANSITIONS,
    LongGoal,
    LongHorizonError,
    Milestone,
    MilestoneManager,
)
from backend.embodied.planning.progress_tracker import (
    ProgressError,
    ProgressTracker,
)

__all__ = [
    "ADJUSTMENT_TRIGGERS",
    "AdjustmentError",
    "BudgetAllocator",
    "BudgetError",
    "CrossGoalError",
    "CrossGoalPlanner",
    "DEFAULT_STEPS_BY_ACTION",
    "DependencyError",
    "DependencyGraph",
    "DependencyGraphError",
    "GROUP_PRIORITY_ORDER",
    "GoalDependencyAnalyzer",
    "LONG_GOAL_STATUSES",
    "LongGoal",
    "LongHorizonError",
    "LongHorizonPlanner",
    "LongHorizonPlannerError",
    "MILESTONE_STATUSES",
    "MILESTONE_TRANSITIONS",
    "Milestone",
    "MilestoneManager",
    "PRIORITY_WEIGHTS",
    "PlanAdjuster",
    "ProgressError",
    "ProgressTracker",
    "RISK_LEVELS",
    "SHARABLE_ACTION_TYPES",
    "infer_goal_type_of",
    "plan_action_sequence",
]
