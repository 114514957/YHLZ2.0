"""
YHLZ Embodied AI V5.5 - 自适应伙伴架构 (Adaptive Companion Architecture)

架构:
    MainCompanionAgent (主伙伴 Agent: 统一入口 / 统一人格 / 统一决策中心)
        ├── CompanionRouter     (内部路由: 意图 → 专业 Agent, 加权打分 + Top-K)
        ├── TaskDelegator       (委派: 并发线程池 + 超时 + 管道感知 + 结果汇总)
        ├── AgentPipeline       (Agent 数据管道: 前序输出 → 后序输入)
        ├── ExecutionCoordinator (执行协调器: 规划 → 执行 → 反馈 → 闭环)
        ├── SelfCorrector       (自我修正器: 失败 → 规则调整 → 再执行)
        ├── CompanionLearning   (学习器: 失败/成功模式 → 规则表)
        ├── AdaptivePersonalityEngine (自适应人格引擎: 核心稳定 + 表现自适应)
        ├── CompanionStats      (协同统计: 组合/耗时/成功率)
        └── SpecialistRegistry  (专业 Agent 注册中心)

专业 Agent 能力域 (对接 Embodied 既有模块):
    - perception_agent:    感知 (observe / get_state / list_environments)
    - reasoning_agent:     推理 (build_environment_context / get_events /
                              analyze_cause / predict)
    - experience_agent:    经验 (policy_stats / experience_summary / trend_stats,
                              可接收管道 env_state 输入)
    - planning_agent:      规划 (cross_goal_plan / strategy_system_overview /
                              cross_goal_groups, 可接收管道策略建议)
    - long_horizon_agent:  长期任务 (long_horizon_plan / track_progress /
                              long_horizon_report / snapshot)
    - governance_agent:    治理 (policy_health_check / scene_coverage /
                              strategy_system_report)
    - execution_agent:     执行 (run_goal / execute_action, 经 Permission)

感知-策略闭环管道 (V5.2):
    perception → experience → planning
    (环境状态 → 策略建议 → 规划输入)

执行闭环管道 (V5.3):
    perception → experience → planning → execution → feedback

自我修正与学习 (V5.4):
    执行失败 → 规则调整 (修正策略表) → 再执行 (上限内)
    失败/成功模式 → 学习规则表 (阈值提升)

身份与自适应人格 (V5.5):
    核心人格稳定 (base 不可修改) + 表现人格自适应 (维度规则调整)
    情境: success/failure/consecutive_fail/casual_chat/serious_task
    互动统计 (只存数字) + 人格审计 (每次调整记录)

约束 (必须保持):
    - 一个人格 / 一个核心意识 / 一个决策中心 (专业 Agent 无独立人格)
    - 纯规则 + 确定性路由: 禁止神经网络训练 / 黑盒优化 / 自由协商
    - 不绕过 Permission Layer (执行必须经 Permission) / 不写 Agent Memory
    - 内部单进程多 Agent (禁止分布式)
    - 线程安全 (RLock)
"""
from typing import Any, Dict, List

