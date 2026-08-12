"""
YHLZ Embodied AI V5.8 - 反思层 (Reflection Layer)

架构:
    ReflectionEngine       (反思引擎: 经历 → Reflection Report)
        ├── PatternDiscovery        (模式发现: 跨经历规律)
        ├── FailureAnalysisEngine   (失败分析: 原因/证据/建议)
        ├── ImprovementProposalEngine (改进建议: Proposal ≠ Action)
        └── ReflectionAudit         (反思审计)

流程:
    Experience → Verification → Validated Experience → Reflection
    → Improvement Proposal → Approval → Execution

Reflection Report:
    {observation, evidence[], pattern, risk, suggestion, confidence}
"""
from backend.embodied.companion.reflection.failure_analysis import (
    FAILURE_REASONS,
    FAILURE_SIGNALS,
    FailureAnalysisEngine,
    FailureError,
)
from backend.embodied.companion.reflection.improvement_proposal import (
    ImprovementProposalEngine,
    ProposalError,
)
from backend.embodied.companion.reflection.pattern_discovery import (
    PatternDiscovery,
    PatternError,
)
from backend.embodied.companion.reflection.reflection_audit import (
    REFLECTION_AUDIT_ACTIONS,
    ReflectionAudit,
    ReflectionAuditError,
)
from backend.embodied.companion.reflection.reflection_engine import (
    ReflectionEngine,
    ReflectionError,
)
from backend.embodied.companion.reflection.cognitive_reflection import (
    CognitiveReflectionEngine,
    ReflectionError as CognitiveReflectionError,
)
from backend.embodied.companion.reflection.contradiction_detector import (
    CONTRADICTION_TYPES,
    CognitiveContradictionDetector,
    ContradictionError as CognitiveContradictionError,
)
from backend.embodied.companion.reflection.pattern_analyzer import (
    PATTERN_TYPES,
    PatternAnalyzer,
    PatternError as PatternAnalyzerError,
)
from backend.embodied.companion.reflection.reflection_report import (
    ReflectionReport,
    ReportError,
)
from backend.embodied.companion.reflection.reflection_emotion import (
    CONTRADICTION_RISK,
    EMOTION_STATES,
    MEANING_BY_PATTERN,
    REFLECTION_EMOTION_CONTEXTS,
    RISK_LEVELS,
    ReflectionEmotionError,
    ReflectionEmotionIntegrator,
)

__all__ = [
    "FAILURE_REASONS",
    "FAILURE_SIGNALS",
    "FailureAnalysisEngine",
    "FailureError",
    "ImprovementProposalEngine",
    "PatternDiscovery",
    "PatternError",
    "ProposalError",
    "REFLECTION_AUDIT_ACTIONS",
    "ReflectionAudit",
    "ReflectionAuditError",
    "ReflectionEngine",
    "ReflectionError",
    "CognitiveReflectionEngine",
    "CognitiveReflectionError",
    "CONTRADICTION_TYPES",
    "CognitiveContradictionDetector",
    "CognitiveContradictionError",
    "PATTERN_TYPES",
    "PatternAnalyzer",
    "PatternAnalyzerError",
    "ReflectionReport",
    "ReportError",
    "CONTRADICTION_RISK",
    "EMOTION_STATES",
    "MEANING_BY_PATTERN",
    "REFLECTION_EMOTION_CONTEXTS",
    "RISK_LEVELS",
    "ReflectionEmotionError",
    "ReflectionEmotionIntegrator",
]
