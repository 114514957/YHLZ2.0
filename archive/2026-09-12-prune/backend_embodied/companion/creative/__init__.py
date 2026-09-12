"""
YHLZ Embodied AI V5.9 - 创造智能层 (Creative Intelligence Layer)

架构:
    CreativeEngine (创造引擎门面, Service 唯一接入点)
        ├── OpportunityDetector        (机会检测: 可靠经验 → 机会)
        ├── ValueEvaluator             (价值评估: 机会 → 决策)
        ├── CreativeReasoningEngine    (创造推理: 当前 → 理想 → 路径)
        ├── ProposalGenerator          (方案生成: 机会+推理+评估 → 方案)
        ├── SimulationEngine           (模拟引擎: 执行前模拟)
        ├── ProposalMemory             (方案记忆: 生命周期 + 持久化)
        └── CreativeAudit              (创造审计: 全程可回溯)

流程:
    Confirmed Experience + Reflection
    → Opportunity Discovery → Value Evaluation → Creative Proposal
    → Simulation → Approval → Execution → New Experience
"""
from backend.embodied.companion.creative.creative_audit import (
    CREATIVE_AUDIT_ACTIONS,
    CreativeAudit,
    CreativeAuditError,
)
from backend.embodied.companion.creative.creative_engine import (
    CreativeEngine,
    CreativeEngineError,
)
from backend.embodied.companion.creative.creative_reasoning_engine import (
    PATH_KEYWORDS,
    PATH_TYPES,
    CreativeReasoningEngine,
    ReasoningError,
)
from backend.embodied.companion.creative.opportunity_detector import (
    OPPORTUNITY_SOURCE_TYPES,
    OpportunityDetector,
    OpportunityError,
)
from backend.embodied.companion.creative.proposal_generator import (
    ProposalGenerationError,
    ProposalGenerator,
)
from backend.embodied.companion.creative.proposal_memory import (
    PROPOSAL_STATUSES,
    PROPOSAL_TRANSITIONS,
    MemoryError,
    ProposalMemory,
)
from backend.embodied.companion.creative.simulation_engine import (
    RECOMMENDATIONS,
    SIDE_EFFECT_KEYWORDS,
    SimulationEngine,
    SimulationError,
)
from backend.embodied.companion.creative.value_evaluator import (
    DECISIONS,
    SOURCE_IMPACT_BONUS,
    VALUE_WEIGHTS,
    EvaluationError,
    ValueEvaluator,
)

__all__ = [
    "CREATIVE_AUDIT_ACTIONS",
    "CreativeAudit",
    "CreativeAuditError",
    "CreativeEngine",
    "CreativeEngineError",
    "CreativeReasoningEngine",
    "DECISIONS",
    "EvaluationError",
    "MemoryError",
    "OPPORTUNITY_SOURCE_TYPES",
    "OpportunityDetector",
    "OpportunityError",
    "PATH_KEYWORDS",
    "PATH_TYPES",
    "PROPOSAL_STATUSES",
    "PROPOSAL_TRANSITIONS",
    "ProposalGenerationError",
    "ProposalGenerator",
    "ProposalMemory",
    "RECOMMENDATIONS",
    "ReasoningError",
    "SIDE_EFFECT_KEYWORDS",
    "SOURCE_IMPACT_BONUS",
    "SimulationEngine",
    "SimulationError",
    "VALUE_WEIGHTS",
    "ValueEvaluator",
]