from backend.embodied.companion.correction import (
    CORRECTION_RULES,
    CorrectionError,
    SelfCorrector,
)
from backend.embodied.companion.delegate import DelegateError, TaskDelegator
from backend.embodied.companion.executor import (
    ExecutionCoordinator,
    ExecutorError,
)
from backend.embodied.companion.learning import (
    CompanionLearning,
    LearningError,
)
from backend.embodied.companion.main_agent import (
    MainAgentError,
    MainCompanionAgent,
)
from backend.embodied.companion.personality import (
    AdaptivePersonalityEngine,
    PersonalityAuditRecord,
    PersonalityError,
    PersonalityState,
    get_personality_service,
    reset_personality_service,
)
from backend.embodied.companion.personality_rules import (
    BASE_DIMENSIONS,
    PERSONALITY_CONTEXTS,
    PERSONALITY_DIMENSIONS,
    PERSONALITY_RULES,
    PersonalityRuleError,
    adjustment_reason,
    apply_adjustment,
    rule_for,
)
from backend.embodied.companion.personality_decay import (
    DecayError,
    PersonalityDecayPolicy,
)
from backend.embodied.companion.interaction_window import (
    DEFAULT_WINDOW_DAYS,
    InteractionWindow,
    WindowError,
)
from backend.embodied.companion.relationship import (
    COMMUNICATION_STYLES,
    FAMILIARITY_STEP,
    RelationshipError,
    RelationshipManager,
    RelationshipState,
    STAGE_THRESHOLDS,
    TRUST_STEP,
)
from backend.embodied.companion.pipeline import (
    AgentPipeline,
    DEFAULT_PIPELINE,
    LOOP_PIPELINE,
    PipelineError,
)
from backend.embodied.companion.router import (
    CompanionRouter,
    DEFAULT_KEYWORD_WEIGHT,
    DEFAULT_ROUTE_TOP_K,
    FALLBACK_CAPABILITIES,
    INTENT_KEYWORDS,
    KEYWORD_WEIGHTS,
    ROUTE_RULE_VERSION,
    RouterError,
)
from backend.embodied.companion.specialist import (
    SPECIALIST_CAPABILITIES,
    SpecialistAgent,
    SpecialistError,
    SpecialistRegistry,
)
from backend.embodied.companion.stats import CompanionStats, StatsError
from backend.embodied.companion.experience import (
    AUDIT_ACTIONS_EXP,
    AuditError,
    EXPERIENCE_TYPES,
    ExperienceAudit,
    ExperienceError,
    ExperienceExtractor,
    ExperienceManager,
    ExperienceManagerError,
    ExperienceQuery,
    ExperienceQueryError,
    ExperienceRecord,
    ExperienceStore,
    ExperienceStoreError,
    ExtractorError,
    VALUE_HIGH,
    VALUE_LOW,
    VALUE_MEDIUM,
)
from backend.embodied.companion.reflection import (
    FAILURE_REASONS,
    FAILURE_SIGNALS,
    FailureAnalysisEngine,
    FailureError,
    ImprovementProposalEngine,
    PatternDiscovery,
    PatternError,
    ProposalError,
    REFLECTION_AUDIT_ACTIONS,
    ReflectionAudit,
    ReflectionAuditError,
    ReflectionEngine,
    ReflectionError,
)
from backend.embodied.companion.verification import (
    ConfidenceEngine,
    ConfidenceError,
    ContradictionDetector,
    ContradictionError,
    EvidenceError,
    EvidenceManager,
    ExperienceVerifier,
    RealityCheck,
    RealityError,
    VERIFICATION_STATUSES,
    VERIFICATION_TRANSITIONS,
    VerificationState,
    VerifierError,
)
from backend.embodied.companion.creative import (
    CREATIVE_AUDIT_ACTIONS,
    CreativeAudit,
    CreativeAuditError,
    CreativeEngine,
    CreativeEngineError,
    CreativeReasoningEngine,
    DECISIONS,
    EvaluationError,
    MemoryError,
    OPPORTUNITY_SOURCE_TYPES,
    OpportunityDetector,
    OpportunityError,
    PATH_KEYWORDS,
    PATH_TYPES,
    PROPOSAL_STATUSES,
    PROPOSAL_TRANSITIONS,
    ProposalGenerationError,
    ProposalGenerator,
    ProposalMemory,
    RECOMMENDATIONS,
    ReasoningError,
    SIDE_EFFECT_KEYWORDS,
    SOURCE_IMPACT_BONUS,
    SimulationEngine,
    SimulationError,
    VALUE_WEIGHTS,
    ValueEvaluator,
)
from backend.embodied.companion.integration import (
    ApprovalBridge,
    ApprovalBridgeError,
    ExperienceBridge,
    ExperienceBridgeError,
    ReflectionBridge,
    ReflectionBridgeError,
)
from backend.embodied.companion.persistence import (
    CompanionSnapshot,
    JSONLStorage,
    PERSISTENCE_AUDIT_ACTIONS,
    PersistenceAudit,
    PersistenceAuditError,
    REQUIRED_FIELDS,
    RESTORE_STEPS,
    RestoreError,
    RestoreManager,
    SNAPSHOT_DOMAINS,
    SnapshotError,
    StorageError,
)
from backend.embodied.companion.memory import (
    CONSOLIDATION_TRANSITIONS,
    CREATIVE_KEYWORDS,
    ConsolidationError,
    IDENTITY_KEYWORDS,
    ImportanceError,
    IndexError,
    MEMORY_STAGES,
    MEMORY_TYPES,
    MemoryConsolidation,
    MemoryImportance,
    MemoryIndex,
    RELATIONSHIP_KEYWORDS,
)
from backend.embodied.companion.identity_history import (
    APPROVAL_STATUSES,
    DiffError,
    IDENTITY_AUDIT_ACTIONS,
    IMMUTABLE_FIELDS,
    IdentityAudit,
    IdentityAuditError,
    IdentityDiff,
    IdentitySnapshot,
    IdentitySnapshotError,
    NOISE_FIELDS,
)
from backend.embodied.companion.growth import (
    BUCKET_SECONDS,
    GROWTH_EVENT_TYPES,
    GrowthMeaning,
    GrowthReport,
    GrowthTracker,
    GrowthTrend,
    MEANING_TEMPLATES,
    MeaningError,
    ReportError,
    TREND_BUCKETS,
    TrackerError,
    TrendError,
)
from backend.embodied.companion.emotion import (
    EMOTION_AUDIT_ACTIONS,
    EMOTION_BASELINE,
    EMOTION_CONTEXTS,
    EMOTION_DIMENSIONS,
    EMOTION_RULES,
    EmotionAudit,
    EmotionDecay,
    EmotionEngine,
    EmotionEngineError,
    EmotionError,
    EmotionMemory,
    EmotionState,
    RulesError,
)
from backend.embodied.companion.rhythm import (
    ConsolidationScheduler,
    GrowthRhythm,
    GrowthTrigger,
    RHYTHM_AUDIT_ACTIONS,
    RhythmAudit,
    RhythmAuditError,
    RhythmError,
    SchedulerError,
    TRIGGER_CONDITIONS,
    TriggerError,
)
from backend.embodied.companion.expression import (
    EXPRESSION_AUDIT_ACTIONS,
    EXPRESSION_RULES,
    EXPRESSION_STYLES,
    EXPRESSION_TONES,
    ExpressionContext,
    ExpressionEngine,
    ExpressionEngineError,
    ExpressionRules,
    RulesError,
)
from backend.embodied.companion.perception import (
    CameraAdapter,
    DetectionMockAdapter,
    DetectionResult,
    ManagerError,
    OCRMockAdapter,
    OCRResult,
    PERCEPTION_AUDIT_ACTIONS,
    PERCEPTION_KINDS,
    PERCEPTION_SOURCES,
    PERCEPTION_TYPES,
    PerceptionAdapter,
    PerceptionAdapterError,
    PerceptionAudit,
    PerceptionEvent,
    PerceptionManager,
    PerceptionPermission,
    PerceptionService,
    PerceptionServiceError,
    PerceptionVerifier,
    PermissionError,
    SchemaError,
    VerificationError,
    VisionMockAdapter,
)
from backend.embodied.companion.identity import (
    ChangeValidator,
    GuardError,
    IdentityGuard,
    PROTECTED_FIELDS,
    ValidatorError,
)
from backend.embodied.companion.reflection import (
    CognitiveContradictionDetector,
    CognitiveReflectionEngine,
    CognitiveReflectionError,
    CONTRADICTION_TYPES,
    CognitiveContradictionError,
    PATTERN_TYPES,
    PatternAnalyzer,
    PatternAnalyzerError,
    ReflectionReport,
    ReportError,
    ReflectionEmotionError,
    ReflectionEmotionIntegrator,
)
from backend.embodied.companion.growth import (
    ApplierError,
    GrowthApplier,
    GrowthAudit,
    GrowthEvaluator,
    GrowthEvaluatorError,
    GrowthProposal,
    GrowthProposalError,
    IMMUTABLE_FIELDS,
    PROPOSAL_TYPES,
    SAFETY_KEYWORDS,
    CycleError,
    GrowthCycleEngine,
    GrowthTrendAnalysis,
    TrendAnalysisError,
)
from backend.embodied.companion.continuity_engine import (
    ContinuityEngine,
    ContinuityError,
)
from backend.embodied.companion.hybrid import (
    ApiGateway,
    Capability,
    CapabilityMatcher,
    CloudProvider,
    CostPolicy,
    HybridError,
    HybridIntelligenceLayer,
    InferenceAudit,
    LocalCapability,
    LocalProvider,
    ModelEndpoint,
    PrivacyPolicy,
    ResultValidator,
    RoutingEngine,
    RoutingPolicy,
    TaskClassifier,
)
from backend.embodied.companion.embodied_presence import (
    PRESENCE_OUTPUT_FIELDS,
    PRESENCE_PROTECTED_FIELDS,
    PresenceEngine,
    PresenceEngineError,
    PresenceMapper,
    PresenceMapperError,
    PresenceMemory,
    PresenceMemoryError,
    PresenceState,
    PresenceStateError,
)
from backend.embodied.companion.constitution import (
    ConstitutionEngine,
    ConstitutionError,
    ConstitutionLedger,
    ConstitutionValidator,
    EvolutionProposal,
    GrowthPolicy,
    IdentityRules,
    IntelligencePolicy,
    LedgerError,
    Principles,
    RuleEngine,
    SafetyPolicy,
)
from backend.embodied.companion.creative_intelligence import (
    CollaborativeCreation,
    CollaborativeError,
    ConceptFusion,
    CreativeMemory,
    CreativeMemoryError,
    CreativeValidation,
    FusionError,
    HypothesisEngine,
    HypothesisError,
    IdeaSparkGenerator,
    KnowledgeGraph,
    KnowledgeGraphError,
    MEMORY_STATUS,
    MetaCreativeEngine,
    MetaCreativeError,
    SparkError,
    ThoughtBoundaryDetector,
    ValidationError,
)
from backend.embodied.companion.research_engine import (
    HypothesisLoop,
    KnowledgeAcquisition,
    ObservationLayer,
    QuestionDiscoveryEngine,
    RealityValidation,
    ResearchAudit,
    ResearchEngine,
    ResearchMemory,
    ResearchPlanner,
)
from backend.embodied.companion.meta_cognition import (
    CognitionAudit,
    CognitionMemory,
    CognitiveMonitor,
    ErrorPatternDetector,
    MetaCognitionEngine,
    ReflectionLoop,
    ReasoningEvaluator,
    SelfVerification,
)
from backend.embodied.schema import EmbodiedGoal


