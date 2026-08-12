"""
YHLZ Embodied AI V5.8 - 具身智能基础架构 (Reflection & Cognitive Integrity Layer)

架构:
    Interface (Agent / 外部调用)
        ↓
    EmbodiedService (闭环: Observe → Reasoning → Permission → Action → Feedback + 上下文 + 经验)
        ↓
    EmbodiedManager (注册 / 路由 / 生命周期 + WorldModel + Memory + Feedback + Predictor + EventLog)
        ↓
    EnvironmentRegistry → Adapter (MockEnvironment / HardwareEnvironment)

数据层:
    WorldModel (状态历史 + 差异分析) / EnvironmentMemory (Embodied 专用记忆 + 经验摘要)
    FeedbackStore + FeedbackAnalyzer (反馈闭环) / StatePredictor (预测 + 多步条件预测)
    EventLog (事件时间线) / CausalAnalyzer (因果分析) / InvariantChecker (不变式) / SemanticAnalyzer (语义环境)

推理链路 (V4.2):
    Environment State → Event Understanding → Cause Analysis → Prediction → Reasoning → Better Action

经验层 (V4.3, 规则驱动):
    Experience → Analysis → Pattern Extraction → Policy Table → Future Suggestion
    Goal Replay (目标回放) / Scene Lifecycle (场景生命周期) / Embodied Report (状态报告)
    禁止神经网络训练 / 黑盒学习; 策略建议不绕过 Permission Layer

治理层 (V4.5, 元策略管理):
    StrategyGovernance (门面) → Overview / Governance / Evolution / Health / Dry Run
    治理动作只影响: 策略表 → 审计日志 → 体系快照 (不触碰 Permission / Agent Memory)

规划层 (V4.6, 跨目标战略规划):
    CrossGoalPlanner (门面) → GoalDependencyAnalyzer (分组/共享步骤/信息复用)
                            → BudgetAllocator (预算分配/冲突检测)
    规划只输出方案: 不修改策略表, 不绕过 Permission, 不写 Agent Memory

长期任务层 (V4.7, Long Horizon Planning Layer):
    LongHorizonPlanner (门面) → MilestoneManager (LongGoal/Milestone/分解)
                              → DependencyGraph (依赖/阻塞/拓扑)
                              → ProgressTracker (进度/报告/快照恢复)
                              → PlanAdjuster (调整/风险/时间规划)
    Long Goal → Milestone → Cross Goal Planner → Strategy → Execution
    允许读取 Experience Memory (历史参考), 禁止修改; 不自动执行

伙伴架构层 (V5.0, Adaptive Companion Architecture):
    MainCompanionAgent (主伙伴 Agent: 统一入口/统一人格/统一决策中心)
        ├── CompanionRouter     (内部路由: 意图 → 专业 Agent, 确定性规则)
        ├── TaskDelegator       (委派: 路由 → 专业 Agent → 结果汇总)
        └── SpecialistRegistry  (专业 Agent 注册中心: 6 能力域)
    专业 Agent: perception / reasoning / experience / planning /
                long_horizon / governance (对接既有模块, 无独立人格)
    一个人格 / 一个核心意识 / 一个决策中心; 内部单进程多 Agent

伙伴协同层 (V5.1, Companion Coordination Enhancement):
    CompanionRouter 增强: 关键词权重打分 + Top-K 路由 (可解释分数)
    TaskDelegator 增强: 并发委派 (线程池) + 超时控制 + 耗时统计
    CompanionStats: 协同统计 (委派组合/耗时/成功率)
    细化专业 Agent 映射: 精确对接 Service 方法 (含参数回退)

感知-战略集成层 (V5.2, Companion Perception & Strategy Integration):
    AgentPipeline: Agent 数据管道 (前序输出 → 后序输入, 顺序依赖, 可解释)
    TaskDelegator 增强: 管道感知委派 (依赖顺序执行 + pipeline 明细)
    感知-策略闭环: perception → experience → planning (环境状态 → 策略建议 → 规划)
    CompanionResponse 增强: pipeline / pipeline_stages

执行-反馈闭环层 (V5.3, Companion Execution & Feedback Loop):
    ExecutionCoordinator: 执行协调器 (规划 → 执行 → 反馈 → 调整, 闭环循环)
    执行闭环管道: perception → experience → planning → execution → feedback
    execution_agent: 执行 Agent (run_goal, 经 Permission Layer)
    ExecutionRecord: 执行审计 (goal/actions/result/latency_ms/status)

自我修正与学习层 (V5.4, Companion Self-Correction & Learning):
    SelfCorrector: 自我修正器 (执行失败 → 规则调整 → 再执行, 上限内)
    CompanionLearning: 学习器 (失败/成功模式 → 规则表, 阈值提升)
    修正策略表: 失败原因 → 修正动作映射 (position_mismatch → 先移动等)
    学习 = 规则统计 (禁止神经网络训练 / 黑盒优化)

身份与自适应人格层 (V5.5, Companion Identity & Adaptive Personality):
    AdaptivePersonalityEngine: 自适应人格引擎 (核心稳定 + 表现自适应)
    人格维度: warmth/patience/humor/serious (0.0~1.0)
    情境规则: success/failure/consecutive_fail/casual_chat/serious_task
    互动统计 (只存数字) + 人格审计 (每次调整记录)
    核心人格 (base) 不可修改 (一个人格 / 一个核心意识 / 一个决策中心)

关系与人格稳定层 (V5.6, Companion Relationship & Personality Stability):
    PersonalityDecayPolicy: 人格衰减 (时间 → 基础值平滑回归, 不突变)
    InteractionWindow: 时间窗口统计 (7/30 天成功率, 只存数字)
    RelationshipManager: 关系状态 (trust/familiarity/communication_style/stage)
    人格-关系联动: 长期稳定 → warmth, 连续失败 → patience (规则驱动)
    审计升级: PersonalityAuditRecord 含 relationship_context/decay_reason/
              window_statistics

经历记忆层 (V5.7, Experience Memory Layer):
    ExperienceManager: 经历管理器 (store/retrieve/update/decay/forget)
    ExperienceStore: 存储 (高价值长期保存, 低价值衰减遗忘, 上限保护)
    ExperienceExtractor: 抽取 (事件 → 经验, 规则驱动, 5 种类型)
    ExperienceQuery: 查询 (类型/关键词/相关检索, 可解释排序)
    ExperienceAudit: 审计 (每次操作追踪)
    Reflection Report: 主动输出 (Observation/发现/Suggestion)
    经历 → 记录 → 总结 → 学习 → 改进 (成长闭环)
    经验仅供参考, 不替代核心 Agent 决策

反思与认知完整性层 (V5.8, Reflection & Cognitive Integrity Layer):
    ReflectionEngine: 反思引擎 (经历 → Reflection Report: 模式/失败/建议/置信度)
    PatternDiscovery: 模式发现 (跨经历规律, 样本/跨度/重复/反例)
    FailureAnalysisEngine: 失败分析 (原因/证据/置信度/修正建议)
    ImprovementProposalEngine: 改进建议 (Proposal ≠ Action, 需批准)
    ExperienceVerifier: 经验验证 (UNKNOWN→PENDING→PROBABLE→CONFIRMED/REJECTED)
    ConfidenceEngine: 置信度 (来源/重复/一致/反例/稳定 加权)
    EvidenceManager: 证据管理 / ContradictionDetector: 矛盾检测 →
      Context-dependent / RealityCheck: 5 问验证
    只有 CONFIRMED 经验进入长期成长参考 (认知免疫系统)
"""

