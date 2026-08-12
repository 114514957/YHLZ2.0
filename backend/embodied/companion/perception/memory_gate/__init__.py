"""
YHLZ Embodied AI V6.3 - 记忆网关 (Memory Gate Layer)

架构:
    MemoryGate          (记忆网关: 候选 → 批准 → 经历)
        ├── CandidateValidator  (候选校验: 必填字段/值域/长度)
        └── ApprovalRule        (批准规则: 来源/重复/价值/身份/风险)

流程:
    Memory Candidate → Candidate Validator → Reflection Check
    → Approval → Experience Memory

原则:
    - 记忆必须经过批准 (感知不能直接成为经历)
"""
from backend.embodied.companion.perception.memory_gate.approval_rule import (
    IDENTITY_KEYWORDS,
    RISK_KEYWORDS,
    TRUSTED_SOURCES,
    VALUE_KEYWORDS,
    ApprovalRule,
    ApprovalRuleError,
)
from backend.embodied.companion.perception.memory_gate.candidate_validator import (
    REQUIRED_CANDIDATE_FIELDS,
    CandidateValidator,
    ValidatorError,
)
from backend.embodied.companion.perception.memory_gate.memory_gate import (
    MemoryGate,
    MemoryGateError,
)
from backend.embodied.companion.perception.memory_gate.reflection import (
    CONTRADICTION_KEYWORDS,
    CounterfactualCheck,
    CounterfactualError,
    EvaluatorError,
    HIGH_STAKE_KEYWORDS,
    REFLECTION_AUDIT_ACTIONS,
    ReflectionAudit,
    ReflectionEvaluator,
    ReflectionRules,
    ReflectionRulesError,
)

__all__ = [
    "ApprovalRule",
    "ApprovalRuleError",
    "CandidateValidator",
    "IDENTITY_KEYWORDS",
    "MemoryGate",
    "MemoryGateError",
    "REQUIRED_CANDIDATE_FIELDS",
    "RISK_KEYWORDS",
    "TRUSTED_SOURCES",
    "VALUE_KEYWORDS",
    "ValidatorError",
    "CONTRADICTION_KEYWORDS",
    "CounterfactualCheck",
    "CounterfactualError",
    "EvaluatorError",
    "HIGH_STAKE_KEYWORDS",
    "REFLECTION_AUDIT_ACTIONS",
    "ReflectionAudit",
    "ReflectionEvaluator",
    "ReflectionRules",
    "ReflectionRulesError",
]