def build_default_agents(svc) -> SpecialistRegistry:
    """构建默认专业 Agent (对接 EmbodiedService 能力, V5.1 细化映射)

    Args:
        svc: EmbodiedService 实例

    Returns:
        SpecialistRegistry (已注册 6 个能力域 Agent, 精确对接方法)
    """
    registry = SpecialistRegistry()

    def make_handler(callable_name: str, default_payload: Dict[str, Any],
                     payload_keys: List[str] = None,
                     fallback_name: str = None):
        """构造处理器: 调用 svc 方法 + 请求参数白名单

        Args:
            callable_name: 首选 Service 方法
            default_payload: 默认参数
            payload_keys: 请求参数白名单 (None=用 default_payload 键)
            fallback_name: 无任何白名单参数时的回退方法 (None=无)
        """
        keys = payload_keys if payload_keys is not None \
            else list(default_payload.keys())

        def handler(request: Dict[str, Any]) -> Dict[str, Any]:
            fn = getattr(svc, callable_name, None)
            if fn is None:
                return {"error": f"Service 方法不存在: {callable_name}"}
            kwargs: Dict[str, Any] = {}
            for key in keys:
                if key in request:
                    kwargs[key] = request[key]
            # 无任何白名单参数 → 回退方法 (V5.2: 保证能力可用性)
            if not kwargs and fallback_name:
                fb = getattr(svc, fallback_name, None)
                if fb is not None:
                    try:
                        return {"data": fb(), "method": fallback_name,
                                "fallback_reason": "请求无该方法参数"}
                    except Exception as e:
                        return {"error": str(e), "method": fallback_name}
            try:
                return {"data": fn(**kwargs), "method": callable_name}
            except TypeError:
                # 参数不被方法接受 → 无参重试 (V5.2: 管道输入兼容)
                try:
                    return {"data": fn(), "method": callable_name,
                            "pipeline_input_ignored": list(kwargs.keys())}
                except Exception as e:
                    return {"error": str(e), "method": callable_name}
            except Exception as e:
                return {"error": str(e), "method": callable_name}
        return handler

    # 感知: 观察 / 状态 / 环境列表
    registry.register_simple(
        name="perception_agent",
        capability="perception",
        handler=make_handler("observe", {"environment": None},
                             payload_keys=["environment"]),
        description="感知: 观察环境 / 世界状态 / 场景",
    )
    # 推理: 上下文 / 事件 / 因果 / 预测
    registry.register_simple(
        name="reasoning_agent",
        capability="reasoning",
        handler=make_handler("build_environment_context", {},
                             payload_keys=["environment",
                                           "include_history", "event_limit"]),
        description="推理: 上下文 / 事件时间线 / 因果 / 预测",
    )
    # 经验: 策略统计 / 经验摘要 / 趋势 (V5.2: 可接收管道 env_state)
    registry.register_simple(
        name="experience_agent",
        capability="experience",
        handler=make_handler("policy_stats", {},
                             payload_keys=["env_state"]),
        description="经验: 策略表统计 / 经验摘要 / 趋势 (可接收环境状态)",
    )
    # 规划: 跨目标规划 / 体系总览 (V5.2: 可接收管道策略建议)
    registry.register_simple(
        name="planning_agent",
        capability="planning",
        handler=make_handler("strategy_system_overview", {},
                             payload_keys=["strategy_suggestions"]),
        description="规划: 跨目标规划 / 策略体系总览 (可接收策略建议)",
    )
    # 长期任务: 规划 / 进度 / 报告 / 快照 (V5.1 细化: 优先精确方法)
    registry.register_simple(
        name="long_horizon_agent",
        capability="long_horizon",
        handler=make_handler("long_horizon_plan",
                             {"title": "", "phases": None},
                             payload_keys=["title", "description", "phases"],
                             fallback_name="report"),
        description="长期任务: 长期目标规划 / 里程碑 / 进度 / 快照",
    )
    # 治理: 健康 / 覆盖 / 报告
    registry.register_simple(
        name="governance_agent",
        capability="governance",
        handler=make_handler("policy_health_check", {}),
        description="治理: 策略健康 / 场景覆盖 / 冗余 / 冲突",
    )
    # 执行: 目标执行 (V5.3, 经 Permission; 需经 ExecutionCoordinator 包装)
    def execution_handler(request: Dict[str, Any]) -> Dict[str, Any]:
        """执行处理器: 请求 → EmbodiedGoal → run_goal (经 Permission)"""
        try:
            goal = EmbodiedGoal.create(
                description=request.get("description",
                                        request.get("text", "")),
                intent=request.get("intent", ""),
                target=request.get("target", ""),
                scene=request.get("scene", ""),
                constraints=dict(request.get("constraints", {}) or {}),
                priority=request.get("priority", "medium"),
            )
            result = svc.run_goal(goal)
            return {
                "data": {
                    "success": result.success,
                    "status": result.status,
                    "error": result.error,
                    "goal": goal.to_dict(),
                },
                "method": "run_goal",
            }
        except Exception as e:
            return {"error": str(e), "method": "run_goal"}
    registry.register_simple(
        name="execution_agent",
        capability="execution",
        handler=execution_handler,
        description="执行: 目标执行 (经 Permission Layer)",
    )
    return registry