from backend.embodied.companion import (
    AUDIT_ACTIONS_EXP,
    AdaptivePersonalityEngine,
    AgentPipeline,
    AuditError,
    BASE_DIMENSIONS,
    COMMUNICATION_STYLES,
    CORRECTION_RULES,
    CompanionLearning,
    CompanionRouter,
    CompanionStats,
    ConfidenceEngine,
    ConfidenceError,
    ContradictionDetector,
    ContradictionError,
    CorrectionError,
    DEFAULT_KEYWORD_WEIGHT,
    DEFAULT_PIPELINE,
    DEFAULT_ROUTE_TOP_K,
    DEFAULT_WINDOW_DAYS,
    DecayError,
    EXPERIENCE_TYPES,
    EvidenceError,
    EvidenceManager,
    ExecutionCoordinator,
    ExecutorError,
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
    ExperienceVerifier,
    ExtractorError,
    FAILURE_REASONS,
    FAILURE_SIGNALS,
    FAMILIARITY_STEP,
    FALLBACK_CAPABILITIES,
    FailureAnalysisEngine,
    FailureError,
    INTENT_KEYWORDS,
    ImprovementProposalEngine,
    InteractionWindow,
    KEYWORD_WEIGHTS,
    LOOP_PIPELINE,
    LearningError,
    MainAgentError,
    MainCompanionAgent,
    PERSONALITY_CONTEXTS,
    PERSONALITY_DIMENSIONS,
    PERSONALITY_RULES,
    PatternDiscovery,
    PatternError,
    PersonalityAuditRecord,
    PersonalityDecayPolicy,
    PersonalityError,
    PersonalityRuleError,
    PersonalityState,
    PipelineError,
    ProposalError,
    REFLECTION_AUDIT_ACTIONS,
    ROUTE_RULE_VERSION,
    RealityCheck,
    RealityError,
    ReflectionAudit,
    ReflectionAuditError,
    ReflectionEngine,
    ReflectionError,
    RelationshipError,
    RelationshipManager,
    RelationshipState,
    RouterError,
    SPECIALIST_CAPABILITIES,
    STAGE_THRESHOLDS,
    SelfCorrector,
    SpecialistAgent,
    SpecialistError,
    SpecialistRegistry,
    StatsError,
    TRUST_STEP,
    TaskDelegator,
    VALUE_HIGH,
    VALUE_LOW,
    VALUE_MEDIUM,
    VERIFICATION_STATUSES,
    VERIFICATION_TRANSITIONS,
    VerificationState,
    VerifierError,
    WindowError,
    adjustment_reason,
    apply_adjustment,
    get_personality_service,
    reset_personality_service,
    rule_for,
)
from backend.embodied.environment.adapter import HardwareEnvironment
from backend.embodied.environment.interface import Environment, EnvironmentError
from backend.embodied.environment.mock import MockEnvironment
from backend.embodied.environment.registry import (
    EnvironmentRegistry,
    EnvironmentRegistryError,
)
from backend.embodied.experience.learner import (
    ExperienceLearner,
    ExperienceLearnerError,
)
from backend.embodied.experience.patterns import (
    FAILURE_PATTERN_RULES,
    PatternExtractor,
    PatternExtractorError,
)
from backend.embodied.experience.policy import (
    ExperiencePolicy,
    PolicyTable,
    PolicyTableError,
)
from backend.embodied.feedback.analyzer import (
    FeedbackAnalyzer,
    FeedbackAnalyzerError,
    SUGGESTION_RULES,
)
from backend.embodied.feedback.processor import (
    FeedbackProcessor,
    FeedbackStore,
    FeedbackStoreError,
)
from backend.embodied.governance import (
    DryRunError,
    EvolutionError,
    GOVERNANCE_DRY_RUN_ACTIONS,
    GovernanceDryRun,
    GovernanceError,
    HealthError,
    OverviewError,
    PolicyEvolution,
    PolicyGovernance,
    PolicyHealthCheck,
    StrategyGovernance,
    StrategySystemOverview,
    SystemSnapshot,
)
from backend.embodied.manager import (
    EmbodiedManager,
    EmbodiedManagerError,
    get_manager,
    reset_manager,
)
from backend.embodied.permission import (
    EmbodiedPermission,
    EmbodiedPermissionConfig,
    PermissionChecker,
)
from backend.embodied.planning import (
    BudgetAllocator,
    BudgetError,
    CrossGoalError,
    CrossGoalPlanner,
    DependencyError,
    GoalDependencyAnalyzer,
    LongHorizonPlanner,
    LongHorizonPlannerError,
)
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
from backend.embodied.reasoning.semantics import SemanticAnalyzer, SemanticError
from backend.embodied.replay import (
    GoalReplayError,
    GoalStep,
    GoalTrace,
    GoalTraceStore,
)
from backend.embodied.scene import SceneManager, SceneManagerError
from backend.embodied.schema import (
    CausalAnalysis,
    CauseType,
    EmbodiedAction,
    EmbodiedActionType,
    EmbodiedGoal,
    EmbodiedStatus,
    EnvironmentEvent,
    EnvironmentObject,
    EnvironmentPrediction,
    EnvironmentState,
    EventType,
    ExperienceSummary,
    Feedback,
    FeedbackAnalysis,
    FeedbackResult,
    MultiStepPrediction,
    WorldStateHistory,
)
from backend.embodied.service import (
    EmbodiedOperationResult,
    EmbodiedService,
    EmbodiedServiceError,
    get_service,
    reset_service,
)
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
from backend.embodied.world_model.memory import (
    EnvironmentMemory,
    EnvironmentMemoryError,
)
from backend.embodied.world_model.predictor import PredictorError, StatePredictor
from backend.embodied.world_model.state import WorldModel, WorldModelError

