"""
YHLZ Embodied AI V4.2 - 环境推理包 (Environment Reasoning Layer)

架构:
    EnvironmentEventLog (事件时间线: 过去发生了什么)
        ↓
    CausalAnalyzer (因果分析: 为什么发生 / 为什么失败)
        ↓
    InvariantChecker (状态不变式: 什么不应该发生)
        ↓
    SemanticAnalyzer (语义环境: 事件理解 → 语义摘要)

设计原则:
    - 规则驱动, 禁止 AI 训练式预测
    - 只推理不执行: 推理结果必须经 Permission → Executor 才能落地
    - 数据独立存储 (绝不写入 Agent Memory / Vision Memory)
"""

from backend.embodied.reasoning.cause import (
    CAUSE_REMEDY_RULES,
    CausalAnalyzer,
    CausalAnalyzerError,
)
from backend.embodied.reasoning.event_log import (
    EnvironmentEventLog,
    EnvironmentEventLogError,
)
from backend.embodied.reasoning.invariants import (
    DEFAULT_INVARIANT_RULES,
    InvariantChecker,
    InvariantError,
)
from backend.embodied.reasoning.semantics import (
    SemanticAnalyzer,
    SemanticError,
)

__all__ = [
    "CausalAnalyzer",
    "CausalAnalyzerError",
    "EnvironmentEventLog",
    "EnvironmentEventLogError",
    "InvariantChecker",
    "InvariantError",
    "SemanticAnalyzer",
    "SemanticError",
    "CAUSE_REMEDY_RULES",
    "DEFAULT_INVARIANT_RULES",
]
