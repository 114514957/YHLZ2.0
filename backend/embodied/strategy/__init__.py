"""
YHLZ Embodied AI V4.4 - 自适应策略层 (Adaptive Strategy Layer)

架构:
    trigger → scene → goal_type → policy candidates → quality ranking → best strategy
    ↓ 生命周期管理 (active / degraded / stale / archived)
    ↓ 决策审计 (Policy Audit Log)
    ↓ 趋势统计 (Trend Stats, 数据源 GoalTraceStore)

约束 (必须保持):
    - 纯规则 + 统计 + 阈值 + 可解释排序, 禁止神经网络训练 / 梯度更新 / 黑盒优化
    - 策略只能影响建议与规划模板, 不能绕过 Permission Layer
    - 审计 / 趋势数据独立存储, 绝不写入 Agent Memory
"""
from backend.embodied.strategy.audit import (
    AUDIT_ACTIONS,
    PolicyAuditError,
    PolicyAuditLog,
)
from backend.embodied.strategy.ranker import PolicyRanker, PolicyRankerError
from backend.embodied.strategy.trends import (
    GOAL_TYPES,
    TrendStats,
    TrendStatsError,
    infer_goal_type,
)

__all__ = [
    "AUDIT_ACTIONS",
    "GOAL_TYPES",
    "PolicyAuditError",
    "PolicyAuditLog",
    "PolicyRanker",
    "PolicyRankerError",
    "TrendStats",
    "TrendStatsError",
    "infer_goal_type",
]