__version__ = "9.5.0"

__all__ = [
    "AUDIT_ACTIONS",
    "AUDIT_ACTIONS_EXP",
    "AdaptivePersonalityEngine",
    "AgentPipeline",
    "AuditError",
    "BASE_DIMENSIONS",
    "BudgetAllocator",
    "BudgetError",
    "COMMUNICATION_STYLES",
    "CORRECTION_RULES",
    "CausalAnalysis",
    "CausalAnalyzer",
    "CausalAnalyzerError",
    "CauseType",
    "CAUSE_REMEDY_RULES",
    "CompanionLearning",
    "CompanionRouter",
    "CompanionStats",
    "ConfidenceEngine",
    "ConfidenceError",
    "ContradictionDetector",
    "ContradictionError",
    "CorrectionError",
    "CrossGoalError",
    "CrossGoalPlanner",
    "DEFAULT_INVARIANT_RULES",
    "DEFAULT_KEYWORD_WEIGHT",
    "DEFAULT_PIPELINE",
    "DEFAULT_ROUTE_TOP_K",
    "DEFAULT_WINDOW_DAYS",
    "DecayError",
    "DependencyError",
    "DryRunError",
    "EXPERIENCE_TYPES",
    "EmbodiedAction",
    "EmbodiedActionType",
    "EmbodiedGoal",
    "EmbodiedManager",
    "EmbodiedManagerError",
    "EmbodiedOperationResult",
    "EmbodiedPermission",
    "EmbodiedPermissionConfig",
    "EmbodiedService",
    "EmbodiedServiceError",
    "EmbodiedStatus",
    "Environment",
    "EnvironmentError",
    "EnvironmentEvent",
    "EnvironmentEventLog",
    "EnvironmentEventLogError",
    "EnvironmentMemory",
    "EnvironmentMemoryError",
    "EnvironmentObject",
    "EnvironmentPrediction",
    "EnvironmentRegistry",
    "EnvironmentRegistryError",
    "EnvironmentState",
    "EventType",
    "EvidenceError",
    "EvidenceManager",
    "EvolutionError",
    "ExecutionCoordinator",
    "ExecutorError",
    "ExperienceAudit",
    "ExperienceError",
    "ExperienceExtractor",
    "ExperienceLearner",
    "ExperienceLearnerError",
    "ExperienceManager",
    "ExperienceManagerError",
    "ExperiencePolicy",
    "ExperienceQuery",
    "ExperienceQueryError",
    "ExperienceRecord",
    "ExperienceStore",
    "ExperienceStoreError",
    "ExperienceSummary",
    "ExperienceVerifier",
    "ExtractorError",
    "FAILURE_REASONS",
    "FAILURE_SIGNALS",
    "FAMILIARITY_STEP",
    "FALLBACK_CAPABILITIES",
    "FAILURE_PATTERN_RULES",
    "FailureAnalysisEngine",
    "FailureError",
    "Feedback",
    "FeedbackAnalysis",
    "FeedbackAnalyzer",
    "FeedbackAnalyzerError",
    "FeedbackProcessor",
    "FeedbackResult",
    "FeedbackStore",
    "FeedbackStoreError",
    "GOVERNANCE_DRY_RUN_ACTIONS",
    "GOAL_TYPES",
    "GoalDependencyAnalyzer",
    "GoalReplayError",
    "GoalStep",
    "GoalTrace",
    "GoalTraceStore",
    "GovernanceDryRun",
    "GovernanceError",
    "HardwareEnvironment",
    "HealthError",
    "InvariantChecker",
    "InvariantError",
    "INTENT_KEYWORDS",
    "KEYWORD_WEIGHTS",
    "LOOP_PIPELINE",
    "LONG_GOAL_STATUSES",
    "LearningError",
    "LongGoal",
    "LongHorizonError",
    "LongHorizonPlanner",
    "LongHorizonPlannerError",
    "MainAgentError",
    "MainCompanionAgent",
    "MockEnvironment",
    "MultiStepPrediction",
    "OverviewError",
    "PERSONALITY_CONTEXTS",
    "PERSONALITY_DIMENSIONS",
    "PERSONALITY_RULES",
    "PatternDiscovery",
    "PatternError",
    "PatternExtractor",
    "PatternExtractorError",
    "PermissionChecker",
    "PersonalityAuditRecord",
    "PersonalityDecayPolicy",
    "PersonalityError",
    "PersonalityRuleError",
    "PersonalityState",
    "PipelineError",
    "PolicyAuditError",
    "PolicyAuditLog",
    "PolicyEvolution",
    "PolicyGovernance",
    "PolicyHealthCheck",
    "PolicyRanker",
    "PolicyRankerError",
    "PolicyTable",
    "PolicyTableError",
    "PredictorError",
    "ProposalError",
    "REFLECTION_AUDIT_ACTIONS",
    "ROUTE_RULE_VERSION",
    "RealityCheck",
    "RealityError",
    "ReflectionAudit",
    "ReflectionAuditError",
    "ReflectionEngine",
    "ReflectionError",
    "RelationshipError",
    "RelationshipManager",
    "RelationshipState",
    "RouterError",
    "SPECIALIST_CAPABILITIES",
    "STAGE_THRESHOLDS",
    "SceneManager",
    "SceneManagerError",
    "SelfCorrector",
    "SemanticAnalyzer",
    "SemanticError",
    "SpecialistAgent",
    "SpecialistError",
    "SpecialistRegistry",
    "StatePredictor",
    "StatsError",
    "StrategyGovernance",
    "StrategySystemOverview",
    "SUGGESTION_RULES",
    "SystemSnapshot",
    "TRUST_STEP",
    "TaskDelegator",
    "TrendStats",
    "TrendStatsError",
    "VALUE_HIGH",
    "VALUE_LOW",
    "VALUE_MEDIUM",
    "VERIFICATION_STATUSES",
    "VERIFICATION_TRANSITIONS",
    "VerificationState",
    "VerifierError",
    "WindowError",
    "WorldModel",
    "WorldModelError",
    "WorldStateHistory",
    "adjustment_reason",
    "apply_adjustment",
    "get_manager",
    "get_personality_service",
    "get_service",
    "infer_goal_type",
    "reset_manager",
    "reset_personality_service",
    "reset_service",
    "rule_for",
]