__all__ = [
    "APPROVAL_STATUSES",
    "AdaptivePersonalityEngine",
    "AgentPipeline",
    "ApprovalBridge",
    "ApprovalBridgeError",
    "AUDIT_ACTIONS_EXP",
    "AuditError",
    "BUCKET_SECONDS",
    "BASE_DIMENSIONS",
    "COMMUNICATION_STYLES",
    "CONSOLIDATION_TRANSITIONS",
    "CORRECTION_RULES",
    "CREATIVE_AUDIT_ACTIONS",
    "CREATIVE_KEYWORDS",
    "CompanionLearning",
    "CompanionRouter",
    "CompanionSnapshot",
    "CompanionStats",
    "ConfidenceEngine",
    "ConfidenceError",
    "ConsolidationError",
    "ConsolidationScheduler",
    "ContinuityEngine",
    "ContinuityError",
    "ContradictionDetector",
    "ContradictionError",
    "CorrectionError",
    "CreativeAudit",
    "CreativeAuditError",
    "CreativeEngine",
    "CreativeEngineError",
    "CreativeReasoningEngine",
    "DECISIONS",
    "DEFAULT_KEYWORD_WEIGHT",
    "DEFAULT_PIPELINE",
    "DEFAULT_ROUTE_TOP_K",
    "DEFAULT_WINDOW_DAYS",
    "DecayError",
    "DelegateError",
    "EMOTION_AUDIT_ACTIONS",
    "EMOTION_BASELINE",
    "EMOTION_CONTEXTS",
    "EMOTION_DIMENSIONS",
    "EMOTION_RULES",
    "EXPERIENCE_TYPES",
    "EXPRESSION_AUDIT_ACTIONS",
    "EXPRESSION_RULES",
    "EXPRESSION_STYLES",
    "EXPRESSION_TONES",
    "EmotionAudit",
    "EmotionDecay",
    "EmotionEngine",
    "EmotionEngineError",
    "EmotionError",
    "EmotionMemory",
    "EmotionState",
    "ExpressionContext",
    "ExpressionEngine",
    "ExpressionEngineError",
    "ExpressionRules",
    "EvidenceError",
    "EvidenceManager",
    "ExecutionCoordinator",
    "ExecutorError",
    "ExperienceBridge",
    "ExperienceBridgeError",
    "ExperienceAudit",
    "ExperienceError",
    "ExperienceExtractor",
    "ExperienceManager",
    "ExperienceManagerError",
    "ExperienceQuery",
    "ExperienceQueryError",
    "ExperienceRecord",
    "ExperienceStore",
    "ExperienceStoreError",
    "ExtractorError",
    "FAILURE_REASONS",
    "FAILURE_SIGNALS",
    "FAMILIARITY_STEP",
    "FALLBACK_CAPABILITIES",
    "FailureAnalysisEngine",
    "FailureError",
    "GROWTH_EVENT_TYPES",
    "GrowthMeaning",
    "GrowthReport",
    "GrowthRhythm",
    "GrowthTracker",
    "GrowthTrend",
    "GrowthTrigger",
    "IDENTITY_AUDIT_ACTIONS",
    "IDENTITY_KEYWORDS",
    "IMMUTABLE_FIELDS",
    "INTENT_KEYWORDS",
    "IdentityAudit",
    "IdentityAuditError",
    "IdentityDiff",
    "IdentitySnapshot",
    "IdentitySnapshotError",
    "ImportanceError",
    "ImprovementProposalEngine",
    "IndexError",
    "InteractionWindow",
    "JSONLStorage",
    "KEYWORD_WEIGHTS",
    "LOOP_PIPELINE",
    "LearningError",
    "MEANING_TEMPLATES",
    "MEMORY_STAGES",
    "MEMORY_TYPES",
    "MainAgentError",
    "MainCompanionAgent",
    "ManagerError",
    "MeaningError",
    "MemoryConsolidation",
    "MemoryImportance",
    "MemoryIndex",
    "MemoryError",
    "NOISE_FIELDS",
    "OCRMockAdapter",
    "OCRResult",
    "OPPORTUNITY_SOURCE_TYPES",
    "OpportunityDetector",
    "OpportunityError",
    "PATH_KEYWORDS",
    "PATH_TYPES",
    "PERSONALITY_CONTEXTS",
    "PERSONALITY_DIMENSIONS",
    "PERSONALITY_RULES",
    "PatternDiscovery",
    "PatternError",
    "PersonalityAuditRecord",
    "PersonalityDecayPolicy",
    "PersonalityError",
    "PersonalityRuleError",
    "PersonalityState",
    "PipelineError",
    "ProposalError",
    "ProposalGenerationError",
    "ProposalGenerator",
    "ProposalMemory",
    "PROPOSAL_STATUSES",
    "PROPOSAL_TRANSITIONS",
    "PERCEPTION_AUDIT_ACTIONS",
    "PERCEPTION_KINDS",
    "PERCEPTION_SOURCES",
    "PERCEPTION_TYPES",
    "PERSISTENCE_AUDIT_ACTIONS",
    "PersistenceAudit",
    "PersistenceAuditError",
    "PerceptionAdapter",
    "PerceptionAdapterError",
    "PerceptionAudit",
    "PerceptionEvent",
    "PerceptionManager",
    "PerceptionPermission",
    "PerceptionService",
    "PerceptionServiceError",
    "PerceptionVerifier",
    "PermissionError",
    "REFLECTION_AUDIT_ACTIONS",
    "REQUIRED_FIELDS",
    "RECOMMENDATIONS",
    "RELATIONSHIP_KEYWORDS",
    "RESTORE_STEPS",
    "RHYTHM_AUDIT_ACTIONS",
    "ROUTE_RULE_VERSION",
    "ReasoningError",
    "RealityCheck",
    "RealityError",
    "ReflectionAudit",
    "ReflectionAuditError",
    "ReflectionBridge",
    "ReflectionBridgeError",
    "ReflectionEngine",
    "ReflectionError",
    "RelationshipError",
    "RelationshipManager",
    "RelationshipState",
    "ReportError",
    "RestoreError",
    "RestoreManager",
    "RhythmAudit",
    "RhythmAuditError",
    "RhythmError",
    "RouterError",
    "RulesError",
    "SNAPSHOT_DOMAINS",
    "SchedulerError",
    "SchemaError",
    "SPECIALIST_CAPABILITIES",
    "STAGE_THRESHOLDS",
    "SIDE_EFFECT_KEYWORDS",
    "SOURCE_IMPACT_BONUS",
    "SelfCorrector",
    "SimulationEngine",
    "SimulationError",
    "SnapshotError",
    "SpecialistAgent",
    "SpecialistError",
    "SpecialistRegistry",
    "StatsError",
    "StorageError",
    "TREND_BUCKETS",
    "TRIGGER_CONDITIONS",
    "TRUST_STEP",
    "TaskDelegator",
    "TrackerError",
    "TrendError",
    "TriggerError",
    "VALUE_HIGH",
    "VALUE_LOW",
    "VALUE_MEDIUM",
    "VALUE_WEIGHTS",
    "ValueEvaluator",
    "VERIFICATION_STATUSES",
    "VERIFICATION_TRANSITIONS",
    "VerificationError",
    "VerificationState",
    "VerifierError",
    "VisionMockAdapter",
    "WindowError",
    "adjustment_reason",
    "apply_adjustment",
    "build_default_agents",
    "get_personality_service",
    "reset_personality_service",
    "rule_for",
    "ApplierError",
    "ChangeValidator",
    "CognitiveContradictionDetector",
    "CognitiveContradictionError",
    "CognitiveReflectionEngine",
    "CognitiveReflectionError",
    "CONTRADICTION_TYPES",
    "GuardError",
    "GrowthApplier",
    "GrowthAudit",
    "GrowthEvaluator",
    "GrowthEvaluatorError",
    "GrowthProposal",
    "GrowthProposalError",
    "IdentityGuard",
    "IMMUTABLE_FIELDS",
    "PATTERN_TYPES",
    "PROPOSAL_TYPES",
    "PROTECTED_FIELDS",
    "PatternAnalyzer",
    "PatternAnalyzerError",
    "ReflectionReport",
    "ReportError",
    "SAFETY_KEYWORDS",
    "ValidatorError",
    "CycleError",
    "GrowthCycleEngine",
    "GrowthTrendAnalysis",
    "ReflectionEmotionError",
    "ReflectionEmotionIntegrator",
    "TrendAnalysisError",
    "ApiGateway",
    "Capability",
    "CapabilityMatcher",
    "CloudProvider",
    "CostPolicy",
    "HybridError",
    "HybridIntelligenceLayer",
    "InferenceAudit",
    "LocalCapability",
    "LocalProvider",
    "ModelEndpoint",
    "PrivacyPolicy",
    "ResultValidator",
    "RoutingEngine",
    "RoutingPolicy",
    "TaskClassifier",
    "PRESENCE_OUTPUT_FIELDS",
    "PRESENCE_PROTECTED_FIELDS",
    "PresenceEngine",
    "PresenceEngineError",
    "PresenceMapper",
    "PresenceMapperError",
    "PresenceMemory",
    "PresenceMemoryError",
    "PresenceState",
    "PresenceStateError",
    "ConstitutionEngine",
    "ConstitutionError",
    "ConstitutionLedger",
    "ConstitutionValidator",
    "EvolutionProposal",
    "GrowthPolicy",
    "IdentityRules",
    "IntelligencePolicy",
    "LedgerError",
    "Principles",
    "RuleEngine",
    "SafetyPolicy",
    "CollaborativeCreation",
    "CollaborativeError",
    "ConceptFusion",
    "CreativeMemory",
    "CreativeMemoryError",
    "CreativeValidation",
    "FusionError",
    "HypothesisEngine",
    "HypothesisError",
    "IdeaSparkGenerator",
    "KnowledgeGraph",
    "KnowledgeGraphError",
    "MEMORY_STATUS",
    "MetaCreativeEngine",
    "MetaCreativeError",
    "SparkError",
    "ThoughtBoundaryDetector",
    "ValidationError",
    "HypothesisLoop",
    "KnowledgeAcquisition",
    "ObservationLayer",
    "QuestionDiscoveryEngine",
    "RealityValidation",
    "ResearchAudit",
    "ResearchEngine",
    "ResearchMemory",
    "ResearchPlanner",
    "CognitionAudit",
    "CognitionMemory",
    "CognitiveMonitor",
    "ErrorPatternDetector",
    "MetaCognitionEngine",
    "ReflectionLoop",
    "ReasoningEvaluator",
    "SelfVerification",
]
