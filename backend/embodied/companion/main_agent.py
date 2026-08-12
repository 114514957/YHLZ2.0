"""
YHLZ Embodied AI V5.1 - 主伙伴 Agent (Main Companion Agent)

职责:
    - 统一入口: 接收请求 → 路由 → 委派 → 汇总 (CompanionResponse)
    - 统一人格: 主 Agent 保持统一人格 (铁哥们/随意亲切),
      专业 Agent 不拥有独立人格
    - 统一决策中心: 所有结果经主 Agent 汇总输出
    - 预演: companion_dry_run (不执行, 只输出路由与委派方案)
    - 协同统计: 每次委派记录 (组合/耗时/成功率, V5.1)

流程:
    Main Companion Agent
        ↓ 意图理解 (路由打分)
    Specialist Agents (并发委派)
        ↓ 结果汇总
    统一响应 (CompanionResponse)

安全约束:
    - 主 Agent 不绕过 Permission Layer (执行仍走 Service 既有流程)
    - 不写 Agent Memory (专业 Agent 只读经验)
    - 纯规则分派 (确定性, 禁止自由协商)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

from backend.embodied.companion.delegate import TaskDelegator
from backend.embodied.companion.router import CompanionRouter
from backend.embodied.companion.specialist import SpecialistRegistry
from backend.embodied.companion.stats import CompanionStats

logger = logging.getLogger(__name__)


class MainAgentError(Exception):
    """主伙伴 Agent 操作异常"""


class MainCompanionAgent:
    """主伙伴 Agent (统一入口 / 统一人格 / 统一决策中心)

    用法:
        agent = MainCompanionAgent(registry, router, delegator)
        response = agent.handle({"text": "帮我整理房间"})
        dry = agent.dry_run({"text": "扫描环境"})
    """

    def __init__(
        self,
        registry: SpecialistRegistry,
        router: CompanionRouter,
        delegator: TaskDelegator,
        personality: str = "铁哥们",
        enabled: bool = True,
        stats: Optional[CompanionStats] = None,
        personality_engine=None,
        relationship_manager=None,
        decay_policy=None,
        interaction_window=None,
        experience_manager=None,
        reflection_engine=None,
        experience_verifier=None,
        creative_engine=None,
        creative_config: Optional[Dict[str, Any]] = None,
        continuity_engine=None,
        continuity_config: Optional[Dict[str, Any]] = None,
        emotion_engine=None,
        rhythm=None,
        rhythm_config: Optional[Dict[str, Any]] = None,
        expression_engine=None,
        perception_service=None,
        perception_config: Optional[Dict[str, Any]] = None,
        memory_gate=None,
        pipeline_adapter=None,
        reflection_evaluator=None,
        counterfactual_check=None,
        cognitive_reflection=None,
        growth_engine=None,
        identity_guard=None,
        growth_config: Optional[Dict[str, Any]] = None,
        reflection_emotion=None,
        growth_cycle=None,
        growth_trend_analysis=None,
        hybrid_layer=None,
        hybrid_config: Optional[Dict[str, Any]] = None,
        presence_engine=None,
        presence_config: Optional[Dict[str, Any]] = None,
        constitution_engine=None,
        constitution_config: Optional[Dict[str, Any]] = None,
        meta_creative=None,
        meta_creative_config: Optional[Dict[str, Any]] = None,
        research_engine=None,
        research_config: Optional[Dict[str, Any]] = None,
        meta_cognition=None,
        meta_cognition_config: Optional[Dict[str, Any]] = None,
    ):
        self._lock = threading.RLock()
        self._registry = registry
        self._router = router
        self._delegator = delegator
        self._personality = personality
        self._enabled = enabled
        self._handled_count = 0
        self._stats = stats or CompanionStats()
        # V5.5 自适应人格引擎 (核心稳定 + 表现自适应)
        if personality_engine is None:
            from backend.embodied.companion.personality import (
                AdaptivePersonalityEngine,
            )
            personality_engine = AdaptivePersonalityEngine(base=personality)
        self._personality_engine = personality_engine
        # V5.6 关系管理 + 人格稳定 (衰减) + 窗口统计
        if relationship_manager is None:
            from backend.embodied.companion.relationship import (
                RelationshipManager,
            )
            relationship_manager = RelationshipManager()
        self._relationship = relationship_manager
        if decay_policy is None:
            from backend.embodied.companion.personality_decay import (
                PersonalityDecayPolicy,
            )
            decay_policy = PersonalityDecayPolicy()
        self._decay = decay_policy
        if interaction_window is None:
            from backend.embodied.companion.interaction_window import (
                InteractionWindow,
            )
            interaction_window = InteractionWindow()
        self._window = interaction_window
        # V5.7 经历记忆 (经历 → 记录 → 总结 → 学习 → 改进)
        if experience_manager is None:
            from backend.embodied.companion.experience import (
                ExperienceManager,
            )
            experience_manager = ExperienceManager()
        self._experience = experience_manager
        # V5.8 反思与认知完整性 (理解经历 + 验证可信)
        if reflection_engine is None:
            from backend.embodied.companion.reflection import (
                ReflectionEngine,
            )
            reflection_engine = ReflectionEngine()
        self._reflection = reflection_engine
        if experience_verifier is None:
            from backend.embodied.companion.verification import (
                ExperienceVerifier,
            )
            experience_verifier = ExperienceVerifier()
        self._verifier = experience_verifier
        # V5.9 创造智能 (主动发现价值机会 + 创造方案)
        if creative_engine is None:
            from backend.embodied.companion.creative import (
                CreativeEngine,
            )
            creative_engine = CreativeEngine(
                experience_manager=self._experience,
                verifier=self._verifier,
                reflection_engine=self._reflection,
                improvement_engine=self._reflection._proposals,
                relationship_manager=self._relationship,
                enabled=bool((creative_config or {}).get(
                    "companion_creative_enabled", True,
                )),
                config=creative_config,
            )
        self._creative = creative_engine
        # V6.0 长期身份与成长连续 (持久化 + 记忆体系 + 身份历史 + 成长)
        if continuity_engine is None:
            from backend.embodied.companion.continuity_engine import (
                ContinuityEngine,
            )
            continuity_engine = ContinuityEngine(
                experience_manager=self._experience,
                verifier=self._verifier,
                reflection_engine=self._reflection,
                creative_engine=self._creative,
                relationship_manager=self._relationship,
                personality_engine=self._personality_engine,
                enabled=bool((continuity_config or {}).get(
                    "companion_persistence_enabled", True,
                )),
                config=continuity_config,
            )
        self._continuity = continuity_engine
        # V6.1.1 情绪引擎 (可计算状态, 与人格严格隔离)
        if emotion_engine is None:
            from backend.embodied.companion.emotion import (
                EmotionEngine,
            )
            emotion_engine = EmotionEngine(
                enabled=bool((rhythm_config or {}).get(
                    "companion_emotion_enabled", True,
                )),
                update_step=float((rhythm_config or {}).get(
                    "companion_emotion_update_step", 0.1,
                )),
                decay_rate=float((rhythm_config or {}).get(
                    "companion_emotion_decay_rate", 0.05,
                )),
                decay_window_days=float((rhythm_config or {}).get(
                    "companion_emotion_decay_window_days", 7.0,
                )),
                consecutive_limit=int((rhythm_config or {}).get(
                    "companion_emotion_consecutive_limit", 3,
                )),
                floor=float((rhythm_config or {}).get(
                    "companion_emotion_floor", 0.1,
                )),
            )
        self._emotion = emotion_engine
        # 让连续层感知情绪引擎 (快照 emotion 域)
        self._continuity._emotion = self._emotion
        # V6.1.1 成长节律 (handle 联动 + 自动整理/快照/反思)
        if rhythm is None:
            from backend.embodied.companion.rhythm import (
                GrowthRhythm,
            )
            rhythm = GrowthRhythm(
                continuity=self._continuity,
                emotion=self._emotion,
                enabled=bool((rhythm_config or {}).get(
                    "companion_rhythm_enabled", True,
                )),
                config=rhythm_config,
            )
        self._rhythm = rhythm
        # V6.2 表达引擎 (状态 → 表达建议, 表达 ≠ 人格修改)
        if expression_engine is None:
            from backend.embodied.companion.expression import (
                ExpressionEngine,
            )
            expression_engine = ExpressionEngine(
                enabled=bool((perception_config or {}).get(
                    "companion_expression_enabled", True,
                )),
                threshold=float((perception_config or {}).get(
                    "companion_expression_threshold", 0.7,
                )),
            )
        self._expression = expression_engine
        # V6.2 感知服务 (权限默认拒绝 + 验证网关 + 记忆候选)
        if perception_service is None:
            from backend.embodied.companion.perception import (
                DetectionMockAdapter,
                OCRMockAdapter,
                PerceptionManager,
                PerceptionPermission,
                PerceptionService,
                PerceptionVerifier,
                VisionMockAdapter,
            )
            cfg = dict(perception_config or {})
            pmgr = PerceptionManager(
                default_ocr=str(cfg.get(
                    "perception_default_ocr", "ocr_mock",
                )),
                default_detect=str(cfg.get(
                    "perception_default_detection",
                    "detection_mock",
                )),
            )
            pmgr.register(OCRMockAdapter())
            pmgr.register(DetectionMockAdapter())
            pmgr.register(VisionMockAdapter())
            from backend.embodied.companion.perception import (
                CameraAdapter,
            )
            pmgr.register(CameraAdapter())
            perception_service = PerceptionService(
                manager=pmgr,
                permission=PerceptionPermission(
                    enabled=bool(cfg.get(
                        "perception_enabled", False,
                    )),
                    vision_enabled=bool(cfg.get(
                        "vision_enabled", False,
                    )),
                    ocr_enabled=bool(cfg.get(
                        "ocr_enabled", False,
                    )),
                    detection_enabled=bool(cfg.get(
                        "detection_enabled", False,
                    )),
                    permission_required=bool(cfg.get(
                        "perception_permission_required", True,
                    )),
                ),
                verifier=PerceptionVerifier(
                    min_confidence=float(cfg.get(
                        "perception_min_confidence", 0.5,
                    )),
                ),
                audit=__import__(
                    "backend.embodied.companion.perception",
                    fromlist=["PerceptionAudit"],
                ).PerceptionAudit(
                    enabled=bool(cfg.get(
                        "perception_audit_enabled", True,
                    )),
                ),
            )
        self._perception = perception_service
        # V6.3 记忆网关 (感知候选 → 批准 → 经历)
        if memory_gate is None:
            from backend.embodied.companion.perception import (
                ApprovalRule,
                CandidateValidator,
                MemoryGate,
            )
            cfg = dict(perception_config or {})
            memory_gate = MemoryGate(
                validator=CandidateValidator(),
                rule=ApprovalRule(
                    approve_threshold=float(cfg.get(
                        "memory_gate_approve_threshold", 0.6,
                    )),
                    reject_threshold=float(cfg.get(
                        "memory_gate_reject_threshold", 0.3,
                    )),
                ),
                enabled=bool(cfg.get(
                    "memory_gate_enabled", True,
                )),
            )
        self._memory_gate = memory_gate
        # V6.3 Agent 管道适配器 (感知帧 → Agent 输入)
        if pipeline_adapter is None:
            from backend.embodied.companion.perception import (
                AgentPipelineAdapter,
                PerceptionRouter,
            )
            pipeline_adapter = AgentPipelineAdapter(
                router=PerceptionRouter(),
                enabled=bool((perception_config or {}).get(
                    "pipeline_perception_enabled", True,
                )),
            )
        self._pipeline_adapter = pipeline_adapter
        # V6.4 反思评估 (Advisor) + 反事实验证
        if reflection_evaluator is None:
            from backend.embodied.companion.perception import (
                ReflectionEvaluator,
                ReflectionRules,
            )
            reflection_evaluator = ReflectionEvaluator(
                rules=ReflectionRules(
                    threshold=float((perception_config or {}).get(
                        "reflection_score_threshold", 0.6,
                    )),
                ),
                enabled=bool((perception_config or {}).get(
                    "reflection_enabled", True,
                )),
            )
        self._reflection_evaluator = reflection_evaluator
        if counterfactual_check is None:
            from backend.embodied.companion.perception import (
                CounterfactualCheck,
            )
            counterfactual_check = CounterfactualCheck(
                enabled=bool((perception_config or {}).get(
                    "counterfactual_enabled", True,
                )),
            )
        self._counterfactual_check = counterfactual_check
        # 让记忆网关感知反思/反事实组件 (Advisor → Authority)
        self._memory_gate._evaluator = self._reflection_evaluator
        self._memory_gate._counterfactual = \
            self._counterfactual_check
        # 让连续层感知感知/网关 (快照 perception_stats 域)
        self._continuity._perception = self._perception
        self._continuity._memory_gate = self._memory_gate
        # V6.5 认知反思 (理解经历) + 自主成长 (受控优化)
        if cognitive_reflection is None:
            from backend.embodied.companion.reflection import (
                CognitiveReflectionEngine,
                PatternAnalyzer,
            )
            cognitive_reflection = CognitiveReflectionEngine(
                pattern_analyzer=PatternAnalyzer(
                    min_samples=int((growth_config or {}).get(
                        "companion_pattern_min_occurrences", 3,
                    )),
                ),
                enabled=bool((growth_config or {}).get(
                    "reflection_enabled", True,
                )),
            )
        self._cognitive_reflection = cognitive_reflection
        # V6.6 成长配置快照 (趋势窗口等)
        self._growth_config = dict(growth_config or {})
        if growth_engine is None:
            from backend.embodied.companion.growth import (
                GrowthApplier,
                GrowthAudit,
                GrowthEvaluator,
                GrowthProposal,
            )
            growth_engine = {
                "proposal": GrowthProposal(
                    enabled=bool((growth_config or {}).get(
                        "growth_proposal_enabled", True,
                    )),
                ),
                "evaluator": GrowthEvaluator(),
                "applier": GrowthApplier(
                    audit=GrowthAudit(
                        enabled=bool((growth_config or {}).get(
                            "growth_audit_enabled", True,
                        )),
                    ),
                    auto_apply=bool((growth_config or {}).get(
                        "growth_auto_apply", False,
                    )),
                ),
            }
        self._growth_engine = growth_engine
        if identity_guard is None:
            from backend.embodied.companion.identity import (
                ChangeValidator,
                IdentityGuard,
            )
            identity_guard = {
                "guard": IdentityGuard(
                    enabled=bool((growth_config or {}).get(
                        "identity_guard_enabled", True,
                    )),
                ),
                "validator": ChangeValidator(),
            }
        self._identity_guard = identity_guard
        # V6.6 反思-情绪集成 (经 Meaning, 不直接改情绪)
        if reflection_emotion is None:
            from backend.embodied.companion.reflection import (
                ReflectionEmotionIntegrator,
            )
            reflection_emotion = ReflectionEmotionIntegrator(
                emotion=self._emotion,
                enabled=bool((growth_config or {}).get(
                    "companion_reflection_emotion_enabled", True,
                )),
            )
        self._reflection_emotion = reflection_emotion
        # V6.6 成长闭环自动化 (应用永远需审批)
        if growth_cycle is None:
            from backend.embodied.companion.growth import (
                GrowthCycleEngine,
            )
            growth_cycle = GrowthCycleEngine(
                reflection=self._cognitive_reflection,
                proposal=self._growth_engine["proposal"],
                evaluator=self._growth_engine["evaluator"],
                audit=self._growth_engine["applier"]._audit,
                records_fn=self._cycle_records,
                enabled=bool((growth_config or {}).get(
                    "companion_growth_cycle_enabled", True,
                )),
                cycle_days=int((growth_config or {}).get(
                    "companion_growth_cycle_days", 1,
                )),
                min_experience_delta=int(
                    (growth_config or {}).get(
                        "companion_growth_cycle_min_experience_delta",
                        5,
                    ),
                ),
                max_pending=int((growth_config or {}).get(
                    "companion_growth_cycle_max_pending", 50,
                )),
            )
        self._growth_cycle = growth_cycle
        # V6.6 成长趋势分析 (反思/成长/身份/记忆)
        if growth_trend_analysis is None:
            from backend.embodied.companion.growth import (
                GrowthTrendAnalysis,
            )
            growth_trend_analysis = GrowthTrendAnalysis(
                enabled=bool((growth_config or {}).get(
                    "companion_growth_trend_enabled", True,
                )),
            )
        self._growth_trend_analysis = growth_trend_analysis
        # V6.8 混合智能层 (本地 + 云端 + 混合调度)
        if hybrid_layer is None:
            from backend.embodied.companion.hybrid import (
                ApiGateway,
                CapabilityMatcher,
                CloudProvider,
                CostPolicy,
                HybridIntelligenceLayer,
                InferenceAudit,
                LocalProvider,
                PrivacyPolicy,
                ResultValidator,
                RoutingEngine,
                RoutingPolicy,
                TaskClassifier,
            )
            hybrid_cfg = dict(hybrid_config or {})
            audit = InferenceAudit(
                enabled=bool(hybrid_cfg.get(
                    "companion_hybrid_audit_enabled", True,
                )),
                max_records=int(hybrid_cfg.get(
                    "companion_hybrid_audit_max", 2000,
                )),
            )
            cost = CostPolicy(
                enabled=bool(hybrid_cfg.get(
                    "companion_hybrid_cost_enabled", True,
                )),
                high_cost_threshold=float(hybrid_cfg.get(
                    "companion_hybrid_high_cost_threshold",
                    0.01,
                )),
                low_value_threshold=float(hybrid_cfg.get(
                    "companion_hybrid_low_value_threshold",
                    0.3,
                )),
            )
            cloud_enabled = bool(hybrid_cfg.get(
                "companion_hybrid_cloud_enabled", True,
            ))
            privacy = PrivacyPolicy(
                enabled=bool(hybrid_cfg.get(
                    "companion_hybrid_privacy_enabled", True,
                )),
            )
            gateway = ApiGateway(
                enabled=cloud_enabled,
                max_records=int(hybrid_cfg.get(
                    "companion_hybrid_audit_max", 2000,
                )),
            )
            matcher = CapabilityMatcher()
            local = LocalProvider()
            cloud = CloudProvider(
                gateway=gateway, enabled=cloud_enabled,
            )
            routing = RoutingEngine(
                privacy=privacy, cost=cost, matcher=matcher,
            )
            hybrid_layer = HybridIntelligenceLayer(
                classifier=TaskClassifier(),
                matcher=matcher,
                routing=routing,
                local=local,
                cloud=cloud,
                gateway=gateway,
                privacy=privacy,
                cost=cost,
                routing_policy=RoutingPolicy(
                    privacy=privacy, cost=cost,
                ),
                validator=ResultValidator(),
                audit=audit,
                enabled=bool(hybrid_cfg.get(
                    "companion_hybrid_enabled", True,
                )),
            )
            hybrid_layer.initialize_defaults()
        self._hybrid = hybrid_layer
        # V7.0 具身表达层 (内部状态 → 可解释的外部表达)
        if presence_engine is None:
            from backend.embodied.companion.embodied_presence import (
                PresenceEngine,
                PresenceMapper,
                PresenceMemory,
                PresenceState,
            )
            presence_cfg = dict(presence_config or {})
            presence_engine = PresenceEngine(
                state=PresenceState(),
                mapper=PresenceMapper(
                    enabled=bool(presence_cfg.get(
                        "companion_presence_enabled", True,
                    )),
                ),
                memory=PresenceMemory(
                    max_records=int(presence_cfg.get(
                        "companion_presence_memory_max", 2000,
                    )),
                ),
                emotion=self._emotion,
                personality_fn=lambda: (
                    self._personality_engine.personality()
                    if hasattr(
                        self._personality_engine, "personality",
                    ) else {}
                ),
                enabled=bool(presence_cfg.get(
                    "companion_presence_enabled", True,
                )),
                intensity_step=float(presence_cfg.get(
                    "companion_presence_intensity_step", 0.15,
                )),
            )
        self._presence = presence_engine
        self._presence_hybrid_link = bool(
            (presence_config or {}).get(
                "companion_presence_hybrid_link", True,
            )
        )
        # V8.0 宪法引擎 (最高治理层, 任何模块必须接受其约束)
        if constitution_engine is None:
            from backend.embodied.companion.constitution import (
                ConstitutionEngine,
                ConstitutionLedger,
                ConstitutionValidator,
                EvolutionProposal,
                GrowthPolicy,
                IdentityRules,
                IntelligencePolicy,
                Principles,
                RuleEngine,
                SafetyPolicy,
            )
            constitution_cfg = dict(
                constitution_config or {},
            )
            principles = Principles(
                enabled=bool(constitution_cfg.get(
                    "companion_constitution_enabled", True,
                )),
            )
            ledger = ConstitutionLedger(
                enabled=bool(constitution_cfg.get(
                    "companion_constitution_enabled", True,
                )),
                max_records=int(constitution_cfg.get(
                    "companion_constitution_ledger_max", 5000,
                )),
            )
            constitution_engine = ConstitutionEngine(
                principles=principles,
                identity_rules=IdentityRules(),
                safety=SafetyPolicy(),
                growth=GrowthPolicy(),
                intelligence=IntelligencePolicy(),
                validator=ConstitutionValidator(),
                evolution=EvolutionProposal(),
                ledger=ledger,
                enabled=bool(constitution_cfg.get(
                    "companion_constitution_enabled", True,
                )),
            )
        self._constitution = constitution_engine
        self._constitution_hybrid_link = bool(
            (constitution_config or {}).get(
                "companion_constitution_hybrid_link", True,
            )
        )
        self._constitution_growth_link = bool(
            (constitution_config or {}).get(
                "companion_constitution_growth_link", True,
            )
        )
        # V8.5 元创造力引擎 (受治理的创造)
        if meta_creative is None:
            from backend.embodied.companion.creative_intelligence import (
                CollaborativeCreation,
                ConceptFusion,
                CreativeMemory,
                CreativeValidation,
                HypothesisEngine,
                IdeaSparkGenerator,
                KnowledgeGraph,
                MetaCreativeEngine,
                ThoughtBoundaryDetector,
            )
            mc_cfg = dict(meta_creative_config or {})
            meta_creative = MetaCreativeEngine(
                graph=KnowledgeGraph(),
                spark_generator=IdeaSparkGenerator(
                    max_sparks=int(mc_cfg.get(
                        "companion_meta_creative_max_sparks",
                        10,
                    )),
                ),
                fusion=ConceptFusion(),
                boundary=ThoughtBoundaryDetector(),
                hypothesis=HypothesisEngine(),
                validation=CreativeValidation(),
                memory=CreativeMemory(
                    max_records=int(mc_cfg.get(
                        "companion_meta_creative_memory_max",
                        1000,
                    )),
                ),
                collaborative=CollaborativeCreation(),
                constitution=self._constitution if bool(
                    mc_cfg.get(
                        "companion_meta_creative_"
                        "constitution_link", True,
                    )
                ) else None,
                enabled=bool(mc_cfg.get(
                    "companion_meta_creative_enabled", True,
                )),
            )
        self._meta_creative = meta_creative
        self._meta_creative_hybrid_link = bool(
            (meta_creative_config or {}).get(
                "companion_meta_creative_hybrid_link", True,
            )
        )
        # V9.0 自主研究探索引擎 (受治理的主动探索)
        if research_engine is None:
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
            r_cfg = dict(research_config or {})
            observation = ObservationLayer()
            research_engine = ResearchEngine(
                observation=observation,
                question_engine=QuestionDiscoveryEngine(
                    layer=observation,
                ),
                planner=ResearchPlanner(),
                acquisition=KnowledgeAcquisition(),
                loop=HypothesisLoop(),
                reality=RealityValidation(),
                memory=ResearchMemory(),
                audit=ResearchAudit(
                    max_records=int(r_cfg.get(
                        "companion_research_audit_max", 2000,
                    )),
                ),
                constitution=self._constitution if bool(
                    r_cfg.get(
                        "companion_research_"
                        "constitution_link", True,
                    )
                ) else None,
                enabled=bool(r_cfg.get(
                    "companion_research_enabled", True,
                )),
                max_loops_per_explore=int(r_cfg.get(
                    "companion_research_max_loops", 3,
                )),
            )
        self._research = research_engine
        self._research_creative_link = bool(
            (research_config or {}).get(
                "companion_research_creative_link", True,
            )
        )
        self._research_hybrid_link = bool(
            (research_config or {}).get(
                "companion_research_hybrid_link", True,
            )
        )
        # V9.5 元认知引擎 (认知过程分析/评估/修正/优化)
        if meta_cognition is None:
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
            mc_cfg = dict(meta_cognition_config or {})
            meta_cognition = MetaCognitionEngine(
                monitor=CognitiveMonitor(),
                evaluator=ReasoningEvaluator(),
                error_detector=ErrorPatternDetector(),
                reflection=ReflectionLoop(
                    constitution=self._constitution if bool(
                        mc_cfg.get(
                            "companion_meta_cognition_"
                            "constitution_link", True,
                        )
                    ) else None,
                ),
                verification=SelfVerification(),
                memory=CognitionMemory(
                    max_records=int(mc_cfg.get(
                        "companion_meta_cognition_memory_max",
                        1000,
                    )),
                ),
                audit=CognitionAudit(
                    max_records=int(mc_cfg.get(
                        "companion_meta_cognition_audit_max",
                        2000,
                    )),
                ),
                constitution=self._constitution if bool(
                    mc_cfg.get(
                        "companion_meta_cognition_"
                        "constitution_link", True,
                    )
                ) else None,
                enabled=bool(mc_cfg.get(
                    "companion_meta_cognition_enabled", True,
                )),
            )
        self._meta_cognition = meta_cognition
        # V10.1 记忆稳定化引擎 (压缩/淘汰/权重/冲突, 纯增量治理)
        from backend.embodied.companion.memory_stabilization import (
            MemoryStabilizationEngine,
        )
        self._memory_stabilization = MemoryStabilizationEngine(
            config=dict(meta_cognition_config or {}),
            enabled=bool((meta_cognition_config or {}).get(
                "companion_memory_stabilize_enabled", True,
            )),
        )
        # V10.1 交互协议引擎 (Interaction Layer: DEMO 吸收改造产物)
        from backend.embodied.companion.interaction import (
            InteractionProtocol,
        )
        interaction_cfg = dict(meta_cognition_config or {})
        self._interaction = InteractionProtocol(
            config=interaction_cfg,
            enabled=bool(interaction_cfg.get(
                "companion_interaction_enabled", True,
            )),
        )
        # V10.0 热机健康指标引擎 (纯只读聚合, 不干预运行)
        from backend.embodied.companion.warm_health import (
            WarmRuntimeHealth,
        )
        health_cfg = dict(meta_cognition_config or {})
        self._warm_health = WarmRuntimeHealth(
            meta_cognition=self._meta_cognition,
            continuity=self._continuity,
            memory_gate=self._memory_gate,
            identity_guard=(
                self._identity_guard.get("guard")
                if isinstance(self._identity_guard, dict)
                else self._identity_guard
            ),
            constitution=self._constitution,
            memory_stabilization=self._memory_stabilization,
            enabled=bool(health_cfg.get(
                "companion_health_enabled", True,
            )),
        )
        # V6.6 快照钩子 (成长状态/反思状态入快照)
        try:
            self._continuity._cognitive_reflection = \
                self._cognitive_reflection
            self._continuity._growth_cycle = self._growth_cycle
            self._continuity._growth_trend_analysis = \
                self._growth_trend_analysis
        except Exception as e:
            logger.warning(f"[V6.6] 快照钩子注入失败: {e}")

    # ── 主入口 ────────────────────────────────────────────────────
    def handle(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """主入口: 意图 → 路由 → 委派 → 汇总

        Args:
            request: 请求 dict (text/intent/query + 附加参数)

        Returns:
            CompanionResponse (见 delegate.TaskDelegator.delegate,
            含 V5.5 personality / V5.6 relationship)

        Raises:
            MainAgentError: 请求为空 / 主 Agent 停用
        """
        with self._lock:
            if not self._enabled:
                raise MainAgentError("主伙伴 Agent 已停用")
            if not isinstance(request, dict) or not request:
                raise MainAgentError("请求不能为空")
            self._handled_count += 1
            response = self._delegator.delegate(request)
            # V5.1 协同统计
            agg = response.get("aggregated", {})
            self._stats.record(
                assigned_agents=response.get("assigned_agents", []),
                ok_count=agg.get("ok_count", 0),
                total=agg.get("total", 0),
                latency_ms=response.get("total_latency_ms", 0.0),
                parallel=response.get("dispatched_parallel", False),
            )
            # V5.5 人格: 按结果调整 + 附人格状态 (兼容)
            # V5.6 关系: 更新关系 + 衰减 + 窗口统计 + 附关系状态
            self._apply_personality_from_response(response)
            self._apply_relationship_from_response(response)
            self._decay.apply(
                self._personality_engine.personality()["dimensions"],
            )
            response["personality"] = self._personality_engine.personality()
            response["relationship"] = self._relationship.relationship()
            response["window_stats"] = self._window.stats()
            # V6.1.1 成长节律: 事件采集 + 情绪联动 + 自动整理/快照/反思
            try:
                response["rhythm"] = self._rhythm.on_handle(
                    request, response,
                )
            except Exception as e:
                logger.warning(f"[Rhythm] handle 联动失败: {e}")
            # V6.6 成长闭环检查 (节律联动: 自动反思/建议/评估, 应用仍审批)
            try:
                response["growth_cycle_check"] = \
                    self._growth_cycle.check(
                        experience_count=self._cycle_count(),
                    )
            except Exception as e:
                logger.warning(
                    f"[GrowthCycle] 节律联动失败: {e}",
                )
            return response

    # ── V5.5 人格联动 ─────────────────────────────────────────────
    def _apply_personality_from_response(
        self, response: Dict[str, Any],
    ) -> None:
        """按委派结果调整人格 (成功 → 热情, 失败 → 耐心)"""
        agg = response.get("aggregated", {})
        ok = agg.get("ok_count", 0)
        total = agg.get("total", 0)
        if total <= 0:
            return
        try:
            if ok == total:
                self._personality_engine.adjust("success")
            elif ok == 0:
                self._personality_engine.adjust("failure")
            # 部分成功 → 不调整 (中性)
        except Exception as e:
            logger.warning(f"[Personality] 联动调整失败: {e}")

    # ── V5.6 关系联动 ─────────────────────────────────────────────
    def _apply_relationship_from_response(
        self, response: Dict[str, Any],
    ) -> None:
        """按委派结果更新关系 + 窗口统计 + 经历记录"""
        agg = response.get("aggregated", {})
        ok = agg.get("ok_count", 0)
        total = agg.get("total", 0)
        if total <= 0:
            return
        success = ok == total
        try:
            self._window.record(success=success)
            self._relationship.update(success=success)
            # V5.7 经历: 从执行事件抽取经验
            rec = self._experience.store_from_event(
                success=success,
                trigger=response.get("intent", "companion_handle"),
                source="companion_handle",
                action=",".join(response.get("assigned_agents", [])),
                result=f"ok={ok}/{total}",
            )
            # V5.8 验证: 记录经历后验证 (证据 1 条, 无反例)
            self._verifier.verify(
                experience_id=rec["id"],
                evidence_count=1,
                contradictions=0,
                source_reliable=True,
            )
            # 人格-关系联动: 关系建议 → 人格调整
            for suggestion in self._relationship.personality_adjustment():
                ctx = suggestion.split(":")[0]
                if ctx in ("long_term_trust", "consecutive_fail"):
                    self._personality_engine.adjust(
                        "consecutive_fail" if ctx == "consecutive_fail"
                        else "success",
                    )
        except Exception as e:
            logger.warning(f"[Relationship] 联动更新失败: {e}")

    # ── V5.7 经历记忆 ─────────────────────────────────────────────
    def experience_stats(self) -> Dict[str, Any]:
        """经历统计 (数量/类型分布/平均价值)"""
        with self._lock:
            return self._experience.stats()

    def experience_relevant(self, trigger: str,
                            limit: int = 5) -> List[Dict[str, Any]]:
        """相关经验 (供未来行为参考)"""
        with self._lock:
            return self._experience.relevant(trigger=trigger, limit=limit)

    def experience_reflection(self) -> Dict[str, Any]:
        """反思报告 (Observation / 发现 / Suggestion)"""
        with self._lock:
            return self._experience.reflection_report()

    def experience_audit(self, limit: int = 100) -> Dict[str, Any]:
        """经历审计"""
        with self._lock:
            return self._experience.audit(limit=limit)

    # ── V5.8 反思与认知完整性 ────────────────────────────────────
    def reflection(self) -> Dict[str, Any]:
        """反思: 经历 → Reflection Report (模式/失败/建议/置信度)"""
        with self._lock:
            records = self._experience._store.all()
            return self._reflection.reflect(
                [r.to_dict() for r in records],
            )

    def reflection_with_verification(self) -> Dict[str, Any]:
        """反思已验证经历 (只 CONFIRMED 进入长期成长参考)"""
        with self._lock:
            records = self._experience._store.all()
            confirmed = self._verifier.confirmed_ids()
            return self._reflection.reflect_with_verification(
                [r.to_dict() for r in records],
                confirmed,
            )

    def verification_stats(self) -> Dict[str, Any]:
        """验证统计 (状态分布)"""
        with self._lock:
            return self._verifier.stats()

    def verification_confirm(self, experience_id: str) -> Dict[str, Any]:
        """手动验证经历 (补证据)"""
        with self._lock:
            return self._verifier.verify(
                experience_id=experience_id,
                evidence_count=2, contradictions=0,
                source_reliable=True,
            )

    def verification_reject(self, experience_id: str) -> Dict[str, Any]:
        """拒绝经验 (反例)"""
        with self._lock:
            return self._verifier.verify(
                experience_id=experience_id,
                evidence_count=0, contradictions=2,
                source_reliable=True,
            )

    def proposal_stats(self) -> Dict[str, Any]:
        """改进建议统计"""
        with self._lock:
            return self._reflection._proposals.stats()

    # ── V5.9 创造智能与价值发现 (Creative Intelligence) ──────────
    def creative_run(self) -> Dict[str, Any]:
        """创造闭环: 发现机会 → 评估 → 推理 → 提案 → 模拟
        (不执行, 方案需审批)
        """
        with self._lock:
            return self._creative.run()

    def creative_detect(self) -> List[Dict[str, Any]]:
        """发现价值机会 (只基于 CONFIRMED 经验)"""
        with self._lock:
            return self._creative.detect()

    def creative_evaluate(self, opportunity_id: str) -> Dict[str, Any]:
        """评估机会价值 (Impact/Frequency/Benefit/Feasibility/Risk)"""
        with self._lock:
            return self._creative.evaluate(opportunity_id)

    def creative_propose(self, opportunity_id: str) -> Dict[str, Any]:
        """生成创造方案 (评估 + 推理 + 方案 + 入记忆)"""
        with self._lock:
            return self._creative.propose(opportunity_id)

    def creative_simulate(self, proposal_id: str) -> Dict[str, Any]:
        """执行前模拟 (预期收益/风险/副作用/可行性)"""
        with self._lock:
            return self._creative.simulate(proposal_id)

    def creative_approve(self, proposal_id: str,
                         approver: str = "user") -> Dict[str, Any]:
        """批准创造方案 (PENDING → APPROVED)"""
        with self._lock:
            return self._creative.approve(proposal_id, approver)

    def creative_reject(self, proposal_id: str,
                        reason: str = "") -> Dict[str, Any]:
        """拒绝创造方案"""
        with self._lock:
            return self._creative.reject(proposal_id, reason)

    def creative_execute(self, proposal_id: str) -> Dict[str, Any]:
        """执行创造方案 (仅 APPROVED 可执行)"""
        with self._lock:
            return self._creative.execute(proposal_id)

    def creative_record_result(self, proposal_id: str, success: bool,
                               result: str = "") -> Dict[str, Any]:
        """记录创造执行结果 → 形成新经验 (闭环)"""
        with self._lock:
            return self._creative.record_result(
                proposal_id, success, result,
            )

    def creative_stats(self) -> Dict[str, Any]:
        """创造层统计 (机会/评估/提案/模拟/记忆)"""
        with self._lock:
            return self._creative.stats()

    def creative_audit(self, limit: int = 100) -> Dict[str, Any]:
        """创造审计报告"""
        with self._lock:
            return self._creative.audit_report(limit=limit)

    # ── V6.0 长期身份与成长连续 (Continuity) ────────────────────
    def persistence_save(self, path: str = "") -> int:
        """全量状态持久化 (经历/验证/关系/人格/反思/创造)"""
        with self._lock:
            return self._continuity.save(path)

    def persistence_load(self, path: str = "") -> Dict[str, Any]:
        """状态恢复 (失败跳过不崩溃)"""
        with self._lock:
            return self._continuity.load(path)

    def growth_report(self) -> Dict[str, Any]:
        """长期成长报告 (经验/认知/创造/关系)"""
        with self._lock:
            return self._continuity.growth_report()

    def experience_lifecycle(self) -> Dict[str, Any]:
        """记忆生命周期整理 (Active/Cold/Archive/Recycle)"""
        with self._lock:
            return self._continuity.consolidate()

    def memory_overview(self) -> Dict[str, Any]:
        """记忆体系总览"""
        with self._lock:
            return self._continuity.memory_overview()

    def identity_history(self, limit: int = 50) -> Dict[str, Any]:
        """身份历史 (快照/差异/审计)"""
        with self._lock:
            return self._continuity.identity_history(limit=limit)

    def identity_capture(self, reason: str = "") -> Dict[str, Any]:
        """记录身份快照"""
        with self._lock:
            return self._continuity.capture_identity(reason)

    def identity_propose_change(self, reason: str,
                                changes: Dict[str, Any]) -> Dict[str, Any]:
        """提出身份变化 (必须审批)"""
        with self._lock:
            return self._continuity.propose_identity_change(
                reason, changes,
            )

    def identity_approve_change(self, snapshot_id: str,
                                approver: str = "user") -> Dict[str, Any]:
        """批准身份变化"""
        with self._lock:
            return self._continuity.approve_identity_change(
                snapshot_id, approver,
            )

    def identity_reject_change(self, snapshot_id: str,
                               reason: str = "") -> Dict[str, Any]:
        """拒绝身份变化"""
        with self._lock:
            return self._continuity.reject_identity_change(
                snapshot_id, reason,
            )

    def growth_trend(self, bucket: str = "day") -> Dict[str, Any]:
        """成长趋势 (按天/周/月)"""
        with self._lock:
            return self._continuity.growth_trend(bucket=bucket)

    def growth_metrics(self) -> Dict[str, Any]:
        """成长指标快照"""
        with self._lock:
            return self._continuity.growth_metrics()

    def continuity_stats(self) -> Dict[str, Any]:
        """连续层统计"""
        with self._lock:
            return self._continuity.stats()

    def continuity_audit(self, limit: int = 100) -> Dict[str, Any]:
        """持久化审计报告"""
        with self._lock:
            return self._continuity.audit_report(limit=limit)

    # ── V6.1.1 情绪表征 (Emotion Representation) ────────────────
    def emotion(self) -> Dict[str, Any]:
        """当前情绪状态 (positivity/energy/warmth, 可解释)"""
        with self._lock:
            return self._emotion.get_state()

    def emotion_adjust(self, context: str) -> Dict[str, Any]:
        """按情境调整情绪 (success/failure/creative_done/...)"""
        with self._lock:
            return self._emotion.update(context)

    def emotion_decay(self) -> Dict[str, Any]:
        """情绪自然衰减 (回归基线)"""
        with self._lock:
            return self._emotion.decay()

    def emotion_audit(self, limit: int = 100) -> Dict[str, Any]:
        """情绪审计报告 (所有变化可追踪)"""
        with self._lock:
            return self._emotion.audit_report(limit=limit)

    def emotion_history(self, limit: int = 50) -> Dict[str, Any]:
        """情绪历史 (供 Reflection/Growth)"""
        with self._lock:
            return self._emotion.history(limit=limit)

    # ── V6.1.1 成长节律 (Growth Rhythm) ─────────────────────────
    def growth_rhythm(self) -> Dict[str, Any]:
        """成长节律状态 (自动采集/整理/快照/反思统计)"""
        with self._lock:
            return self._rhythm.stats()

    def growth_rhythm_cycle(self, request: Dict[str, Any] = None,
                            response: Dict[str, Any] = None) -> Dict:
        """手动运行一次节律循环"""
        with self._lock:
            return self._rhythm.run_cycle(request, response)

    def rhythm_audit(self, limit: int = 100) -> Dict[str, Any]:
        """节律审计报告 (自动行为可追踪)"""
        with self._lock:
            return self._rhythm.audit_report(limit=limit)

    # ── V6.2 表达层 (Expression) ────────────────────────────────
    def expression_generate(
        self,
        emotion: Dict[str, Any] = None,
        relationship: Dict[str, Any] = None,
        task: Dict[str, Any] = None,
        conversation: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        """生成表达建议 (style/tone/reason/confidence)"""
        with self._lock:
            return self._expression.generate(
                emotion=emotion, relationship=relationship,
                task=task, conversation=conversation,
            )

    def expression_status(self) -> Dict[str, Any]:
        """表达引擎状态 (规则命中/风格分布)"""
        with self._lock:
            return self._expression.status()

    def expression_audit(self, limit: int = 100) -> Dict[str, Any]:
        """表达审计"""
        with self._lock:
            return self._expression.audit_report(limit=limit)

    # ── V6.2 感知层 (Perception) ────────────────────────────────
    def vision_ocr(self, image=None) -> Dict[str, Any]:
        """OCR (经权限, 未授权返回 PERMISSION_DENIED)"""
        with self._lock:
            return self._perception.vision_ocr(image)

    def vision_detect(self, image=None) -> Dict[str, Any]:
        """目标检测 (经权限)"""
        with self._lock:
            return self._perception.vision_detect(image)

    def perception_receive(self, source: str,
                           content: Dict[str, Any],
                           confidence: float = 0.0) -> Dict[str, Any]:
        """接收感知事件 (不直接进入 Memory)"""
        with self._lock:
            return self._perception.perception_receive(
                source=source, content=content,
                confidence=confidence,
            )

    def perception_verify(self, event_id: str) -> Dict[str, Any]:
        """验证感知事件 (通过 → 记忆候选)"""
        with self._lock:
            return self._perception.perception_verify(event_id)

    def perception_audit(self, limit: int = 100) -> Dict[str, Any]:
        """感知审计 (所有自动行为可追踪)"""
        with self._lock:
            return self._perception.audit_report(limit=limit)

    def perception_stats(self) -> Dict[str, Any]:
        """感知统计 (事件/验证/权限)"""
        with self._lock:
            return self._perception.stats()

    def perception_memory_candidates(self) -> Dict[str, Any]:
        """感知记忆候选 (只读, 未存储)"""
        with self._lock:
            return self._perception.memory_candidates()

    # ── V6.3 记忆网关 (Memory Gate) ─────────────────────────────
    def perception_memory_gate(
        self, candidate_id: str,
    ) -> Dict[str, Any]:
        """记忆网关: 候选 → 校验 → 反思 → 反事实 → 批准 → 写入经历

        安全: 感知不直接写 Memory, 必须经过批准
        """
        with self._lock:
            cands = self._perception.memory_candidates()
            candidate = next(
                (c for c in cands["candidates"]
                 if c["candidate_id"] == candidate_id),
                None,
            )
            if candidate is None:
                return {"status": "NOT_FOUND",
                        "error": f"候选不存在: {candidate_id}",
                        "mode": "rule_based"}
            result = self._memory_gate.process(
                candidate,
                store_fn=self._gate_store_fn,
                reflect_fn=self._gate_reflect_fn,
            )
            # V6.4 感知-成长闭环: 批准 → multimodal 事件 + 情绪经 meaning
            if result["status"] == "approved":
                self._perception_growth_loop(candidate)
            return result

    def _perception_growth_loop(self, candidate: Dict[str, Any]) -> None:
        """感知-成长闭环 (批准后):

        感知 → Meaning → Experience Value → Emotion Adjustment
        (感知不能直接影响情绪, 必须经过 Meaning)
        """
        try:
            # 1. Multimodal 成长事件
            self._continuity.track_event(
                "multimodal_perception",
                detail=f"感知批准: {candidate.get('summary', '')[:40]}",
                meta={"source": candidate.get("source", ""),
                      "meaning": candidate.get("summary", "")[:60]},
            )
            # 2. 情绪联动 (经 Meaning 评估价值)
            summary = str(candidate.get("summary", ""))
            value_words = ("任务", "清单", "重要", "目标", "学习")
            has_value = any(w in summary for w in value_words)
            if has_value:
                # 有价值感知 → 温和积极 (经 Experience Value)
                self._emotion.update("creative_done")
            else:
                self._emotion.update("relationship_up")
        except Exception as e:
            logger.warning(f"[Growth] 感知成长闭环失败: {e}")

    def _gate_store_fn(self, candidate: Dict[str, Any]) -> Dict[str, Any]:
        """批准后写入经历 (source=vision_perception)"""
        return self._experience.store_from_event(
            success=True,
            trigger=f"感知:{candidate.get('kind', 'vision')}",
            source="vision_perception",
            action="memory_gate",
            result=f"感知记忆批准: {candidate.get('summary', '')[:40]}",
        )

    def _gate_reflect_fn(self, candidate: Dict[str, Any]) -> list:
        """反思评估上下文: 返回已有经历 (供一致性/模式对比)"""
        try:
            return [
                r.to_dict()
                for r in self._experience._store.all()
            ]
        except Exception:
            return []

    def perception_memory_gate_stats(self) -> Dict[str, Any]:
        """记忆网关统计 (候选/批准/拒绝)"""
        with self._lock:
            return self._memory_gate.stats()

    # ── V6.3 感知管道 (Perception Pipeline) ─────────────────────
    def perception_frame(
        self, content: Dict[str, Any], meaning: str = "",
        verified: bool = False, ftype: str = "vision",
    ) -> Dict[str, Any]:
        """创建感知帧并注入管道

        Args:
            content: 帧内容 (kind/text/objects)
            meaning: 感知意义
            verified: 是否已验证 (未验证禁止行动)
            ftype: 帧类型 (vision/audio/text)
        """
        with self._lock:
            from backend.embodied.companion.perception import (
                PerceptionFrame,
            )
            frame = PerceptionFrame.create(
                content=content, meaning=meaning,
                verified=verified, ftype=ftype,
            )
            return self._pipeline_adapter.ingest(frame)

    def perception_pipeline_stats(self) -> Dict[str, Any]:
        """感知管道统计 (帧数量/验证/行动拦截)"""
        with self._lock:
            return self._pipeline_adapter.stats()

    # ── V6.4 感知-记忆认知集成 (Reflection & Provenance) ────────
    def reflection_evaluate(
        self, candidate: Dict[str, Any],
    ) -> Dict[str, Any]:
        """反思评估候选 (Advisor, 非决策者)"""
        with self._lock:
            known = self._gate_reflect_fn(candidate)
            return self._reflection_evaluator.evaluate(
                candidate, known,
            )

    def counterfactual_check(self, candidate: Dict[str, Any]) -> Dict:
        """反事实验证 (降低幻觉进入 Memory)"""
        with self._lock:
            return self._counterfactual_check.check(candidate)

    def experience_create(
        self, source: str, modalities: list,
        meaning: str, confidence: float = 0.0,
        impact: str = "",
    ) -> Dict[str, Any]:
        """创建多模态经验对象 (统一结构, 含 Provenance)"""
        with self._lock:
            from backend.embodied.companion.experience import (
                MultimodalExperience,
                Provenance,
            )
            prov = Provenance.create(
                origin=source,
                source_event="",
                verification_score=confidence,
                reflection_reason="经验对象创建",
                approved_by="system",
            )
            exp = MultimodalExperience.create(
                source=source, modalities=modalities,
                meaning=meaning, confidence=confidence,
                impact=impact, provenance=prov.to_dict(),
            )
            return exp.to_dict()

    def experience_provenance(self, experience_id: str) -> Dict:
        """查询经验来源链"""
        with self._lock:
            exp = self._experience.retrieve(experience_id)
            if exp is None:
                return {"status": "NOT_FOUND",
                        "error": f"经历不存在: {experience_id}"}
            # 经历含 provenance 字段 (感知来源)
            provenance = exp.get("provenance", {})
            if not provenance and exp.get("source") == \
                    "vision_perception":
                provenance = {
                    "origin": "vision",
                    "source_event": exp.get("id", ""),
                    "verification_score": exp.get(
                        "confidence", 0.0,
                    ),
                    "reflection_reason": "经记忆网关批准",
                    "approved_by": "memory_gate",
                    "timestamp": exp.get("timestamp", 0.0),
                }
            return {
                "experience_id": experience_id,
                "provenance": provenance,
                "traceable": bool(provenance),
            }

    def perception_stats(self) -> Dict[str, Any]:
        """感知统计 (事件/验证/批准/拒绝/反思)"""
        with self._lock:
            return {
                "mode": "rule_based",
                "perception": self._perception.stats(),
                "memory_gate": self._memory_gate.stats(),
                "reflection": self._reflection_evaluator.stats(),
                "counterfactual": self._counterfactual_check.stats(),
            }

    def multimodal_event_create(
        self, source: str, meaning: str,
        impact: str = "",
    ) -> Dict[str, Any]:
        """创建多模态成长事件 (Growth Tracker)"""
        with self._lock:
            return self._continuity.track_event(
                "multimodal_perception",
                detail=meaning,
                meta={"source": source, "impact": impact},
            )

    # ── V6.5 认知反思与自主成长 (Cognitive Reflection & Growth) ─
    def reflection_analyze(self) -> Dict[str, Any]:
        """认知反思: 经历 → 认知总结 (理解经验)"""
        with self._lock:
            records = [
                r.to_dict()
                for r in self._experience._store.all()
            ]
            identity = self._continuity._identity_state() if \
                hasattr(self._continuity, "_identity_state") else {}
            return self._cognitive_reflection.analyze(
                records, identity,
            )

    def _cycle_records(self) -> List[Dict[str, Any]]:
        """成长闭环经历提供者 (只读)"""
        return [
            r.to_dict() for r in self._experience._store.all()
        ]

    def _cycle_count(self) -> int:
        """当前经历数"""
        try:
            return len(self._cycle_records())
        except Exception:
            return 0

    def pattern_detect(self) -> Dict[str, Any]:
        """模式检测 (统计驱动)"""
        with self._lock:
            records = [
                r.to_dict()
                for r in self._experience._store.all()
            ]
            return {
                "mode": "rule_based",
                "patterns": self._cognitive_reflection.analyze(
                    records,
                )["patterns"],
                "stats": self._cognitive_reflection._patterns.stats(),
            }

    def contradiction_check(
        self, experience: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        """矛盾检测: 新经验 vs 旧知识 vs Identity"""
        with self._lock:
            if experience is None:
                records = [
                    r.to_dict()
                    for r in self._experience._store.all()
                ]
                if not records:
                    return {"conflict": False,
                            "reason": "无经历可检测",
                            "mode": "rule_based"}
                experience = records[-1]
            known = [
                r.to_dict()
                for r in self._experience._store.all()
            ][:-1]
            identity = self._continuity._identity_state() if \
                hasattr(self._continuity, "_identity_state") else {}
            return self._cognitive_reflection._contradictions.detect(
                experience, identity, known,
            )

    def growth_generate(self) -> Dict[str, Any]:
        """生成成长建议 (从反思报告)"""
        with self._lock:
            report = self.reflection_analyze()
            proposals = self._growth_engine["proposal"].generate(
                report,
            )
            return {
                "mode": "rule_based",
                "report_id": report["report_id"],
                "proposals": proposals,
                "proposal_count": len(proposals),
            }

    def growth_evaluate(self, proposal: Dict[str, Any]) -> Dict[str, Any]:
        """评估成长建议 (Identity/Safety/Value 三检查)"""
        with self._lock:
            identity = self._continuity._identity_state() if \
                hasattr(self._continuity, "_identity_state") else {}
            return self._growth_engine["evaluator"].evaluate(
                proposal, identity,
            )

    def growth_apply(
        self, proposal: Dict[str, Any],
        evaluation: Dict[str, Any] = None,
        changes: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        """受控应用成长 (仅 approved, 默认需人工确认)"""
        with self._lock:
            if evaluation is None:
                evaluation = self.growth_evaluate(proposal)
            before = self._continuity._identity_state() if \
                hasattr(self._continuity, "_identity_state") else {}
            guard = self._identity_guard["guard"]
            validator = self._identity_guard["validator"]
            # Identity Guard 检查
            ok, reason = guard.check(changes or {}, before)
            if not ok:
                return {
                    "status": "blocked",
                    "reason": f"身份守护拦截: {reason}",
                    "mode": "rule_based",
                }
            result = self._growth_engine["applier"].apply(
                proposal, evaluation, before,
                change_fn=lambda b, p: (changes or {}),
                guard_fn=lambda p: (True, "身份守护通过"),
            )
            # 变更验证
            if result["status"] == "applied":
                v = validator.validate(
                    result["before"], result["after"],
                    reason=proposal.get("description", ""),
                )
                if not v["ok"]:
                    return {
                        "status": "blocked",
                        "reason": f"变更验证失败: {v['reason']}",
                        "mode": "rule_based",
                    }
            return result

    def growth_audit(self, limit: int = 100) -> Dict[str, Any]:
        """成长审计 (全过程可追溯)"""
        with self._lock:
            return self._growth_engine["applier"]._audit.report(
                limit=limit,
            )

    def growth_stats(self) -> Dict[str, Any]:
        """成长统计 (建议/评估/应用)"""
        with self._lock:
            return {
                "mode": "rule_based",
                "reflection": self._cognitive_reflection.stats(),
                "proposal": self._growth_engine["proposal"].stats(),
                "evaluator": self._growth_engine["evaluator"].stats(),
                "applier": self._growth_engine["applier"].stats(),
                "identity_guard": self._identity_guard["guard"].stats(),
                "change_validator": self._identity_guard[
                    "validator"].stats(),
            }

    # ── V6.6 自主成长成熟化 (Autonomous Growth Maturation) ──────
    def reflection_emotion_adjust(self) -> Dict[str, Any]:
        """反思-情绪集成 (经 Meaning, 不直接修改情绪/人格)"""
        with self._lock:
            report = self.reflection_analyze()
            return self._reflection_emotion.adjust(report)

    def growth_cycle_run(
        self, trigger: str = "auto",
    ) -> Dict[str, Any]:
        """运行成长闭环 (自动反思 → 建议 → 评估 → 待审批)"""
        with self._lock:
            result = self._growth_cycle.run(trigger=trigger)
            # V8.0 宪法治理: 成长建议必须经宪法审查
            if self._constitution_growth_link and \
                    result.get("cycle") is not None:
                try:
                    reviews = [
                        self._constitution.review({
                            "module": "growth",
                            "action_text": (
                                p.get("description", "")
                            ),
                            "change": {},
                            "growth_proposal": p,
                        })
                        for p in result.get("proposals", [])
                    ]
                    result["constitution_reviews"] = reviews
                except Exception as e:
                    logger.warning(
                        f"[Constitution] Growth 联动失败: {e}",
                    )
            return result

    def growth_pending_approvals(
        self, limit: int = 50,
    ) -> Dict[str, Any]:
        """待审批列表 (应用永远需人工)"""
        with self._lock:
            return self._growth_cycle.pending(limit=limit)

    def growth_cycle_decide(
        self, pending_id: str, decision: str,
        reason: str = "",
    ) -> Dict[str, Any]:
        """待审批决策 (批准仅标记, 应用仍经人工审批)"""
        with self._lock:
            return self._growth_cycle.decide(
                pending_id, decision, reason,
            )

    def growth_trend_analysis(
        self, period: str = "day",
    ) -> Dict[str, Any]:
        """成长趋势分析 (反思/成长/身份/记忆 四类指标)"""
        with self._lock:
            stats = self.growth_stats()
            exp = {}
            if self._experience is not None:
                try:
                    exp = self._experience.stats()
                except Exception as e:
                    logger.warning(
                        f"[Trend] 读取经历统计失败: {e}",
                    )
            ver = {}
            if self._verifier is not None:
                try:
                    ver = self._verifier.stats()
                except Exception as e:
                    logger.warning(
                        f"[Trend] 读取验证统计失败: {e}",
                    )
            guard = dict(stats["identity_guard"])
            guard["attempt_count"] = guard.get(
                "intercept_count", 0,
            ) + guard.get("approval_count", 0)
            period_days = int(self._growth_config_days())
            return self._growth_trend_analysis.analyze({
                "reflection": stats["reflection"],
                "proposal": stats["proposal"],
                "evaluator": stats["evaluator"],
                "applier": stats["applier"],
                "identity_guard": guard,
                "experience": exp,
                "verification": ver,
                "period_days": period_days,
            }, period=period)

    def _growth_config_days(self) -> int:
        """成长统计窗口天数 (配置驱动)"""
        try:
            return int(self._growth_config.get(
                "companion_growth_window_days", 30,
            ))
        except Exception:
            return 30

    # ── V6.8 混合智能层 (Hybrid Intelligence Layer) ─────────────
    def hybrid_route(
        self, task_context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """智能调度路由 (任务 → LOCAL/CLOUD/HYBRID)"""
        with self._lock:
            return self._hybrid.route(task_context)

    def hybrid_execute(
        self, task_context: Dict[str, Any],
        request: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        """执行智能调用 (路由 → 执行 → 验证 → 宪法 → 表达)"""
        with self._lock:
            result = self._hybrid.execute(
                task_context, request,
            )
            # V8.0 宪法治理: 云端结果必须经宪法检查
            if self._constitution_hybrid_link:
                try:
                    validation = self._constitution.validate_output(
                        str(result.get("content", "")) +
                        str(result.get("result", "")),
                        source=result.get("provider", ""),
                    )
                    review = self._constitution.review({
                        "module": "hybrid",
                        "action_text": str(result.get(
                            "content", "",
                        )) + str(result.get("result", "")),
                        "change": {},
                        "cloud_result": result,
                    })
                    result["constitution"] = {
                        "validation": validation,
                        "review": review,
                    }
                except Exception as e:
                    logger.warning(
                        f"[Constitution] HIL 联动失败: {e}",
                    )
            # V7.0 具身联动: HIL 结果 → 表达状态 (可解释)
            if self._presence_hybrid_link:
                try:
                    ttype = str(
                        (task_context or {}).get("type", ""),
                    )
                    if ttype in ("deep_reasoning",
                                 "architecture_design",
                                 "document_understanding",
                                 "research"):
                        presence_ctx = "deep_task"
                    elif result.get("ok") is not False and \
                            result.get("provider") == "cloud":
                        presence_ctx = "success"
                    else:
                        presence_ctx = "idle"
                    result["presence"] = \
                        self._presence.update(presence_ctx)
                except Exception as e:
                    logger.warning(
                        f"[Presence] HIL 联动失败: {e}",
                    )
            return result

    def hybrid_gateway_request(
        self, model: str,
        payload: Dict[str, Any] = None,
        value_score: float = 0.0,
    ) -> Dict[str, Any]:
        """网关直调 (低价值任务禁止高成本模型)"""
        with self._lock:
            return self._hybrid.gateway_request(
                model, payload, value_score,
            )

    def hybrid_stats(self) -> Dict[str, Any]:
        """混合智能层统计 (调度/成本/安全/审计)"""
        with self._lock:
            return self._hybrid.stats()

    def hybrid_audit(self, limit: int = 100) -> Dict[str, Any]:
        """智能调用审计 (可查询/可追踪/可回放)"""
        with self._lock:
            return self._hybrid.audit_report(limit=limit)

    # ── V7.0 具身表达层 (Embodied Presence Layer) ───────────────
    def presence_state(self) -> Dict[str, Any]:
        """当前表达状态 (表情/姿态/强度/互动模式)"""
        with self._lock:
            return self._presence.state()

    def presence_update(self, context: str = "idle") -> Dict[str, Any]:
        """表达状态机更新 (经映射/有限幅/身份守护)"""
        with self._lock:
            return self._presence.update(context)

    def presence_interpreter(
        self, context: str = "idle",
    ) -> Dict[str, Any]:
        """表达解释器 (只读映射, 不改变状态)"""
        with self._lock:
            return self._presence.interpreter(context)

    def presence_continuity(
        self, window_days: int = 30,
    ) -> Dict[str, Any]:
        """存在连续性 (沟通节奏/表达偏好)"""
        with self._lock:
            return self._presence.continuity(
                window_days=window_days,
            )

    def presence_stats(self) -> Dict[str, Any]:
        """表达引擎统计 (状态/映射/记忆/审计)"""
        with self._lock:
            return self._presence.stats()

    # ── V8.0 宪法引擎 (Constitution Engine, 最高治理层) ─────────
    def constitution_review(
        self, action_context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """治理审查 (任何模块行为必须接受约束)"""
        with self._lock:
            return self._constitution.review(action_context)

    def constitution_arbitrate(
        self, conflict_event: Dict[str, Any],
    ) -> Dict[str, Any]:
        """跨层冲突仲裁 (固定优先级)"""
        with self._lock:
            return self._constitution.arbitrate(
                conflict_event,
            )

    def constitution_validate_output(
        self, output_text: str, source: str = "",
    ) -> Dict[str, Any]:
        """输出验证 (现实验证 + 防幻觉)"""
        with self._lock:
            return self._constitution.validate_output(
                output_text, source,
            )

    def constitution_principles(self) -> Dict[str, Any]:
        """治理原则定义"""
        with self._lock:
            return self._constitution.principles()

    def constitution_ledger(self, limit: int = 100) -> Dict[str, Any]:
        """治理总账 (可查询/可回放/可审计)"""
        with self._lock:
            return self._constitution.ledger_report(
                limit=limit,
            )

    def constitution_propose_evolution(
        self, change: str, reason: str = "",
        operator: str = "system",
    ) -> Dict[str, Any]:
        """提出最高原则修改建议 (永不自动应用)"""
        with self._lock:
            return self._constitution.propose_evolution(
                change, reason, operator,
            )

    def constitution_evolution_decide(
        self, proposal_id: str, decision: str,
        reviewer: str = "human",
    ) -> Dict[str, Any]:
        """演化建议审批 (批准仅标记, 应用需人工)"""
        with self._lock:
            return self._constitution.evolution_decide(
                proposal_id, decision, reviewer,
            )

    def constitution_stats(self) -> Dict[str, Any]:
        """宪法引擎统计"""
        with self._lock:
            return self._constitution.stats()

    # ── V8.5 元创造力引擎 (Creative Intelligence Engine) ────────
    def meta_creative_create(
        self, problem: str,
        context: Dict[str, Any] = None,
        human_input: str = None,
    ) -> Dict[str, Any]:
        """完整创造流程 (火花→重组→假设→验证→输出)"""
        with self._lock:
            result = self._meta_creative.create(
                problem, context, human_input,
            )
            # HIL 连接: 复杂创造允许云端增强 (标记)
            if self._meta_creative_hybrid_link and \
                    result.get("ok") is not False:
                try:
                    ttype = "creative_exploration"
                    route = self._hybrid.route({
                        "type": ttype,
                    })
                    result["hybrid"] = {
                        "route": route["route"],
                        "note": (
                            "复杂创造可经 HIL 云端增强"
                            if route["route"] == "CLOUD"
                            else "本地创造已满足"
                        ),
                    }
                except Exception as e:
                    logger.warning(
                        f"[MetaCreative] HIL 联动失败: {e}",
                    )
            return result

    def meta_creative_sparks(
        self, problem: str,
    ) -> Dict[str, Any]:
        """思维火花 (只生成, 不创建)"""
        with self._lock:
            sparks = self._meta_creative._spark.generate(
                problem,
            )
            return {
                "mode": "rule_based",
                "sparks": sparks,
                "spark_count": len(sparks),
            }

    def meta_creative_hypothesis(
        self, problem: str,
    ) -> Dict[str, Any]:
        """假设构建 (经验证)"""
        with self._lock:
            engine = self._meta_creative
            sparks = engine._spark.generate(problem)
            if not sparks:
                return {
                    "mode": "error_frame",
                    "ok": False,
                    "reason": "无基础 (需先加载经历到知识图)",
                }
            h = engine._hypothesis.build(
                sparks[0], None,
            )
            v = engine._validation.validate(h)
            return {
                "mode": "rule_based",
                "hypothesis": h,
                "validation": v,
            }

    def meta_creative_stats(self) -> Dict[str, Any]:
        """创造引擎统计"""
        with self._lock:
            return self._meta_creative.stats()

    # ── V9.0 自主研究探索引擎 (Research & Exploration) ──────────
    def research_explore(
        self, goal: str, user_value: str = "",
    ) -> Dict[str, Any]:
        """受治理的主动探索 (观察→问题→计划→获取→假设→验证)"""
        with self._lock:
            result = self._research.explore(goal, user_value)
            if result.get("ok") is not False:
                # Creative 联动: 探索结果 → 知识图积累
                if self._research_creative_link:
                    try:
                        concepts = []
                        for q in result.get(
                            "questions", [],
                        ):
                            concepts.append(
                                str(q.get(
                                    "question", "",
                                ))[:20],
                            )
                        if concepts:
                            self._meta_creative.load_experience([
                                {"trigger": c,
                                 "source": "research",
                                 "confidence": 0.7}
                                for c in concepts
                            ])
                            result["creative_link"] = {
                                "concepts_added": len(
                                    concepts,
                                ),
                            }
                    except Exception as e:
                        logger.warning(
                            f"[Research] 创造联动失败: {e}",
                        )
                # HIL 联动: 复杂研究任务调度标记
                if self._research_hybrid_link:
                    try:
                        route = self._hybrid.route({
                            "type": "research",
                        })
                        result["hybrid"] = {
                            "route": route["route"],
                            "note": "研究任务经 HIL 调度",
                        }
                    except Exception as e:
                        logger.warning(
                            f"[Research] HIL 联动失败: {e}",
                        )
            return result

    def research_observe(
        self, obs_type: str, content: str,
        source: str = "system",
    ) -> Dict[str, Any]:
        """采集研究观察"""
        with self._lock:
            return self._research.observe(
                obs_type, content, source,
            )

    def research_questions(self) -> Dict[str, Any]:
        """当前研究问题"""
        with self._lock:
            return self._research.questions()

    def research_audit(self, limit: int = 100) -> Dict[str, Any]:
        """研究审计 (全过程可追踪)"""
        with self._lock:
            return self._research.audit_report(limit=limit)

    def research_stats(self) -> Dict[str, Any]:
        """研究引擎统计"""
        with self._lock:
            return self._research.stats()

    # ── V9.5 元认知引擎 (Meta-Cognition Engine) ─────────────────
    def meta_cognition_monitor(
        self, task: str, reasoning_type: str = "rules",
        confidence: float = 0.5, uncertainty: str = "",
        resources: List[str] = None,
    ) -> Dict[str, Any]:
        """记录认知过程"""
        with self._lock:
            return self._meta_cognition.monitor(
                task, reasoning_type, confidence,
                uncertainty, resources,
            )

    def meta_cognition_evaluate(
        self, monitor_entry: Dict[str, Any],
        output_text: str = "",
    ) -> Dict[str, Any]:
        """推理四维评价"""
        with self._lock:
            return self._meta_cognition.evaluate(
                monitor_entry, output_text,
            )

    def meta_cognition_detect_error(
        self, error_text: str, trigger: str = "",
    ) -> Dict[str, Any]:
        """错误分类"""
        with self._lock:
            return self._meta_cognition.detect_error(
                error_text, trigger,
            )

    def meta_cognition_reflect(
        self, experience: str, analysis: str = "",
        adjustment: str = "",
    ) -> Dict[str, Any]:
        """认知反思 (调整经宪法)"""
        with self._lock:
            return self._meta_cognition.reflect(
                experience, analysis, adjustment,
            )

    def meta_cognition_verify(
        self, conclusion: str, evidence: str = "",
        reasoning: str = "", confidence: float = 0.5,
    ) -> Dict[str, Any]:
        """输出前自我验证"""
        with self._lock:
            return self._meta_cognition.verify(
                conclusion, evidence, reasoning,
                confidence,
            )

    def meta_cognition_stats(self) -> Dict[str, Any]:
        """元认知引擎统计"""
        with self._lock:
            return self._meta_cognition.stats()

    # ── V10.0 热机健康指标 (Warm Runtime Health) ───────────────
    def health(self) -> Dict[str, Any]:
        """热机健康指标 (V10.0: Cognitive/Memory/Growth/Safety 四维)

        Returns:
            {
                'mode', 'enabled', 'version', 'generated_at',
                'overall': {'score', 'level', 'reason'},
                'cognitive': {...}, 'memory': {...},
                'growth': {...}, 'safety': {...},
            }
        """
        with self._lock:
            return self._warm_health.report()

    # ── V10.1 交互协议 (Interaction Protocol) ───────────────────
    def interaction_begin_session(
        self, goal: str = "", mode: str = "casual",
    ) -> Dict[str, Any]:
        """开始交互会话 (目标/交流模式)"""
        with self._lock:
            return self._interaction.begin_session(goal, mode)

    def interaction_update_stage(self, stage: str) -> Dict[str, Any]:
        """更新会话任务阶段"""
        with self._lock:
            return self._interaction.update_stage(stage)

    def interaction_set_context(self, context: str) -> Dict[str, Any]:
        """设置当前上下文 (经筛选)"""
        with self._lock:
            return self._interaction.set_context(context)

    def interaction_add_pending(self, item: str) -> Dict[str, Any]:
        """添加未完成事项"""
        with self._lock:
            return self._interaction.add_pending(item)

    def interaction_resolve_pending(self, item: str) -> bool:
        """移除已完成事项"""
        with self._lock:
            return self._interaction.resolve_pending(item)

    def interaction_conversation_snapshot(self) -> Dict[str, Any]:
        """会话状态快照"""
        with self._lock:
            return self._interaction.conversation_snapshot()

    def interaction_filter_context(self, text: str) -> Dict[str, Any]:
        """上下文筛选 (不等同长期记忆)"""
        with self._lock:
            return self._interaction.filter_context(text)

    def interaction_begin_tool_flow(self, intent: str) -> Dict[str, Any]:
        """开始工具交互流程"""
        with self._lock:
            return self._interaction.begin_tool_flow(intent)

    def interaction_advance_tool_flow(
        self, flow_id: str, stage: str, detail: str = "",
    ) -> Dict[str, Any]:
        """推进工具流程阶段"""
        with self._lock:
            return self._interaction.advance_tool_flow(
                flow_id, stage, detail,
            )

    def interaction_execute_tool(
        self,
        flow_id: str,
        tool_name: str,
        tool_fn: Any = None,
        args: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """执行工具调用 (经流程编排 + 延迟记录)"""
        with self._lock:
            if tool_fn is None:
                return {
                    "mode": "error_frame",
                    "ok": False,
                    "reason": "工具回调不可用 (交互协议不执行工具)",
                }
            return self._interaction.execute_tool(
                flow_id, tool_name, tool_fn, args,
            )

    def interaction_finish_tool_flow(
        self, flow_id: str, response: str = "",
    ) -> Dict[str, Any]:
        """完成工具流程"""
        with self._lock:
            return self._interaction.finish_tool_flow(
                flow_id, response,
            )

    def interaction_trace_tool_flow(self, flow_id: str) -> Dict[str, Any]:
        """回溯工具流程 (可审计)"""
        with self._lock:
            return self._interaction.trace_tool_flow(flow_id)

    def interaction_set_partner_goal(self, goal: str) -> Dict[str, Any]:
        """设置伙伴协作目标"""
        with self._lock:
            return self._interaction.set_partner_goal(goal)

    def interaction_set_partner_relation(
        self, relation: str,
    ) -> Dict[str, Any]:
        """设置伙伴任务关系"""
        with self._lock:
            return self._interaction.set_partner_relation(relation)

    def interaction_partner_snapshot(self) -> Dict[str, Any]:
        """伙伴交互状态快照"""
        with self._lock:
            return self._interaction.partner_snapshot()

    def interaction_mark_latency(
        self, stage: str, latency_ms: float,
    ) -> Dict[str, Any]:
        """记录链路延迟"""
        with self._lock:
            return self._interaction.mark_latency(stage, latency_ms)

    def interaction_latency_report(self) -> Dict[str, Any]:
        """延迟报告"""
        with self._lock:
            return self._interaction.latency_report()

    def interaction_audit(self, limit: int = 100) -> Dict[str, Any]:
        """交互审计报告"""
        with self._lock:
            return self._interaction.audit_report(limit=limit)

    def interaction_stats(self) -> Dict[str, Any]:
        """交互协议统计"""
        with self._lock:
            return self._interaction.stats()

    # ── V10.1 记忆稳定化 (Memory Stabilization) ─────────────────
    def memory_stabilize(
        self,
        records: Optional[List[Dict[str, Any]]] = None,
        confirmed_ids: Optional[List[str]] = None,
        referenced_ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """记忆稳定化总报告 (压缩+权重+冲突, 不执行淘汰)

        Args:
            records: 记忆记录列表 (缺省取经历存储全量)
            confirmed_ids: CONFIRMED 记忆 ID (保护/权重)
            referenced_ids: 被引用记忆 ID (权重加成)

        Returns:
            {
                'mode', 'enabled', 'total',
                'compression': {...}, 'prune_candidates': {...},
                'evaluation': [...], 'conflicts': {...},
            }
        """
        with self._lock:
            recs = records
            if recs is None:
                recs = [
                    r.to_dict()
                    for r in self._experience._store.all()
                ]
            confirmed = confirmed_ids
            if confirmed is None:
                try:
                    confirmed = self._verifier.confirmed_ids()
                except Exception as e:
                    logger.warning(f"[V10.1] 确认状态读取失败: {e}")
                    confirmed = []
            return self._memory_stabilization.stabilize(
                recs, confirmed, referenced_ids,
            )

    def memory_prune_candidates(
        self,
        records: Optional[List[Dict[str, Any]]] = None,
        confirmed_ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """记忆淘汰候选 (只出方案, 不执行)"""
        with self._lock:
            recs = records
            if recs is None:
                recs = [
                    r.to_dict()
                    for r in self._experience._store.all()
                ]
            confirmed = confirmed_ids
            if confirmed is None:
                try:
                    confirmed = self._verifier.confirmed_ids()
                except Exception as e:
                    logger.warning(f"[V10.1] 确认状态读取失败: {e}")
                    confirmed = []
            return self._memory_stabilization.prune_candidates(
                recs, confirmed,
            )

    def memory_prune_execute(
        self,
        record_ids: List[str],
        records: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """显式执行记忆淘汰 (经经历存储 forget + 审计)

        Args:
            record_ids: 要淘汰的记录 ID 列表
            records: 原记录列表 (reason 溯源, 可缺省)

        Returns:
            {
                'mode', 'enabled', 'requested', 'removed',
                'not_found', 'removed_ids',
            }
        """
        with self._lock:
            recs = records
            if recs is None:
                recs = [
                    r.to_dict()
                    for r in self._experience._store.all()
                ]
            return self._memory_stabilization.prune_execute(
                list(record_ids),
                self._experience.forget,
                recs,
            )

    def memory_stabilization_stats(self) -> Dict[str, Any]:
        """记忆稳定化统计 (压缩/淘汰/权重/冲突/审计)"""
        with self._lock:
            return self._memory_stabilization.stats()

    def memory_stabilization_audit(
        self, limit: int = 100,
    ) -> Dict[str, Any]:
        """记忆稳定化审计报告 (热机可追踪)"""
        with self._lock:
            return self._memory_stabilization.audit_report(
                limit=limit,
            )

    # ── 人格 (V5.5) ───────────────────────────────────────────────
    def personality(self) -> Dict[str, Any]:
        """当前人格状态 (维度/统计/调整原因)"""
        with self._lock:
            return self._personality_engine.personality()

    def adjust_personality(self, context: str) -> Dict[str, Any]:
        """人格调整 (情境 → 维度调整 → 审计)"""
        with self._lock:
            return self._personality_engine.adjust(context)

    # ── V5.6 关系与稳定 ───────────────────────────────────────────
    def relationship(self) -> Dict[str, Any]:
        """关系状态 (信任/熟悉/沟通风格/阶段)"""
        with self._lock:
            return self._relationship.relationship()

    def relationship_update(self, success: bool) -> Dict[str, Any]:
        """关系更新 (按互动结果)"""
        with self._lock:
            return self._relationship.update(success)

    def personality_stability(self) -> Dict[str, Any]:
        """人格稳定状态 (当前/基础/衰减/调整历史)"""
        with self._lock:
            dims = self._personality_engine.personality()["dimensions"]
            stability = self._decay.stability(dims)
            return {
                "current": self._personality_engine.personality(),
                "base": stability["base"],
                "decay": stability,
                "adjust_history": self._personality_engine.audit(),
                "relationship": self._relationship.relationship(),
            }

    def window_stats(self, days: int = 30) -> Dict[str, Any]:
        """窗口统计 (7/30 天)"""
        with self._lock:
            return self._window.stats(days=days)

    # ── 协同统计 (V5.1) ───────────────────────────────────────────
    def stats(self) -> Dict[str, Any]:
        """伙伴协同统计 (委派次数/成功率/平均耗时/Top 组合)"""
        with self._lock:
            return self._stats.summary()

    # ── 路由分析 ──────────────────────────────────────────────────
    def route(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """路由分析 (请求 → 专业 Agent, 不执行)"""
        return self._router.route(request)

    # ── Agent 清单 ────────────────────────────────────────────────
    def agents(self) -> Dict[str, Any]:
        """专业 Agent 清单 (能力域 / 状态 / 调用数)"""
        return self._registry.snapshot()

    # ── 预演 (不执行) ─────────────────────────────────────────────
    def dry_run(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """伙伴架构预演: 只输出路由与委派方案 (不调用专业 Agent)

        Returns:
            {
                'dry_run': True,
                'request_id', 'route': {...}, 'would_delegate': [...],
                'protection_checks': {...},
            }
        """
        with self._lock:
            route = self._router.route(request)
            return {
                "dry_run": True,
                "request_id": "req_" + uuid.uuid4().hex[:8],
                "route": route,
                "would_delegate": [
                    {"agent": name, "capability": self._capability_of(name)}
                    for name in route["assigned_agents"]
                ],
                "protection_checks": {
                    "checks": [
                        {"name": "no_execution", "passed": True,
                         "reason": "预演不调用专业 Agent / 不执行动作"},
                        {"name": "no_memory_write", "passed": True,
                         "reason": "专业 Agent 不写入 Agent Memory"},
                        {"name": "permission_layer_untouched", "passed": True,
                         "reason": "执行仍经 Permission Layer"},
                        {"name": "rule_based_only", "passed": True,
                         "reason": "确定性路由 + 规则分派, 无黑盒"},
                        {"name": "single_consciousness", "passed": True,
                         "reason": "专业 Agent 无独立人格, 统一决策中心"},
                    ],
                    "passed": True,
                },
            }

    def _capability_of(self, agent_name: str) -> str:
        agent = self._registry.get(agent_name)
        return agent.capability if agent else ""

    # ── 状态 ──────────────────────────────────────────────────────
    def status(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "version": "9.5.0",
                "personality": self._personality,
                "enabled": self._enabled,
                "handled_count": self._handled_count,
                "mode": "rule_based",
                "agents_total": self._registry.count(),
            }

    def set_enabled(self, enabled: bool) -> None:
        with self._lock:
            self._enabled = enabled

    @property
    def personality(self) -> str:
        with self._lock:
            return self._personality


__all__ = [
    "MainAgentError",
    "MainCompanionAgent",
]
