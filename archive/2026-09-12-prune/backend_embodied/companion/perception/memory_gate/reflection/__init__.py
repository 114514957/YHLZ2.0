"""
YHLZ Embodied AI V6.4 - 反思评估层 (Reflection Evaluation Layer)

架构:
    ReflectionEvaluator  (反思评估器: Advisor)
        ├── ReflectionRules    (5 维规则: 可信度/一致性/价值/身份/风险)
        ├── CounterfactualCheck (反事实验证: 降低幻觉)
        └── ReflectionAudit    (反思审计)

原则:
    - Reflection 不是决策者: 只提供分析/评分/风险提示/价值建议
    - Memory Gate 是 Authority (唯一写入决策者)
"""
from backend.embodied.companion.perception.memory_gate.reflection.counterfactual_check import (
    HIGH_STAKE_KEYWORDS,
    CounterfactualCheck,
    CounterfactualError,
)
from backend.embodied.companion.perception.memory_gate.reflection.reflection_audit import (
    AuditError,
    REFLECTION_AUDIT_ACTIONS,
    ReflectionAudit,
)
from backend.embodied.companion.perception.memory_gate.reflection.reflection_evaluator import (
    EvaluatorError,
    ReflectionEvaluator,
)
from backend.embodied.companion.perception.memory_gate.reflection.reflection_rules import (
    CONTRADICTION_KEYWORDS,
    IDENTITY_KEYWORDS,
    RISK_KEYWORDS,
    ReflectionRules,
    ReflectionRulesError,
    VALUE_KEYWORDS,
)

__all__ = [
    "AuditError",
    "CONTRADICTION_KEYWORDS",
    "CounterfactualCheck",
    "CounterfactualError",
    "EvaluatorError",
    "HIGH_STAKE_KEYWORDS",
    "IDENTITY_KEYWORDS",
    "REFLECTION_AUDIT_ACTIONS",
    "RISK_KEYWORDS",
    "ReflectionAudit",
    "ReflectionEvaluator",
    "ReflectionRules",
    "ReflectionRulesError",
    "VALUE_KEYWORDS",
]
