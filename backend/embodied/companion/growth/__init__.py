"""
YHLZ Embodied AI V6.0 - 成长层 (Growth Layer)

架构:
    GrowthTracker   (成长追踪: 事件采集 + 指标)
    GrowthMeaning   (成长意义: 发生了什么 → 意味着什么 → 影响未来)
    GrowthTrend     (成长趋势: 按天/周/月 + 增长量 + 加速/减速)
    GrowthReport    (成长报告: 经验/认知/创造/关系四维报告)

目标:
    不是"经验+100", 而是理解成长的意义与趋势
"""
from backend.embodied.companion.growth.growth_meaning import (
    GROWTH_EVENT_TYPES,
    MEANING_TEMPLATES,
    GrowthMeaning,
    MeaningError,
)
from backend.embodied.companion.growth.growth_report import (
    GrowthReport,
    ReportError,
)
from backend.embodied.companion.growth.growth_tracker import (
    GrowthTracker,
    TrackerError,
)
from backend.embodied.companion.growth.growth_trend import (
    BUCKET_SECONDS,
    TREND_BUCKETS,
    GrowthTrend,
    TrendError,
)
from backend.embodied.companion.growth.growth_proposal import (
    PROPOSAL_TYPES,
    GrowthProposal,
    ProposalError as GrowthProposalError,
)
from backend.embodied.companion.growth.growth_evaluator import (
    EvaluatorError as GrowthEvaluatorError,
    GrowthEvaluator,
    IMMUTABLE_FIELDS,
    SAFETY_KEYWORDS,
)
from backend.embodied.companion.growth.growth_applier import (
    ApplierError,
    GrowthApplier,
)
from backend.embodied.companion.growth.growth_audit import (
    GrowthAudit,
)
from backend.embodied.companion.growth.growth_cycle import (
    CYCLE_STATUS,
    CYCLE_TRIGGERS,
    CycleError,
    GrowthCycleEngine,
    PENDING_DECISIONS,
)
from backend.embodied.companion.growth.growth_trend_analysis import (
    ANALYSIS_PERIODS,
    GROWTH_WEIGHTS,
    GrowthTrendAnalysis,
    TREND_LEVELS,
    TrendAnalysisError,
)

__all__ = [
    "BUCKET_SECONDS",
    "GROWTH_EVENT_TYPES",
    "GrowthMeaning",
    "GrowthReport",
    "GrowthTracker",
    "GrowthTrend",
    "MEANING_TEMPLATES",
    "MeaningError",
    "ReportError",
    "TREND_BUCKETS",
    "TrackerError",
    "TrendError",
    "PROPOSAL_TYPES",
    "GrowthProposal",
    "GrowthProposalError",
    "GrowthEvaluator",
    "GrowthEvaluatorError",
    "IMMUTABLE_FIELDS",
    "SAFETY_KEYWORDS",
    "ApplierError",
    "GrowthApplier",
    "GrowthAudit",
    "CYCLE_STATUS",
    "CYCLE_TRIGGERS",
    "CycleError",
    "GrowthCycleEngine",
    "PENDING_DECISIONS",
    "ANALYSIS_PERIODS",
    "GROWTH_WEIGHTS",
    "GrowthTrendAnalysis",
    "TREND_LEVELS",
    "TrendAnalysisError",
]
