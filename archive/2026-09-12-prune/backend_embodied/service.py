"""
YHLZ Embodied AI V4.6 - 具身 Service (Cross-Goal Strategic Planning)

职责:
    - 统一对外 API (Interface 层)
    - 接收 Agent 目标 → 转换动作 → 调用 Environment → 获取反馈
    - 具身闭环: Observe → Think → Plan → Act → Evaluate (自适应规划)
    - 构建具身上下文 (build_environment_context) 供 Agent 推理 (含事件摘要 / 因果 / 预测置信度)
    - 状态预测 (predict / predict_sequence) 供 Agent 决策参考 (只预测不执行)
    - 反馈分析 (FeedbackAnalyzer) + 因果分析 (CausalAnalyzer): 为什么失败 → 补救
    - 事件时间线 (EnvironmentEventLog): get_events / event_history
    - 具身经验摘要 (EnvironmentMemory.summary): 高频失败模式 / 成功率趋势
    - V4.3 场景生命周期: switch_environment / list_environments (多环境动态切换)
    - V4.3 Goal Replay: replay_goal / compare_goals / export_goal_trace
    - V4.3 经验学习: 失败经验沉淀 / 成功配方 / 策略应用到规划 (规则驱动, 禁止 AI 训练)
    - V4.3 Embodied Report: report() 统一输出 (World Model / Memory / Feedback / Prediction / Events / Scene / Policy)
    - V4.4 策略自适应调度: trigger → scene → goal_type → candidates → 质量排序 → best (可解释)
    - V4.4 策略生命周期: archive / restore / policy_history / 老化 stale / 降级恢复
    - V4.4 决策审计: 独立 Audit Log (策略应用 / 拒绝 / 排序, 禁止进入 Agent Memory)
    - V4.4 趋势统计: trend_stats() (场景成功率 / 目标成功率, 数据源 GoalTraceStore)
    - V4.4 Dry Run 预演: dry_run_suggestion() 只模拟不写统计 / 不改计划
    - V4.4 配方泛化: move 参数归一化 (方向 + 距离等级) → 跨场景复用
    - V4.4 场景分段: 事件时间线 scene_segment → 跨场景 Goal Replay
    - V4.5 元策略管理 (StrategyGovernance 门面):
      strategy_system_overview / strategy_system_report (体系总览 + 一致性检查)
      redundant_policies / archive_redundant_policies / conflicting_policies / resolve_conflicts
      archive_candidates / apply_archival (检测→建议→人工确认→执行)
      delete_policy / restore_policy / purge_policy / recycle_bin (回收站)
      consolidate_similar_policies / split_policy / compare_policy_versions / rollback_policy
      policy_health_check / scene_coverage (P1)
      governance_dry_run (治理预演统一入口) / audit_system_export (审计档案导出)
    - 组合 Manager + Permission + ExperienceLearner + GoalTraceStore + SceneManager + Governance
    - 权限优先: 任何动作执行前必须通过 PermissionChecker
    - 高风险动作必须确认 (awaiting_confirm)
    - 动作不得绕过安全层 (策略建议同样不可绕过 Permission Layer)

架构位置:
    Interface (Agent / FastAPI)
        ↓
    Service (本模块)
        ↓
    Manager → Registry → Adapter (Environment)

设计原则:
    - 单一入口: 所有具身操作经 Service
    - 权限优先: 执行前必须通过 PermissionChecker
    - 先理解后行动: 动作必须携带 intent / reason / confidence
    - 状态记忆: 每次观察写入 WorldModel
    - 反馈闭环: 每次行动写入 FeedbackStore + EventLog + Environment Memory
    - 因果优先: 失败必须能解释原因 (cause)
    - 只预测不执行: 预测结果必须经 Permission → Executor 才能落地
    - 经验可解释: 规则表 + 模板匹配, 禁止神经网络训练 / 黑盒学习
    - 策略进化可解释: 规则 + 统计 + 阈值 + 可解释排序 (禁止梯度 / 黑盒优化)
    - 治理约束: 治理动作只影响策略表 / 审计日志 / 体系快照, 不绕过 Permission
    - 配置驱动: 从 config 加载 (embodied_*)
    - 可测试: 提供完整 Mock 注入接口
"""
from __future__ import annotations

import logging
import threading
import time as _time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from backend.embodied.environment.interface import Environment, EnvironmentError
from backend.embodied.environment.mock import MockEnvironment, SCENES
from backend.embodied.environment.registry import EnvironmentRegistryError
from backend.embodied.experience.learner import ExperienceLearner
from backend.embodied.experience.patterns import denormalize_move_parameters
from backend.embodied.experience.policy import ExperiencePolicy
from backend.embodied.feedback.processor import FeedbackStore
from backend.embodied.manager import EmbodiedManager, get_manager, reset_manager
from backend.embodied.permission import (
    EmbodiedPermission,
    EmbodiedPermissionConfig,
    PermissionChecker,
)
from backend.embodied.replay import (
    GoalStep,
    GoalTrace,
    GoalTraceStore,
)
from backend.embodied.scene import SceneManager
from backend.embodied.schema import (
    CausalAnalysis,
    EmbodiedAction,
    EmbodiedActionType,
    EmbodiedGoal,
    EmbodiedStatus,
    EnvironmentEvent,
    EnvironmentPrediction,
    EnvironmentState,
    EventType,
    ExperienceSummary,
    Feedback,
    FeedbackAnalysis,
    FeedbackResult,
    MultiStepPrediction,
)
from backend.embodied.strategy.audit import PolicyAuditLog
from backend.embodied.strategy.ranker import PolicyRanker
from backend.embodied.strategy.trends import TrendStats, infer_goal_type
from backend.embodied.world_model.memory import EnvironmentMemory
from backend.embodied.world_model.state import WorldModel
from backend.embodied.governance import StrategyGovernance
from backend.embodied.planning import CrossGoalPlanner, LongHorizonPlanner
from backend.embodied.companion import MainCompanionAgent

logger = logging.getLogger(__name__)


class EmbodiedServiceError(Exception):
    """Embodied Service 操作异常"""


@dataclass
class EmbodiedOperationResult:
    """具身操作统一结果

    Attributes:
        success:     是否成功 (业务层面)
        goal:        EmbodiedGoal (目标流程)
        action:      执行的 EmbodiedAction (单动作流程)
        state:       动作后环境状态
        feedback:    动作反馈
        analysis:    反馈分析结果 (V4.1)
        prediction:  动作预测 (V4.1)
        permission:  权限判定结果
        suggestions: 规划前置策略建议 (V4.3)
        trace_id:    目标轨迹 ID (V4.3, 目标流程)
        status:      状态 (EmbodiedStatus)
        error:       错误信息
        latency_ms:  耗时 (毫秒)
        iterations:  闭环迭代次数
    """
    success: bool = False
    goal: Optional[EmbodiedGoal] = None
    action: Optional[EmbodiedAction] = None
    state: Optional[EnvironmentState] = None
    feedback: Optional[Feedback] = None
    analysis: Optional[FeedbackAnalysis] = None
    prediction: Optional[EnvironmentPrediction] = None
    permission: Optional[EmbodiedPermission] = None
    suggestions: List[Dict[str, Any]] = field(default_factory=list)
    trace_id: Optional[str] = None
    status: str = EmbodiedStatus.PENDING.value
    error: Optional[str] = None
    latency_ms: float = 0.0
    iterations: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "goal": self.goal.to_dict() if self.goal else None,
            "action": self.action.to_dict() if self.action else None,
            "state": self.state.to_dict() if self.state else None,
            "feedback": self.feedback.to_dict() if self.feedback else None,
            "analysis": self.analysis.to_dict() if self.analysis else None,
            "prediction": self.prediction.to_dict() if self.prediction else None,
            "permission": self.permission.to_dict() if self.permission else None,
            "suggestions": self.suggestions,
            "trace_id": self.trace_id,
            "status": self.status,
            "latency_ms": round(self.latency_ms, 2),
            "iterations": self.iterations,
        }


class EmbodiedService:
    """具身统一服务

    用法:
        svc = EmbodiedService()
        svc.load_config({"embodied_enabled": True})
        result = svc.run_goal(goal)
        ctx = svc.build_environment_context()   # Agent 推理上下文

    闭环:
        Observe → Think → Plan → Act → Evaluate → (成功或达到上限)
    """

    def __init__(
        self,
        manager: Optional[EmbodiedManager] = None,
        permission: Optional[PermissionChecker] = None,
    ):
        self._lock = threading.RLock()
        self._manager: EmbodiedManager = manager or EmbodiedManager()
        self._permission: PermissionChecker = permission or PermissionChecker()
        self._experience = ExperienceLearner()          # V4.3 经验学习 (V4.4 自适应调度)
        self._traces = GoalTraceStore()                  # V4.3 目标轨迹
        self._scene_manager = SceneManager()             # V4.3 场景生命周期
        self._audit = PolicyAuditLog()                   # V4.4 决策审计 (独立存储)
        self._trends = TrendStats()                      # V4.4 趋势统计
        self._governance: Optional[StrategyGovernance] = None  # V4.5 元策略治理
        self._planner: Optional[CrossGoalPlanner] = None        # V4.6 跨目标规划
        self._long_horizon: Optional[LongHorizonPlanner] = None  # V4.7 长期任务
        self._companion: Optional[MainCompanionAgent] = None     # V5.0 伙伴架构
        self._companion_executor: Optional[Any] = None           # V5.3 执行协调器
        self._companion_corrector: Optional[Any] = None          # V5.4 自我修正器
        self._companion_learner: Optional[Any] = None            # V5.4 学习器
        self._companion_personality: Optional[Any] = None        # V5.5 人格引擎
        self._companion_relationship: Optional[Any] = None       # V5.6 关系管理器
        self._companion_decay: Optional[Any] = None              # V5.6 人格衰减
        self._companion_window: Optional[Any] = None             # V5.6 窗口统计
        self._companion_experience: Optional[Any] = None         # V5.7 经历记忆
        self._companion_reflection: Optional[Any] = None         # V5.8 反思引擎
        self._companion_verifier: Optional[Any] = None           # V5.8 经验验证
        self._companion_creative: Optional[Any] = None           # V5.9 创造智能
        self._companion_continuity: Optional[Any] = None         # V6.0 连续层
        self._companion_emotion: Optional[Any] = None            # V6.1.1 情绪
        self._companion_rhythm: Optional[Any] = None             # V6.1.1 节律
        self._companion_expression: Optional[Any] = None         # V6.2 表达
        self._companion_perception: Optional[Any] = None         # V6.2 感知
        self._companion_memory_gate: Optional[Any] = None        # V6.3 记忆网关
        self._companion_pipeline: Optional[Any] = None           # V6.3 感知管道
        self._companion_reflection_eval: Optional[Any] = None    # V6.4 反思评估
        self._companion_counterfactual: Optional[Any] = None     # V6.4 反事实验证
        self._companion_cognitive: Optional[Any] = None          # V6.5 认知反思
        self._companion_growth: Optional[Any] = None             # V6.5 自主成长
        self._companion_identity_guard: Optional[Any] = None     # V6.5 身份守护
        self._companion_reflection_emotion: Optional[Any] = None # V6.6 反思情绪
        self._companion_growth_cycle: Optional[Any] = None       # V6.6 成长闭环
        self._companion_trend: Optional[Any] = None              # V6.6 趋势分析
        self._companion_hybrid: Optional[Any] = None             # V6.8 混合智能层
        self._companion_presence: Optional[Any] = None           # V7.0 具身表达层
        self._companion_constitution: Optional[Any] = None       # V8.0 宪法引擎
        self._companion_meta_creative: Optional[Any] = None      # V8.5 元创造力
        self._companion_research: Optional[Any] = None           # V9.0 研究探索
        self._companion_meta_cognition: Optional[Any] = None     # V9.5 元认知
        self._companion_config: Dict[str, Any] = {}              # V5.3 配置快照
        self._initialized = False

    # ── 依赖注入 ──────────────────────────────────────────────────
    def set_manager(self, manager: EmbodiedManager) -> None:
        with self._lock:
            self._manager = manager

    def set_permission(self, permission: PermissionChecker) -> None:
        with self._lock:
            self._permission = permission

    def set_experience(self, learner: ExperienceLearner) -> None:
        """注入经验学习器 (测试用)"""
        with self._lock:
            self._experience = learner

    def set_audit(self, audit: PolicyAuditLog) -> None:
        """注入决策审计日志 (测试用)"""
        with self._lock:
            self._audit = audit

    def set_trends(self, trends: TrendStats) -> None:
        """注入趋势统计器 (测试用)"""
        with self._lock:
            self._trends = trends

    def set_governance(self, governance: StrategyGovernance) -> None:
        """注入元策略治理门面 (V4.5, 测试用)"""
        with self._lock:
            self._governance = governance

    @property
    def manager(self) -> EmbodiedManager:
        return self._manager

    @property
    def permission(self) -> PermissionChecker:
        return self._permission

    @property
    def experience(self) -> ExperienceLearner:
        """经验学习器 (V4.3)"""
        return self._experience

    @property
    def traces(self) -> GoalTraceStore:
        """目标轨迹存储 (V4.3)"""
        return self._traces

    @property
    def scene_manager(self) -> SceneManager:
        """场景迁移记录器 (V4.3)"""
        return self._scene_manager

    @property
    def audit(self) -> PolicyAuditLog:
        """决策审计日志 (V4.4, 独立存储)"""
        return self._audit

    @property
    def trends(self) -> TrendStats:
        """趋势统计器 (V4.4)"""
        return self._trends

    @property
    def governance(self) -> StrategyGovernance:
        """元策略治理门面 (V4.5, 懒加载)"""
        with self._lock:
            if self._governance is None:
                self._governance = StrategyGovernance(
                    table=self._experience.table,
                    audit=self._audit,
                )
            return self._governance

    @property
    def planner(self) -> CrossGoalPlanner:
        """跨目标规划器 (V4.6, 懒加载)"""
        with self._lock:
            if self._planner is None:
                self._planner = CrossGoalPlanner(
                    table=self._experience.table,
                    audit=self._audit,
                )
            return self._planner

    @property
    def long_horizon(self) -> LongHorizonPlanner:
        """长期任务规划器 (V4.7, 懒加载)"""
        with self._lock:
            if self._long_horizon is None:
                self._long_horizon = LongHorizonPlanner(audit=self._audit)
            return self._long_horizon

    @property
    def companion(self) -> MainCompanionAgent:
        """主伙伴 Agent (V5.0, 懒加载)"""
        with self._lock:
            if self._companion is None:
                from backend.embodied.companion import (
                    CompanionRouter,
                    CompanionStats,
                    TaskDelegator,
                    build_default_agents,
                )
                registry = build_default_agents(self)
                router = CompanionRouter(registry)
                delegator = TaskDelegator(router)
                self._companion = MainCompanionAgent(
                    registry=registry, router=router, delegator=delegator,
                    personality="铁哥们",
                    stats=CompanionStats(),
                    personality_engine=self.companion_personality_engine,
                    relationship_manager=self.companion_relationship_manager,
                    decay_policy=self.companion_decay,
                    interaction_window=self.companion_window,
                experience_manager=self.companion_experience,
                reflection_engine=self.companion_reflection_engine,
                experience_verifier=self.companion_verifier,
                )
            return self._companion

    @property
    def companion_personality_engine(self) -> Any:
        """自适应人格引擎 (V5.5, 懒加载缓存)"""
        with self._lock:
            if self._companion_personality is None:
                from backend.embodied.companion import (
                    AdaptivePersonalityEngine,
                )
                self._companion_personality = AdaptivePersonalityEngine(
                    base=str(self._companion_config.get(
                        "companion_personality_base", "铁哥们"
                    )),
                    step=float(self._companion_config.get(
                        "companion_personality_adjust_step", 0.1
                    )),
                    enabled=bool(self._companion_config.get(
                        "companion_personality_enabled", True
                    )),
                )
            return self._companion_personality

    @property
    def companion_relationship_manager(self) -> Any:
        """关系管理器 (V5.6, 懒加载缓存)"""
        with self._lock:
            if self._companion_relationship is None:
                from backend.embodied.companion import RelationshipManager
                self._companion_relationship = RelationshipManager(
                    enabled=bool(self._companion_config.get(
                        "companion_relationship_enabled", True
                    )),
                )
            return self._companion_relationship

    @property
    def companion_decay(self) -> Any:
        """人格衰减策略 (V5.6, 懒加载缓存)"""
        with self._lock:
            if self._companion_decay is None:
                from backend.embodied.companion import (
                    PersonalityDecayPolicy,
                )
                self._companion_decay = PersonalityDecayPolicy(
                    rate=float(self._companion_config.get(
                        "companion_decay_rate", 0.05
                    )),
                    enabled=bool(self._companion_config.get(
                        "companion_personality_decay_enabled", True
                    )),
                )
            return self._companion_decay

    @property
    def companion_window(self) -> Any:
        """窗口统计器 (V5.6, 懒加载缓存)"""
        with self._lock:
            if self._companion_window is None:
                from backend.embodied.companion import InteractionWindow
                self._companion_window = InteractionWindow()
            return self._companion_window

    @property
    def companion_experience(self) -> Any:
        """经历管理器 (V5.7, 懒加载缓存)"""
        with self._lock:
            if self._companion_experience is None:
                from backend.embodied.companion.experience import (
                    ExperienceManager,
                    ExperienceStore,
                )
                self._companion_experience = ExperienceManager(
                    store=ExperienceStore(
                        max_records=int(self._companion_config.get(
                            "companion_experience_max_records", 200
                        )),
                    ),
                )
            return self._companion_experience

    @property
    def companion_reflection_engine(self) -> Any:
        """反思引擎 (V5.8, 懒加载缓存)"""
        with self._lock:
            if self._companion_reflection is None:
                from backend.embodied.companion.reflection import (
                    PatternDiscovery,
                    ReflectionEngine,
                )
                self._companion_reflection = ReflectionEngine(
                    pattern_discovery=PatternDiscovery(
                        min_occurrences=int(self._companion_config.get(
                            "companion_pattern_min_occurrences", 3
                        )),
                    ),
                )
            return self._companion_reflection

    @property
    def companion_verifier(self) -> Any:
        """经验验证器 (V5.8, 懒加载缓存)"""
        with self._lock:
            if self._companion_verifier is None:
                from backend.embodied.companion.verification import (
                    ExperienceVerifier,
                )
                self._companion_verifier = ExperienceVerifier(
                    confirm_threshold=int(self._companion_config.get(
                        "companion_verification_confirm_threshold", 2
                    )),
                    reject_threshold=int(self._companion_config.get(
                        "companion_verification_reject_threshold", 2
                    )),
                )
            return self._companion_verifier

    @property
    def companion_creative_engine(self) -> Any:
        """创造引擎 (V5.9, 懒加载缓存)"""
        with self._lock:
            if self._companion_creative is None:
                from backend.embodied.companion.creative import (
                    CreativeEngine,
                )
                self._companion_creative = CreativeEngine(
                    experience_manager=self.companion_experience,
                    verifier=self.companion_verifier,
                    reflection_engine=self.companion_reflection_engine,
                    improvement_engine=(
                        self.companion_reflection_engine._proposals
                    ),
                    relationship_manager=self.companion_relationship_manager,
                    enabled=bool(self._companion_config.get(
                        "companion_creative_enabled", True
                    )),
                    config=self._companion_config,
                )
            return self._companion_creative

    @property
    def companion_continuity_engine(self) -> Any:
        """连续引擎 (V6.0, 懒加载缓存)"""
        with self._lock:
            if self._companion_continuity is None:
                from backend.embodied.companion.continuity_engine import (
                    ContinuityEngine,
                )
                self._companion_continuity = ContinuityEngine(
                    experience_manager=self.companion_experience,
                    verifier=self.companion_verifier,
                    reflection_engine=self.companion_reflection_engine,
                    creative_engine=self.companion_creative_engine,
                    relationship_manager=self.companion_relationship_manager,
                    personality_engine=self.companion_personality_engine,
                    emotion_engine=self.companion_emotion_engine,
                    enabled=bool(self._companion_config.get(
                        "companion_persistence_enabled", False
                    )),
                    config=self._companion_config,
                )
            return self._companion_continuity

    @property
    def companion_emotion_engine(self) -> Any:
        """情绪引擎 (V6.1.1, 懒加载缓存)"""
        with self._lock:
            if self._companion_emotion is None:
                from backend.embodied.companion.emotion import (
                    EmotionEngine,
                )
                self._companion_emotion = EmotionEngine(
                    enabled=bool(self._companion_config.get(
                        "companion_emotion_enabled", True
                    )),
                    update_step=float(self._companion_config.get(
                        "companion_emotion_update_step", 0.1
                    )),
                    decay_rate=float(self._companion_config.get(
                        "companion_emotion_decay_rate", 0.05
                    )),
                    decay_window_days=float(self._companion_config.get(
                        "companion_emotion_decay_window_days", 7.0
                    )),
                    consecutive_limit=int(self._companion_config.get(
                        "companion_emotion_consecutive_limit", 3
                    )),
                    floor=float(self._companion_config.get(
                        "companion_emotion_floor", 0.1
                    )),
                )
            return self._companion_emotion

    @property
    def companion_rhythm(self) -> Any:
        """成长节律 (V6.1.1, 懒加载缓存)"""
        with self._lock:
            if self._companion_rhythm is None:
                from backend.embodied.companion.rhythm import (
                    GrowthRhythm,
                )
                self._companion_rhythm = GrowthRhythm(
                    continuity=self.companion_continuity_engine,
                    emotion=self.companion_emotion_engine,
                    enabled=bool(self._companion_config.get(
                        "companion_rhythm_enabled", True
                    )),
                    config=self._companion_config,
                )
            return self._companion_rhythm

    @property
    def companion_expression_engine(self) -> Any:
        """表达引擎 (V6.2, 懒加载缓存)"""
        with self._lock:
            if self._companion_expression is None:
                from backend.embodied.companion.expression import (
                    ExpressionEngine,
                )
                self._companion_expression = ExpressionEngine(
                    enabled=bool(self._companion_config.get(
                        "companion_expression_enabled", True
                    )),
                    threshold=float(self._companion_config.get(
                        "companion_expression_threshold", 0.7
                    )),
                )
            return self._companion_expression

    @property
    def companion_perception_service(self) -> Any:
        """感知服务 (V6.2, 懒加载缓存)"""
        with self._lock:
            if self._companion_perception is None:
                from backend.embodied.companion.perception import (
                    CameraAdapter,
                    DetectionMockAdapter,
                    OCRMockAdapter,
                    PerceptionAudit,
                    PerceptionManager,
                    PerceptionPermission,
                    PerceptionService,
                    PerceptionVerifier,
                    VisionMockAdapter,
                )
                pmgr = PerceptionManager(
                    default_ocr=str(self._companion_config.get(
                        "perception_default_ocr", "ocr_mock"
                    )),
                    default_detect=str(self._companion_config.get(
                        "perception_default_detection",
                        "detection_mock"
                    )),
                )
                pmgr.register(OCRMockAdapter())
                pmgr.register(DetectionMockAdapter())
                pmgr.register(VisionMockAdapter())
                pmgr.register(CameraAdapter())
                self._companion_perception = PerceptionService(
                    manager=pmgr,
                    permission=PerceptionPermission(
                        enabled=bool(self._companion_config.get(
                            "perception_enabled", False
                        )),
                        vision_enabled=bool(
                            self._companion_config.get(
                                "vision_enabled", False
                            )
                        ),
                        ocr_enabled=bool(self._companion_config.get(
                            "ocr_enabled", False
                        )),
                        detection_enabled=bool(
                            self._companion_config.get(
                                "detection_enabled", False
                            )
                        ),
                        permission_required=bool(
                            self._companion_config.get(
                                "perception_permission_required",
                                True
                            )
                        ),
                    ),
                    verifier=PerceptionVerifier(
                        min_confidence=float(
                            self._companion_config.get(
                                "perception_min_confidence", 0.5
                            )
                        ),
                    ),
                    audit=PerceptionAudit(
                        enabled=bool(self._companion_config.get(
                            "perception_audit_enabled", True
                        )),
                    ),
                )
            return self._companion_perception

    @property
    def companion_memory_gate(self) -> Any:
        """记忆网关 (V6.3, 懒加载缓存)"""
        with self._lock:
            if self._companion_memory_gate is None:
                from backend.embodied.companion.perception import (
                    ApprovalRule,
                    CandidateValidator,
                    MemoryGate,
                )
                self._companion_memory_gate = MemoryGate(
                    validator=CandidateValidator(),
                    rule=ApprovalRule(
                        approve_threshold=float(
                            self._companion_config.get(
                                "memory_gate_approve_threshold", 0.6
                            )
                        ),
                        reject_threshold=float(
                            self._companion_config.get(
                                "memory_gate_reject_threshold", 0.3
                            )
                        ),
                    ),
                    enabled=bool(self._companion_config.get(
                        "memory_gate_enabled", True
                    )),
                )
            return self._companion_memory_gate

    @property
    def companion_perception_pipeline(self) -> Any:
        """感知管道适配器 (V6.3, 懒加载缓存)"""
        with self._lock:
            if self._companion_pipeline is None:
                from backend.embodied.companion.perception import (
                    AgentPipelineAdapter,
                    PerceptionRouter,
                )
                self._companion_pipeline = AgentPipelineAdapter(
                    router=PerceptionRouter(),
                    enabled=bool(self._companion_config.get(
                        "pipeline_perception_enabled", True
                    )),
                )
            return self._companion_pipeline

    @property
    def companion_reflection_evaluator(self) -> Any:
        """反思评估器 (V6.4, Advisor, 懒加载缓存)"""
        with self._lock:
            if self._companion_reflection_eval is None:
                from backend.embodied.companion.perception import (
                    ReflectionEvaluator,
                    ReflectionRules,
                )
                self._companion_reflection_eval =                     ReflectionEvaluator(
                        rules=ReflectionRules(
                            threshold=float(
                                self._companion_config.get(
                                    "reflection_score_threshold", 0.6
                                )
                            ),
                        ),
                        enabled=bool(self._companion_config.get(
                            "reflection_enabled", True
                        )),
                    )
            return self._companion_reflection_eval

    @property
    def companion_counterfactual_checker(self) -> Any:
        """反事实验证器 (V6.4, 懒加载缓存)"""
        with self._lock:
            if self._companion_counterfactual is None:
                from backend.embodied.companion.perception import (
                    CounterfactualCheck,
                )
                self._companion_counterfactual = CounterfactualCheck(
                    enabled=bool(self._companion_config.get(
                        "counterfactual_enabled", True
                    )),
                )
            return self._companion_counterfactual

    @property
    def companion_cognitive_reflection(self) -> Any:
        """认知反思引擎 (V6.5, 懒加载缓存)"""
        with self._lock:
            if self._companion_cognitive is None:
                from backend.embodied.companion.reflection import (
                    CognitiveReflectionEngine,
                    PatternAnalyzer,
                )
                self._companion_cognitive = \
                    CognitiveReflectionEngine(
                        pattern_analyzer=PatternAnalyzer(
                            min_samples=int(
                                self._companion_config.get(
                                    "companion_pattern_min_occurrences",
                                    3,
                                )
                            ),
                        ),
                        enabled=bool(self._companion_config.get(
                            "reflection_enabled", True
                        )),
                    )
            return self._companion_cognitive

    @property
    def companion_growth_engine(self) -> Any:
        """成长引擎 (V6.5, 懒加载缓存)"""
        with self._lock:
            if self._companion_growth is None:
                from backend.embodied.companion.growth import (
                    GrowthApplier,
                    GrowthAudit,
                    GrowthEvaluator,
                    GrowthProposal,
                )
                self._companion_growth = {
                    "proposal": GrowthProposal(
                        enabled=bool(self._companion_config.get(
                            "growth_proposal_enabled", True
                        )),
                    ),
                    "evaluator": GrowthEvaluator(),
                    "applier": GrowthApplier(
                        audit=GrowthAudit(
                            enabled=bool(self._companion_config.get(
                                "growth_audit_enabled", True
                            )),
                        ),
                        auto_apply=bool(self._companion_config.get(
                            "growth_auto_apply", False
                        )),
                    ),
                }
            return self._companion_growth

    @property
    def companion_identity_guard(self) -> Any:
        """身份守护 (V6.5, 懒加载缓存)"""
        with self._lock:
            if self._companion_identity_guard is None:
                from backend.embodied.companion.identity import (
                    ChangeValidator,
                    IdentityGuard,
                )
                self._companion_identity_guard = {
                    "guard": IdentityGuard(
                        enabled=bool(self._companion_config.get(
                            "identity_guard_enabled", True
                        )),
                    ),
                    "validator": ChangeValidator(),
                }
            return self._companion_identity_guard

    @property
    def companion_reflection_emotion(self) -> Any:
        """反思情绪集成器 (V6.6, 懒加载缓存)"""
        with self._lock:
            if self._companion_reflection_emotion is None:
                from backend.embodied.companion.reflection import (
                    ReflectionEmotionIntegrator,
                )
                self._companion_reflection_emotion = \
                    ReflectionEmotionIntegrator(
                        emotion=self.companion_emotion_engine,
                        enabled=bool(self._companion_config.get(
                            "companion_reflection_emotion_enabled",
                            True,
                        )),
                    )
            return self._companion_reflection_emotion

    @property
    def companion_growth_cycle(self) -> Any:
        """成长闭环引擎 (V6.6, 懒加载缓存)"""
        with self._lock:
            if self._companion_growth_cycle is None:
                from backend.embodied.companion.growth import (
                    GrowthCycleEngine,
                )
                engine = self.companion_growth_engine
                self._companion_growth_cycle = GrowthCycleEngine(
                    reflection=self.companion_cognitive_reflection,
                    proposal=engine["proposal"],
                    evaluator=engine["evaluator"],
                    audit=engine["applier"]._audit,
                    records_fn=lambda: [
                        r.to_dict()
                        for r in self.companion_experience.
                        _store.all()
                    ],
                    enabled=bool(self._companion_config.get(
                        "companion_growth_cycle_enabled", True,
                    )),
                    cycle_days=int(self._companion_config.get(
                        "companion_growth_cycle_days", 1,
                    )),
                    min_experience_delta=int(
                        self._companion_config.get(
                            "companion_growth_cycle_"
                            "min_experience_delta", 5,
                        ),
                    ),
                    max_pending=int(self._companion_config.get(
                        "companion_growth_cycle_max_pending", 50,
                    )),
                )
            return self._companion_growth_cycle

    @property
    def companion_growth_trend_analyzer(self) -> Any:
        """成长趋势分析器 (V6.6, 懒加载缓存)"""
        with self._lock:
            if self._companion_trend is None:
                from backend.embodied.companion.growth import (
                    GrowthTrendAnalysis,
                )
                self._companion_trend = GrowthTrendAnalysis(
                    enabled=bool(self._companion_config.get(
                        "companion_growth_trend_enabled", True,
                    )),
                )
            return self._companion_trend

    @property
    def companion_hybrid(self) -> Any:
        """混合智能层 (V6.8, 懒加载缓存)"""
        with self._lock:
            if self._companion_hybrid is None:
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
                cfg = self._companion_config
                cloud_enabled = bool(cfg.get(
                    "companion_hybrid_cloud_enabled", True,
                ))
                audit = InferenceAudit(
                    enabled=bool(cfg.get(
                        "companion_hybrid_audit_enabled", True,
                    )),
                    max_records=int(cfg.get(
                        "companion_hybrid_audit_max", 2000,
                    )),
                )
                cost = CostPolicy(
                    enabled=bool(cfg.get(
                        "companion_hybrid_cost_enabled", True,
                    )),
                    high_cost_threshold=float(cfg.get(
                        "companion_hybrid_high_cost_threshold",
                        0.01,
                    )),
                    low_value_threshold=float(cfg.get(
                        "companion_hybrid_low_value_threshold",
                        0.3,
                    )),
                )
                privacy = PrivacyPolicy(
                    enabled=bool(cfg.get(
                        "companion_hybrid_privacy_enabled", True,
                    )),
                )
                gateway = ApiGateway(
                    enabled=cloud_enabled,
                    max_records=int(cfg.get(
                        "companion_hybrid_audit_max", 2000,
                    )),
                )
                matcher = CapabilityMatcher()
                local = LocalProvider()
                cloud = CloudProvider(
                    gateway=gateway, enabled=cloud_enabled,
                )
                routing = RoutingEngine(
                    privacy=privacy, cost=cost,
                    matcher=matcher,
                )
                self._companion_hybrid = \
                    HybridIntelligenceLayer(
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
                        enabled=bool(cfg.get(
                            "companion_hybrid_enabled", True,
                        )),
                    )
                self._companion_hybrid.initialize_defaults()
            return self._companion_hybrid

    @property
    def companion_presence_engine(self) -> Any:
        """具身表达引擎 (V7.0, 懒加载缓存)"""
        with self._lock:
            if self._companion_presence is None:
                from backend.embodied.companion.embodied_presence import (
                    PresenceEngine,
                    PresenceMapper,
                    PresenceMemory,
                    PresenceState,
                )
                cfg = self._companion_config
                self._companion_presence = PresenceEngine(
                    state=PresenceState(),
                    mapper=PresenceMapper(
                        enabled=bool(cfg.get(
                            "companion_presence_enabled", True,
                        )),
                    ),
                    memory=PresenceMemory(
                        max_records=int(cfg.get(
                            "companion_presence_memory_max",
                            2000,
                        )),
                    ),
                    emotion=self.companion_emotion_engine,
                    personality_fn=lambda: (
                        self.companion_personality_engine
                        .personality()
                    ),
                    enabled=bool(cfg.get(
                        "companion_presence_enabled", True,
                    )),
                    intensity_step=float(cfg.get(
                        "companion_presence_intensity_step",
                        0.15,
                    )),
                )
            return self._companion_presence

    @property
    def companion_constitution_engine(self) -> Any:
        """宪法引擎 (V8.0, 懒加载缓存)"""
        with self._lock:
            if self._companion_constitution is None:
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
                cfg = self._companion_config
                enabled = bool(cfg.get(
                    "companion_constitution_enabled", True,
                ))
                principles = Principles(enabled=enabled)
                ledger = ConstitutionLedger(
                    enabled=enabled,
                    max_records=int(cfg.get(
                        "companion_constitution_ledger_max",
                        5000,
                    )),
                )
                self._companion_constitution = \
                    ConstitutionEngine(
                        principles=principles,
                        identity_rules=IdentityRules(),
                        safety=SafetyPolicy(),
                        growth=GrowthPolicy(),
                        intelligence=IntelligencePolicy(),
                        validator=ConstitutionValidator(),
                        evolution=EvolutionProposal(),
                        ledger=ledger,
                        enabled=enabled,
                    )
            return self._companion_constitution

    @property
    def companion_meta_creative(self) -> Any:
        """元创造力引擎 (V8.5, 懒加载缓存)"""
        with self._lock:
            if self._companion_meta_creative is None:
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
                cfg = self._companion_config
                self._companion_meta_creative = \
                    MetaCreativeEngine(
                        graph=KnowledgeGraph(),
                        spark_generator=IdeaSparkGenerator(
                            max_sparks=int(cfg.get(
                                "companion_meta_creative_"
                                "max_sparks", 10,
                            )),
                        ),
                        fusion=ConceptFusion(),
                        boundary=ThoughtBoundaryDetector(),
                        hypothesis=HypothesisEngine(),
                        validation=CreativeValidation(),
                        memory=CreativeMemory(
                            max_records=int(cfg.get(
                                "companion_meta_creative_"
                                "memory_max", 1000,
                            )),
                        ),
                        collaborative=CollaborativeCreation(),
                        constitution=(
                            self.companion_constitution_engine
                            if bool(cfg.get(
                                "companion_meta_creative_"
                                "constitution_link", True,
                            )) else None
                        ),
                        enabled=bool(cfg.get(
                            "companion_meta_creative_enabled",
                            True,
                        )),
                    )
            return self._companion_meta_creative

    @property
    def companion_research(self) -> Any:
        """自主研究引擎 (V9.0, 懒加载缓存)"""
        with self._lock:
            if self._companion_research is None:
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
                cfg = self._companion_config
                observation = ObservationLayer()
                self._companion_research = ResearchEngine(
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
                        max_records=int(cfg.get(
                            "companion_research_audit_max",
                            2000,
                        )),
                    ),
                    constitution=(
                        self.companion_constitution_engine
                        if bool(cfg.get(
                            "companion_research_"
                            "constitution_link", True,
                        )) else None
                    ),
                    enabled=bool(cfg.get(
                        "companion_research_enabled", True,
                    )),
                    max_loops_per_explore=int(cfg.get(
                        "companion_research_max_loops", 3,
                    )),
                )
            return self._companion_research

    @property
    def companion_meta_cognition(self) -> Any:
        """元认知引擎 (V9.5, 懒加载缓存)"""
        with self._lock:
            if self._companion_meta_cognition is None:
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
                cfg = self._companion_config
                constitution = (
                    self.companion_constitution_engine
                    if bool(cfg.get(
                        "companion_meta_cognition_"
                        "constitution_link", True,
                    )) else None
                )
                self._companion_meta_cognition = \
                    MetaCognitionEngine(
                        monitor=CognitiveMonitor(),
                        evaluator=ReasoningEvaluator(),
                        error_detector=ErrorPatternDetector(),
                        reflection=ReflectionLoop(
                            constitution=constitution,
                        ),
                        verification=SelfVerification(),
                        memory=CognitionMemory(
                            max_records=int(cfg.get(
                                "companion_meta_cognition_"
                                "memory_max", 1000,
                            )),
                        ),
                        audit=CognitionAudit(
                            max_records=int(cfg.get(
                                "companion_meta_cognition_"
                                "audit_max", 2000,
                            )),
                        ),
                        constitution=constitution,
                        enabled=bool(cfg.get(
                            "companion_meta_cognition_enabled",
                            True,
                        )),
                    )
            return self._companion_meta_cognition

    @property
    def companion_executor(self) -> Any:
        """执行协调器 (V5.3, 懒加载缓存)"""
        with self._lock:
            if self._companion_executor is None:
                from backend.embodied.companion import ExecutionCoordinator
                self._companion_executor = ExecutionCoordinator(
                    self,
                    max_iterations=int(self._companion_config.get(
                        "companion_loop_max_iterations", 3
                    )),
                    feedback_enabled=bool(self._companion_config.get(
                        "companion_feedback_enabled", True
                    )),
                    confirm=bool(self._companion_config.get(
                        "companion_execute_confirm", False
                    )),
                )
            return self._companion_executor

    @property
    def companion_learner(self) -> Any:
        """学习器 (V5.4, 懒加载缓存)"""
        with self._lock:
            if self._companion_learner is None:
                from backend.embodied.companion import CompanionLearning
                self._companion_learner = CompanionLearning(
                    enabled=bool(self._companion_config.get(
                        "companion_learning_enabled", True
                    )),
                )
            return self._companion_learner

    @property
    def companion_corrector(self) -> Any:
        """自我修正器 (V5.4, 懒加载缓存)"""
        with self._lock:
            if self._companion_corrector is None:
                from backend.embodied.companion import SelfCorrector
                self._companion_corrector = SelfCorrector(
                    self,
                    max_attempts=int(self._companion_config.get(
                        "companion_correction_max_attempts", 3
                    )),
                    strict=bool(self._companion_config.get(
                        "companion_correction_strict", False
                    )),
                    learner=self.companion_learner,
                )
            return self._companion_corrector

    @property
    def world_model(self) -> WorldModel:
        return self._manager.world_model

    @property
    def feedback_store(self) -> FeedbackStore:
        return self._manager.feedback

    @property
    def memory(self) -> EnvironmentMemory:
        return self._manager.memory

    # ── 配置 ──────────────────────────────────────────────────────
    def load_config(self, config: Dict[str, Any]) -> None:
        """从 dict 加载配置 (权限 + 默认环境注册 + 记忆路径 + 经验学习)"""
        with self._lock:
            perm = EmbodiedPermissionConfig.from_dict(config)
            self._permission.load_from_config(perm)
            self._manager.register_defaults()
            memory_path = config.get("embodied_memory_path")
            if memory_path:
                self._manager.memory.load_or_init(memory_path)
            # V4.3: 经验学习配置 (规则驱动)
            self._experience.configure(
                failure_threshold=config.get(
                    "embodied_failure_pattern_threshold",
                    self._experience.stats()["failure_threshold"],
                ),
                min_suggestions=config.get(
                    "embodied_policy_min_suggestions",
                    self._experience.stats()["min_suggestions"],
                ),
                min_hit_rate=config.get(
                    "embodied_policy_min_hit_rate",
                    self._experience.stats()["min_hit_rate"],
                ),
                planning_use_recipe=config.get(
                    "embodied_planning_use_recipe",
                    self._experience.stats()["planning_use_recipe"],
                ),
                enabled=config.get(
                    "embodied_experience_enabled",
                    self._experience.stats()["enabled"],
                ),
                # V4.4: 策略生命周期 (老化 / 恢复)
                max_age_days=config.get(
                    "embodied_policy_max_age_days",
                    self._experience.stats()["max_age_days"],
                ),
                recovery_threshold=config.get(
                    "embodied_policy_recovery_threshold",
                    self._experience.stats()["recovery_threshold"],
                ),
                scene_enabled=config.get(
                    "embodied_policy_scene_enabled",
                    self._experience.stats()["scene_enabled"],
                ),
                goal_type_enabled=config.get(
                    "embodied_policy_goal_type_enabled",
                    self._experience.stats()["goal_type_enabled"],
                ),
            )
            # V4.4: 排序权重 (可解释排序)
            if any(k in config for k in (
                "embodied_rank_hit_rate_weight",
                "embodied_rank_acceptance_weight",
                "embodied_rank_recency_weight",
            )):
                self._experience.set_ranker(PolicyRanker(
                    hit_rate_weight=config.get("embodied_rank_hit_rate_weight", 0.5),
                    acceptance_weight=config.get("embodied_rank_acceptance_weight", 0.3),
                    recency_weight=config.get("embodied_rank_recency_weight", 0.2),
                ))
            # V4.4: 决策审计 (独立存储, 禁止进入 Agent Memory)
            self._audit = PolicyAuditLog(
                max_entries=int(config.get("embodied_audit_log_max", 500))
            )
            audit_path = config.get("embodied_audit_log_path")
            if audit_path:
                self._audit.load_from_file(audit_path)
            # V4.4: 趋势统计 (滚动窗口)
            self._trends = TrendStats(
                window=int(config.get("embodied_trend_window", 10))
            )
            # V4.5: 元策略治理 (阈值配置驱动, embodied_* 前缀)
            self._governance = StrategyGovernance(
                table=self._experience.table,
                audit=self._audit,
                min_archive_age_days=float(config.get(
                    "embodied_policy_min_archive_age_days", 30
                )),
                min_archive_hit_rate=float(config.get(
                    "embodied_policy_min_archive_hit_rate", 0.3
                )),
            )
            # V4.6: 跨目标规划 (配置驱动, embodied_planning_* 前缀)
            self._planner = CrossGoalPlanner(
                table=self._experience.table,
                audit=self._audit,
                max_budget=int(config.get(
                    "embodied_planning_max_budget", 100
                )),
                min_group_size=int(config.get(
                    "embodied_planning_min_group_size", 2
                )),
                min_archive_hit_rate=float(config.get(
                    "embodied_planning_quality_bonus_threshold",
                    config.get("embodied_policy_min_hit_rate", 0.5),
                )),
            )
            # V4.7: 长期任务规划 (配置驱动, embodied_mission_* 前缀)
            from backend.embodied.planning import PlanAdjuster, ProgressTracker
            self._long_horizon = LongHorizonPlanner(
                audit=self._audit,
                plan_adjuster=PlanAdjuster(
                    progress_tracker=ProgressTracker(),
                    risk_failure_threshold=int(config.get(
                        "embodied_risk_failure_threshold", 3
                    )),
                    risk_blocked_threshold=int(config.get(
                        "embodied_risk_blocked_threshold", 2
                    )),
                    deadline_warning_hours=float(config.get(
                        "embodied_deadline_warning_hours", 24.0
                    )),
                ),
                min_goals_per_milestone=1,
            )
            # V5.0: 主伙伴 Agent (配置驱动, companion_* 前缀)
            # V5.1: 并发委派 + 路由打分 + 协同统计 (配置驱动)
            # V5.2: Agent 数据管道 (感知-策略闭环, 配置驱动)
            # V5.3: 执行闭环 (V5.3 配置快照)
            # V5.4: 自我修正与学习 (配置驱动)
            # V5.5: 身份与自适应人格 (配置驱动)
            # V5.6: 关系与人格稳定 (配置驱动)
            self._companion_config = dict(config)
            self._companion_executor = None
            self._companion_corrector = None
            self._companion_learner = None
            self._companion_personality = None
            self._companion_relationship = None
            self._companion_decay = None
            self._companion_window = None
            self._companion_experience = None
            self._companion_reflection = None
            self._companion_verifier = None
            self._companion_creative = None
            self._companion_continuity = None
            self._companion_emotion = None
            self._companion_rhythm = None
            self._companion_expression = None
            self._companion_perception = None
            self._companion_memory_gate = None
            self._companion_pipeline = None
            self._companion_reflection_eval = None
            self._companion_counterfactual = None
            self._companion_cognitive = None
            self._companion_growth = None
            self._companion_identity_guard = None
            self._companion_reflection_emotion = None
            self._companion_growth_cycle = None
            self._companion_trend = None
            self._companion_hybrid = None
            self._companion_presence = None
            self._companion_constitution = None
            self._companion_meta_creative = None
            self._companion_research = None
            self._companion_meta_cognition = None
            from backend.embodied.companion import (
                AgentPipeline,
                CompanionRouter,
                CompanionStats,
                TaskDelegator,
                build_default_agents,
            )
            registry = build_default_agents(self)
            router = CompanionRouter(
                registry,
                rule_version=str(config.get(
                    "companion_route_rule_version", "v1"
                )),
                top_k=int(config.get("companion_route_topk", 3)),
            )
            pipeline = AgentPipeline(
                enabled=bool(config.get("companion_pipeline_enabled", True)),
                strict=bool(config.get("companion_pipeline_strict", False)),
            )
            delegator = TaskDelegator(
                router,
                timeout=float(config.get("companion_agent_timeout", 10.0)),
                workers=int(config.get("companion_delegate_workers", 4)),
                pipeline=pipeline,
            )
            self._companion = MainCompanionAgent(
                registry=registry, router=router, delegator=delegator,
                personality="铁哥们",
                enabled=bool(config.get("companion_enabled", False)),
                stats=CompanionStats(max_records=int(config.get(
                    "companion_stats_max_records", 500
                ))),
                personality_engine=self.companion_personality_engine,
                relationship_manager=self.companion_relationship_manager,
                decay_policy=self.companion_decay,
                interaction_window=self.companion_window,
                experience_manager=self.companion_experience,
                reflection_engine=self.companion_reflection_engine,
                experience_verifier=self.companion_verifier,
                creative_engine=self.companion_creative_engine,
                creative_config=self._companion_config,
                continuity_engine=self.companion_continuity_engine,
                continuity_config=self._companion_config,
                emotion_engine=self.companion_emotion_engine,
                rhythm=self.companion_rhythm,
                rhythm_config=self._companion_config,
                expression_engine=self.companion_expression_engine,
                perception_service=self.companion_perception_service,
                perception_config=self._companion_config,
                memory_gate=self.companion_memory_gate,
                pipeline_adapter=self.companion_perception_pipeline,
                reflection_evaluator=self.companion_reflection_evaluator,
                counterfactual_check=self.companion_counterfactual_checker,
                cognitive_reflection=self.companion_cognitive_reflection,
                growth_engine=self.companion_growth_engine,
                identity_guard=self.companion_identity_guard,
                growth_config=self._companion_config,
                reflection_emotion=self.companion_reflection_emotion,
                growth_cycle=self.companion_growth_cycle,
                growth_trend_analysis=(
                    self.companion_growth_trend_analyzer
                ),
                hybrid_layer=self.companion_hybrid,
                hybrid_config=self._companion_config,
                presence_engine=self.companion_presence_engine,
                presence_config=self._companion_config,
                constitution_engine=(
                    self.companion_constitution_engine
                ),
                constitution_config=self._companion_config,
                meta_creative=self.companion_meta_creative,
                meta_creative_config=self._companion_config,
                research_engine=self.companion_research,
                research_config=self._companion_config,
                meta_cognition=self.companion_meta_cognition,
                meta_cognition_config=self._companion_config,
            )
            policy_path = config.get("embodied_policy_path")
            if policy_path:
                self._experience.load_policy(policy_path)
            self._initialized = True
        logger.info(f"EmbodiedService 配置已加载: {perm.to_dict()}")

    def load_permission(self, permission: EmbodiedPermissionConfig) -> None:
        self._permission.load_from_config(permission)

    def update_permission(self, **kwargs) -> EmbodiedPermissionConfig:
        return self._permission.update(**kwargs)

    def get_permission(self) -> Dict[str, Any]:
        return self._permission.to_dict()

    def reset_permission(self) -> None:
        self._permission.reset()

    # ── 目标校验 ──────────────────────────────────────────────────
    @staticmethod
    def validate_goal(goal: EmbodiedGoal) -> tuple:
        """校验具身目标

        Returns:
            (True, '') 通过
            (False, error) 不通过
        """
        if goal is None:
            return False, "goal 不能为 None"
        if not goal.description or not goal.description.strip():
            if not goal.intent:
                return False, "目标缺少描述 (description) 或意图 (intent)"
        if goal.priority not in ("low", "medium", "high"):
            return False, f"priority 不合法: {goal.priority}"
        max_steps = goal.constraints.get("max_steps")
        if max_steps is not None:
            try:
                if int(max_steps) <= 0:
                    return False, f"max_steps 必须 > 0: {max_steps}"
            except (TypeError, ValueError):
                return False, f"max_steps 不合法: {max_steps}"
        return True, ""

    # ── 规划 (Think → Plan, 规则驱动) ─────────────────────────────
    @staticmethod
    def plan_actions(goal: EmbodiedGoal) -> List[EmbodiedAction]:
        """从目标生成动作序列 (不执行)

        规则驱动 (本版本不调用 LLM, 保持确定性与可测试):
            - 意图含 scan/探索/扫描 → SCAN
            - 意图含 pick/拿起/抓取 → PICK (target 指定对象)
            - 意图含 place/放置 → PLACE
            - 意图含 move/移动 → MOVE
            - 意图含 inspect/检查/查看 → INSPECT (target 指定对象)
            - 无目标 → EXPLORE
        """
        if goal is None:
            return []
        text = (goal.description + " " + goal.intent).lower()
        target = goal.target

        def mk(action_type: str, intent: str) -> EmbodiedAction:
            return EmbodiedAction.create(
                action_type=action_type, intent=intent, target=target,
                reason=f"目标规划: {goal.description}",
                confidence=0.8,
            )

        plan: List[EmbodiedAction] = []
        for kw, action_type, intent in (
            ("scan", EmbodiedActionType.SCAN.value, "扫描环境"),
            ("扫描", EmbodiedActionType.SCAN.value, "扫描环境"),
            ("探索", EmbodiedActionType.SCAN.value, "扫描环境"),
            ("pick", EmbodiedActionType.PICK.value, "拾取对象"),
            ("拿起", EmbodiedActionType.PICK.value, "拾取对象"),
            ("抓取", EmbodiedActionType.PICK.value, "拾取对象"),
            ("place", EmbodiedActionType.PLACE.value, "放置对象"),
            ("放置", EmbodiedActionType.PLACE.value, "放置对象"),
            ("move", EmbodiedActionType.MOVE.value, "移动主体"),
            ("移动", EmbodiedActionType.MOVE.value, "移动主体"),
            ("inspect", EmbodiedActionType.INSPECT.value, "检查对象"),
            ("检查", EmbodiedActionType.INSPECT.value, "检查对象"),
            ("查看", EmbodiedActionType.INSPECT.value, "检查对象"),
        ):
            if kw in text:
                plan.append(mk(action_type, intent))
                break
        if not plan:
            plan.append(mk(EmbodiedActionType.EXPLORE.value, "探索环境"))
        return plan

    # ── 观察 ──────────────────────────────────────────────────────
    def observe(self, environment: Optional[str] = None) -> EnvironmentState:
        """观察环境并写入世界模型"""
        env = self._resolve_environment(environment)
        state = env.observe()
        self._manager.world_model.update(state)
        self._manager.event_log.record_observe(
            objects=len(state.objects), position=state.location,
            metadata={"environment": env.name},
        )
        logger.info(
            f"[Embodied] 观察 env={env.name} objects={len(state.objects)} "
            f"position={state.position}"
        )
        return state

    def _resolve_environment(self, environment: Optional[str]) -> Environment:
        """解析环境 (指定名 / 默认)"""
        if environment:
            env = self._manager.get_environment(environment)
            if env is None:
                raise EmbodiedServiceError(f"环境不存在: {environment}")
        else:
            env = self._manager.get_default_environment()
        if env is None:
            raise EmbodiedServiceError("无可用环境 (请先注册环境)")
        if not env.is_available():
            raise EmbodiedServiceError(f"环境不可用: {env.name}")
        return env

    def get_state(self, environment: Optional[str] = None) -> EnvironmentState:
        """获取当前环境状态 (不写入世界模型)"""
        env = self._resolve_environment(environment)
        return env.get_state()

    def reset(self, environment: Optional[str] = None) -> EnvironmentState:
        """重置环境"""
        env = self._resolve_environment(environment)
        state = env.reset()
        self._manager.world_model.update(state)
        self._manager.event_log.record_reset(
            scene=getattr(env, "scene", ""), metadata={"environment": env.name},
        )
        logger.info(f"[Embodied] 重置 env={env.name}")
        return state

    # ── 场景生命周期 (V4.3) ───────────────────────────────────────
    def list_environments(self) -> List[Dict[str, Any]]:
        """只读查询: 列出所有环境 (含场景 / 可用性 / 默认标记)"""
        default = self._manager.get_default_environment()
        out: List[Dict[str, Any]] = []
        for info in self._manager.list_environments():
            env = self._manager.get_environment(info["name"])
            item = dict(info)
            item["scene"] = getattr(env, "scene", "")
            item["is_default"] = env is default
            out.append(item)
        return out

    def switch_environment(self, name: str) -> Dict[str, Any]:
        """场景生命周期: 动态切换环境

        流程 (切换前):
            Observe → 记录当前状态 → 生成 RESET Event
        流程 (切换后):
            WorldModel Reset → 建立新场景状态 → 检测同名对象状态变化

        Args:
            name: 目标环境名 (已注册环境 / 内置场景名 room|warehouse)

        Returns:
            迁移记录 dict:
                migration_id / from / to / previous_scene / new_scene /
                same_name_changes / events_count / failures / active_objects / timestamp

        Raises:
            EmbodiedServiceError: 当前无环境 / 目标环境不存在
        """
        with self._lock:
            # 1. 切换前: Observe 当前环境, 记录当前状态
            current = self._resolve_environment(None)
            prev_state = current.observe()
            prev_objects = list(prev_state.objects)

            # 2. 生成 RESET Event (场景迁移)
            current_name = self._manager.get_default_name() or current.name
            self._manager.event_log.record_reset(
                scene=getattr(current, "scene", ""),
                metadata={
                    "event": "environment_switch",
                    "from": current_name,
                    "to": name,
                },
            )

            # 3. 解析目标环境 (内置场景名 → 注册 Mock 环境)
            target = self._manager.get_environment(name)
            if target is None:
                if name in SCENES:
                    target = MockEnvironment(scene=name)
                    self._manager.register_environment(name, target, override=True)
                    logger.info(f"[Embodied] 已注册场景环境: {name}")
                else:
                    raise EmbodiedServiceError(
                        f"环境不存在: {name} (可用: {self._manager.list_names()} / "
                        f"内置场景: {list(SCENES.keys())})"
                    )

            # 4. 切换后: WorldModel Reset
            self._manager.world_model.reset()

            # 5. 设置默认环境 (后续路由)
            self._manager.set_default_environment(name)

            # 6. 建立新场景状态
            new_state: Optional[EnvironmentState] = None
            if target.is_available():
                new_state = target.observe()
                self._manager.world_model.update(new_state)
            self._manager.event_log.record_observe(
                objects=len(new_state.objects) if new_state else 0,
                position=new_state.location if new_state else None,
                metadata={"environment": name, "scene": getattr(target, "scene", "")},
            )

            # 7. 同名对象状态变化检测 (P1 场景迁移认知)
            same_name_changes = SceneManager.same_name_object_changes(
                prev_objects, list(new_state.objects) if new_state else []
            )
            events_stats = self._manager.event_log.stats()

            migration = {
                "from": current_name,
                "to": name,
                "timestamp": _time.time(),
                "previous_scene": self._scene_summary_of(
                    current, prev_state, events_stats,
                    env_name=current_name,
                ),
                "new_scene": self._scene_summary_of(
                    target, new_state, events_stats,
                    env_name=name,
                ) if new_state is not None else None,
                "same_name_changes": same_name_changes,
                "events_count": int(events_stats.get("total", 0)),
                "failures": int((events_stats.get("by_result") or {}).get("failure", 0)),
                "active_objects": (
                    [o.name for o in new_state.objects] if new_state is not None else []
                ),
            }
            migration_id = self._scene_manager.record_migration(migration)
            migration["migration_id"] = migration_id
            logger.info(
                f"[Embodied] 场景切换: {current.name} → {name} "
                f"(同名对象变化 {len(same_name_changes)} 处)"
            )
            return migration

    def _scene_summary_of(
        self,
        env: Environment,
        state: Optional[EnvironmentState],
        events_stats: Dict[str, Any],
        env_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """构建场景摘要 (V4.3 P1 场景迁移认知)

        env_name: 注册表实例名 (默认 env.name 适配器名)
        """
        return SceneManager.build_summary(
            env_name=env_name or env.name,
            scene=getattr(env, "scene", ""),
            state=state,
            events_stats=events_stats,
        )

    # ── 状态预测 (V4.1) ───────────────────────────────────────────
    def predict(
        self,
        action: EmbodiedAction,
        environment: Optional[str] = None,
    ) -> Optional[EnvironmentPrediction]:
        """预测动作对环境的预期影响 (规则驱动)

        用法:
            pred = svc.predict(action)
            if pred.expected_change.get('event') == 'move': ...
        """
        # 确保世界模型有状态 (无状态时观察一次)
        if self._manager.world_model.get_latest() is None:
            try:
                self.observe(environment)
            except EmbodiedServiceError:
                return None
        return self._manager.predict(action)

    def predict_sequence(
        self,
        actions: List[EmbodiedAction],
        environment: Optional[str] = None,
    ) -> Optional[MultiStepPrediction]:
        """多步骤条件预测 (V4.2): 动作序列 → 逐步预期 + 最终预期 + 不变式

        例:
            [MOVE(dx=1), PICK(lamp)] → final_expected = {'lamp': 'held'}

        只预测不执行: 返回结果供 Agent 决策参考。
        """
        if not actions:
            return None
        if self._manager.world_model.get_latest() is None:
            try:
                self.observe(environment)
            except EmbodiedServiceError:
                pass
        return self._manager.predict_sequence(actions, environment=environment)

    def verify_prediction(
        self,
        prediction: EnvironmentPrediction,
        actual_change: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """验证预测与实际变化是否一致"""
        return self._manager.verify_prediction(prediction, actual_change)

    def analyze_cause(
        self,
        action_id: str,
    ) -> Optional[CausalAnalysis]:
        """查询动作的因果分析 (V4.2): 为什么失败 → 补救

        从反馈存储 + 事件时间线重建动作上下文, 输出 CausalAnalysis。
        """
        feedback = self._manager.feedback.get(action_id)
        if feedback is None:
            return None
        action = None
        event = self._manager.event_log.get_events(limit=200)
        for e in event:
            if e.action_id == action_id:
                action = EmbodiedAction.create(
                    action_type=e.action_type or EmbodiedActionType.CUSTOM.value,
                    target=e.target,
                    parameters={"object": e.target or ""},
                )
                break
        return self._manager.analyze_cause(
            feedback, action=action,
            previous_state=self._manager.world_model.get_latest(),
        )

    # ── 具身上下文 (V4.2, 供 Agent 推理) ─────────────────────────
    def build_environment_context(
        self,
        environment: Optional[str] = None,
        include_history: bool = True,
        event_limit: int = 8,
    ) -> Dict[str, Any]:
        """构建具身上下文, 供 Agent 推理 (Agent Reasoning) 使用

        内容:
            - current_state: 当前环境状态 (对象 / 位置 / 条件 / 关系)
            - recent_changes: 最近状态变化 (可选)
            - events: 事件摘要 (V4.2: 过去发生了什么 / 为什么 / 结果)
            - causal_analysis: 最近失败因果 (V4.2)
            - prediction: 稳定性预测 + 置信度 (V4.2)
            - experience: 经验摘要 (V4.2: 高频失败模式 / 成功率趋势)
            - feedback: 最近反馈与成功率
            - environments: 可用环境
            - scene / scene_summary / scene_migration / scene_object_changes (V4.3 P1)
            - experience_policy: 策略统计与近期策略 (V4.3)

        用法 (Agent):
            ctx = svc.build_environment_context()
            reasoning = f"当前环境: {ctx['current_state']} ..."
        """
        latest = self._manager.world_model.get_latest()
        if latest is None:
            try:
                self.observe(environment)
                latest = self._manager.world_model.get_latest()
            except EmbodiedServiceError:
                pass

        ctx: Dict[str, Any] = {
            "current_state": latest.to_dict() if latest else None,
            "environments": self._manager.list_names(),
            "feedback_stats": self._manager.feedback.stats(),
            "memory_stats": self._manager.memory.stats(),
        }
        if include_history:
            ctx["recent_changes"] = self._manager.world_model.state_changes(limit=3)
        # V4.2: 事件摘要 (时间线)
        ctx["events"] = self._manager.event_log.event_history(limit=event_limit)
        ctx["event_stats"] = self._manager.event_log.stats()
        # V4.2: 最近失败因果
        failures = self._manager.event_log.failure_events(limit=3)
        ctx["causal_analysis"] = []
        for ev in failures:
            if ev.action_id:
                causal = self.analyze_cause(ev.action_id)
                if causal is not None:
                    ctx["causal_analysis"].append(causal.to_dict())
        # V4.2: 稳定性预测 + 置信度
        if latest is not None and self._manager.predictor is not None:
            try:
                pred = self._manager.predictor.predict(None, latest)
                ctx["prediction"] = pred.to_dict()
                ctx["prediction_confidence"] = pred.confidence
            except Exception as e:
                logger.warning(f"[Embodied] 稳定性预测失败: {e}")
                ctx["prediction_confidence"] = 0.0
        else:
            ctx["prediction_confidence"] = 0.0
        # V4.2: 经验摘要 (高频失败模式 / 成功率趋势)
        ctx["experience"] = self._manager.memory.summary().to_dict()
        # V4.3 P1: 场景迁移认知 (Scene Summary / Events Count / Failures / Active Objects)
        try:
            env = self._resolve_environment(environment)
        except EmbodiedServiceError:
            env = None
        if env is not None:
            events_stats = self._manager.event_log.stats()
            env_name = environment or self._manager.get_default_name() or env.name
            ctx["scene"] = self._scene_summary_of(env, latest, events_stats, env_name)
            ctx["scene_summary"] = ctx["scene"]
            migration = self._scene_manager.latest()
            ctx["scene_migration"] = migration
            ctx["scene_object_changes"] = (
                migration.get("same_name_changes", []) if migration else []
            )
        # V4.3: 经验策略 (统计 + 近期策略, 供 Agent 长上下文)
        ctx["experience_policy"] = self._experience.report_dict()
        # V4.4: 自适应策略层 (审计摘要 + 趋势 + 生命周期状态)
        ctx["strategy"] = {
            "audit": self._audit.audit_policy_log(limit=5),
            "trends": self._trends.trend_stats(self._traces.all()),
            "lifecycle": self._experience.table.stats()["status_counts"],
            "mode": "rule_based",
        }
        return ctx

    # ── 单动作执行 ────────────────────────────────────────────────
    def execute_action(
        self,
        action: EmbodiedAction,
        confirmed: bool = False,
        record_memory: bool = True,
    ) -> EmbodiedOperationResult:
        """执行单个具身动作

        流程:
            1. 总开关检查 (denied)
            2. 风险评估 (高风险 → awaiting_confirm)
            3. 路由环境 → 执行 (ok / error / unsupported)
            4. 反馈记录 (FeedbackStore + 反馈分析 + 环境记忆)
            5. 状态写入世界模型
        """
        start = _time.perf_counter()

        # 1. 总开关
        allowed, reason = self._permission.check_enabled()
        if not allowed:
            return self._deny(action, reason, start)

        # 2. 风险评估 + 权限判定
        perm = self._permission.evaluate(action)
        if not perm.allowed:
            return self._deny(action, perm.reason, start, permission=perm)

        # 3. 高风险需确认
        if perm.require_confirm and not confirmed:
            return self._finish(
                action, success=True,
                status=EmbodiedStatus.AWAITING_CONFIRM.value,
                error=f"高风险动作待确认: {perm.reason} (请确认后重试)",
                permission=perm, start=start,
            )

        # 4. 路由 + 执行
        env = self._manager.route(action)
        if env is None:
            return self._finish(
                action, success=False,
                status=EmbodiedStatus.ERROR.value,
                error="无可用环境",
                permission=perm, start=start,
            )
        if not env.is_available():
            return self._finish(
                action, success=False,
                status=EmbodiedStatus.UNSUPPORTED.value,
                error=f"环境不可用: {env.name} (本版本仅 Mock 可执行)",
                permission=perm, start=start,
            )

        # 5. 预测 (供决策参考, 不阻塞执行)
        prediction = None
        try:
            if self._manager.world_model.get_latest() is None:
                # 世界模型无状态 → 用环境快照预测 (不写入世界模型)
                s0 = env.get_state()
                if self._manager.predictor is not None:
                    prediction = self._manager.predictor.predict(action, s0)
            else:
                prediction = self._manager.predict(action)
        except Exception as e:
            logger.warning(f"[Embodied] 状态预测失败: {e}")

        try:
            state = env.step(action)
        except EnvironmentError as e:
            logger.error(f"[Embodied] 环境执行异常: {e}")
            return self._finish(
                action, success=False,
                status=EmbodiedStatus.UNSUPPORTED.value,
                error=f"{type(e).__name__}: {e}",
                permission=perm, start=start, prediction=prediction,
            )
        except Exception as e:
            logger.error(f"[Embodied] 执行异常: {e}", exc_info=True)
            return self._finish(
                action, success=False,
                status=EmbodiedStatus.ERROR.value,
                error=f"{type(e).__name__}: {e}",
                permission=perm, start=start, prediction=prediction,
            )

        # 6. 反馈 + 分析 + 状态记忆
        feedback = env.feedback(action.action_id)
        analysis: Optional[FeedbackAnalysis] = None
        if feedback is not None:
            analysis = self._manager.process_feedback(
                feedback, action=action, state=state,
                record_memory=record_memory,
            )
            # V4.3: 失败经验沉淀 (规则驱动, 达到阈值生成策略)
            try:
                self._experience.on_action_result(action, feedback, analysis)
            except Exception as e:
                logger.warning(f"[Embodied] 经验学习失败: {e}")
        self._manager.world_model.update(state)

        # 反馈缺失视为成功 (环境已执行且未抛异常)
        status = (
            EmbodiedStatus.OK.value
            if feedback is None or feedback.result in (
                FeedbackResult.SUCCESS.value, FeedbackResult.NO_CHANGE.value,
                FeedbackResult.PARTIAL.value,
            ) else EmbodiedStatus.ERROR.value
        )
        success = status == EmbodiedStatus.OK.value
        return self._finish(
            action, success=success, status=status,
            state=state, feedback=feedback, analysis=analysis,
            prediction=prediction, permission=perm, start=start,
        )

    def _deny(
        self,
        action: EmbodiedAction,
        reason: str,
        start: float,
        permission: Optional[EmbodiedPermission] = None,
    ) -> EmbodiedOperationResult:
        logger.warning(f"[Embodied] 权限拒绝: {reason} action={action.action_type}")
        self._manager.event_log.record_action(
            action=action,
            result=FeedbackResult.FAILURE.value,
            change={"event": "permission_denied"},
            cause="permission_denied",
            metadata={"reason": reason},
        )
        return self._finish(
            action, success=False, status=EmbodiedStatus.DENIED.value,
            error=reason, permission=permission, start=start,
        )

    def _finish(
        self,
        action: EmbodiedAction,
        success: bool,
        status: str,
        error: Optional[str] = None,
        state: Optional[EnvironmentState] = None,
        feedback: Optional[Feedback] = None,
        analysis: Optional[FeedbackAnalysis] = None,
        prediction: Optional[EnvironmentPrediction] = None,
        permission: Optional[EmbodiedPermission] = None,
        start: float = 0.0,
        iterations: int = 0,
    ) -> EmbodiedOperationResult:
        latency = (_time.perf_counter() - start) * 1000
        return EmbodiedOperationResult(
            success=success, action=action, state=state, feedback=feedback,
            analysis=analysis, prediction=prediction,
            permission=permission, status=status, error=error,
            latency_ms=latency, iterations=iterations,
        )

    # ── 目标闭环 (Observe → Think → Plan → Act → Evaluate) ────────
    def run_goal(
        self,
        goal: EmbodiedGoal,
        confirmed: bool = False,
        max_iterations: Optional[int] = None,
        environment: Optional[str] = None,
        adaptive: bool = True,
    ) -> EmbodiedOperationResult:
        """执行具身目标闭环 (自适应规划 + 经验策略)

        流程:
            1. 校验目标
            2. 规划动作序列 (Think → Plan)
            3. V4.3 策略前置查询 (query policy → suggestions → safe planning):
               - 成功配方 → 初始计划模板 (仍经 Permission Layer)
               - 失败策略 → warning (预防)
            4. 循环: 观察 → 预测 → 执行 → 反馈分析 → 自适应调整 (直到成功或达到上限)
            5. 记录目标轨迹 (GoalTrace) + 经验学习 (失败模式 / 成功配方)

        adaptive=True 时 (V4.1):
            - 动作失败后, 根据 analysis.suggestion 调整下一步动作
            - 如拾取失败建议"移动到目标附近", 自动补充 MOVE 动作
            - 连续失败超过 2 次 → 放弃并记录失败

        V4.3 安全约束:
            - 经验策略只做建议/模板, 动作执行仍必须通过 PermissionChecker
            - 经验学习为规则驱动 (禁止 AI 训练)
        """
        start = _time.perf_counter()
        start_ts = _time.time()

        # 1. 总开关
        allowed, reason = self._permission.check_enabled()
        if not allowed:
            return EmbodiedOperationResult(
                success=False, goal=goal, status=EmbodiedStatus.DENIED.value,
                error=reason, latency_ms=(_time.perf_counter() - start) * 1000,
            )

        # 2. 目标校验
        ok, error = self.validate_goal(goal)
        if not ok:
            return EmbodiedOperationResult(
                success=False, goal=goal, status=EmbodiedStatus.INVALID.value,
                error=error, latency_ms=(_time.perf_counter() - start) * 1000,
            )

        # 3. 解析环境
        try:
            env = self._resolve_environment(environment)
        except EmbodiedServiceError as e:
            return EmbodiedOperationResult(
                success=False, goal=goal, status=EmbodiedStatus.ERROR.value,
                error=str(e), latency_ms=(_time.perf_counter() - start) * 1000,
            )

        # 4. 规划 (Think → Plan)
        plan = self.plan_actions(goal)
        iterations_limit = max_iterations
        if iterations_limit is None:
            try:
                iterations_limit = int(goal.constraints.get("max_steps", 5))
            except (TypeError, ValueError):
                iterations_limit = 5

        # 5. V4.4 策略前置查询 (trigger → scene → goal_type → candidates → ranking → best)
        suggestions: List[Dict[str, Any]] = []
        applied_policies: List[str] = []
        if self._experience.enabled:
            # 场景维度: goal.scene > environment 参数 > 默认环境名
            scene = (
                goal.scene
                or environment
                or self._manager.get_default_name()
                or env.name
            )
            goal_type = infer_goal_type(goal.to_dict(), plan)
            suggestions = self._experience.suggest_for_goal(
                goal, plan, scene=scene, goal_type=goal_type,
            )
            template = next(
                (s for s in suggestions if s["type"] == "template"), None
            )
            if template is not None:
                recipe = self._experience.get_policy(template["trigger"])
                if recipe is not None:
                    plan = self._build_plan_from_recipe(recipe, goal)
                    applied_policies.append(template["trigger"])
                    # V4.4 审计: 策略应用 (可解释: 为什么使用该策略)
                    self._audit.record(
                        trigger=template["trigger"],
                        action="apply",
                        applied=True,
                        goal_id=goal.goal_id,
                        kind=template.get("kind", ""),
                        scene=scene,
                        reason=(
                            f"排序选择: {template.get('reason', '')} "
                            f"(candidates={template.get('candidates', 1)})"
                        ),
                    )
                    logger.info(
                        f"[Embodied] 经验模板应用: {template['trigger']} → "
                        f"{[a.action_type for a in plan]}"
                    )
            # V4.4 审计: 建议 + 拒绝 (未采纳)
            for s in suggestions:
                if s.get("type") == "template" and s["trigger"] in applied_policies:
                    continue
                self._audit.record(
                    trigger=s["trigger"],
                    action=(
                        "apply" if s["trigger"] in applied_policies else "reject"
                    ),
                    applied=s["trigger"] in applied_policies,
                    goal_id=goal.goal_id,
                    kind=s.get("kind", ""),
                    scene=scene,
                    reason=(
                        f"warning 未采纳: {s.get('reason', '')}"
                        if s.get("type") == "warning"
                        else s.get("reason", "")
                    ),
                )
            if suggestions:
                # V4.4 审计: 排序结果汇总
                best = suggestions[0]
                self._audit.record(
                    trigger=best["trigger"],
                    action="rank",
                    applied=best["trigger"] in applied_policies,
                    goal_id=goal.goal_id,
                    kind=best.get("kind", ""),
                    scene=scene,
                    reason=(
                        f"排序结果: 候选 {best.get('candidates', 0)} 个, "
                        f"最优 {best['trigger']} v{best.get('version', 1)} "
                        f"rank={best.get('rank', 1)}, {best.get('reason', '')}"
                    ),
                )
            warnings = [s for s in suggestions if s["type"] == "warning"]
            if warnings:
                logger.info(
                    f"[Embodied] 策略警告 {len(warnings)} 条: "
                    f"{[w['strategy'] for w in warnings]}"
                )

        original_plan_last = len(plan) - 1

        executed: List[str] = []
        executed_actions: List[Dict[str, Any]] = []
        trace_steps: List[GoalStep] = []
        final: Optional[EmbodiedOperationResult] = None
        state: Optional[EnvironmentState] = None
        failures = 0
        adaptive_ids: set = set()  # 自适应插入的动作 id (其成功不代表目标完成)

        for i in range(1, iterations_limit + 1):
            # Observe
            state = env.observe()
            self._manager.world_model.update(state)

            # Plan: 每轮取计划中的下一个动作 (轮转)
            action = plan[(i - 1) % len(plan)]
            action.intent = goal.intent or action.intent

            # Act + Evaluate
            res = self.execute_action(action, confirmed=confirmed)
            executed.append(res.status)
            executed_actions.append({
                "action_type": action.action_type,
                "target": action.target,
                "parameters": dict(action.parameters),
                "success": res.status == EmbodiedStatus.OK.value,
                "result": res.status,
            })
            trace_steps.append(GoalStep(
                step_index=i,
                action=action.to_dict(),
                feedback=res.feedback.to_dict() if res.feedback else None,
                analysis=res.analysis.to_dict() if res.analysis else None,
                observed_state=state.to_dict(),
                result=res.status,
                timestamp=_time.time(),
            ))

            # 自适应调整 (V4.1): 失败 → 按建议调整下一步
            if adaptive and res.feedback is not None and res.analysis is not None:
                if not res.analysis.success and res.analysis.suggestion:
                    if "移动到" in res.analysis.suggestion or "移动" in res.analysis.suggestion:
                        # 拾取/放置类失败 → 先移动到目标附近 (计算 dx/dy)
                        dx, dy, has_target = self._compute_move_step(goal.target)
                        insert_action = EmbodiedAction.create(
                            action_type=EmbodiedActionType.MOVE.value,
                            intent=res.analysis.suggestion,
                            target=goal.target,
                            parameters=({"dx": dx, "dy": dy} if has_target else {}),
                            reason="自适应规划: 根据失败建议移动",
                            confidence=0.6,
                        )
                        plan.insert(i, insert_action)
                        adaptive_ids.add(insert_action.action_id)
                        logger.info(
                            f"[Embodied] 自适应: 插入 MOVE 动作 dx={dx} dy={dy} "
                            f"suggestion={res.analysis.suggestion}"
                        )
                    failures += 1
                elif res.analysis.success:
                    failures = 0

            final = res

            # 目标完成判定: 计划末尾动作成功 且 不是自适应插入动作 → 结束
            goal_done = False
            if res.feedback is not None:
                if res.feedback.result == FeedbackResult.SUCCESS.value:
                    goal_done = (
                        action.action_id not in adaptive_ids
                        and ((i - 1) % len(plan)) == original_plan_last
                    )
            elif res.status == EmbodiedStatus.OK.value:
                goal_done = (
                    action.action_id not in adaptive_ids
                    and ((i - 1) % len(plan)) == original_plan_last
                )
            if goal_done:
                break

            # 连续失败超过阈值 → 放弃
            if failures >= 2:
                logger.warning(f"[Embodied] 连续失败 {failures} 次, 放弃目标 {goal.goal_id}")
                break

        if final is None:
            final = EmbodiedOperationResult(
                success=False, goal=goal, status=EmbodiedStatus.ERROR.value,
                error="未执行任何动作", latency_ms=0.0,
            )

        final.goal = goal
        final.iterations = min(len(executed), iterations_limit)
        final.latency_ms = (_time.perf_counter() - start) * 1000
        final.suggestions = suggestions

        # V4.3: 记录目标轨迹 (Goal Replay 数据源)
        if trace_steps:
            trace = GoalTrace(
                goal_id=goal.goal_id,
                goal=goal.to_dict(),
                plan=[a.to_dict() for a in plan],
                steps=trace_steps,
                event_timeline=[
                    e.to_dict() for e in self._manager.event_log.get_events(limit=200)
                    if e.timestamp >= start_ts
                ],
                final_state=final.state.to_dict() if final.state else None,
                final_status=final.status,
                success=final.success,
                failures=failures,
                iterations=final.iterations,
                environment=(
                    environment
                    or self._manager.get_default_name()
                    or env.name
                ),
                suggestions=suggestions,
                started_at=start_ts,
                ended_at=_time.time(),
                duration_ms=final.latency_ms,
            )
            final.trace_id = self._traces.add(trace)
            # V4.4: 经验学习 (失败模式计数 + 成功配方 + 质量统计 + 生命周期评估)
            if self._experience.enabled:
                self._experience.on_goal_complete(
                    goal=goal,
                    trace=trace,
                    success=final.success,
                    applied_policies=applied_policies,
                    suggestions=suggestions,
                    executed_actions=executed_actions,
                    scene=(
                        goal.scene
                        or environment
                        or self._manager.get_default_name()
                        or env.name
                    ),
                    goal_type=infer_goal_type(goal.to_dict(), plan),
                )

        logger.info(
            f"[Embodied] 目标完成 goal_id={goal.goal_id} "
            f"status={final.status} iterations={final.iterations} "
            f"executed={executed}"
        )
        return final

    def _build_plan_from_recipe(
        self,
        recipe: ExperiencePolicy,
        goal: EmbodiedGoal,
    ) -> List[EmbodiedAction]:
        """从成功配方构建初始计划模板 (V4.3)

        安全约束: 模板只生成动作序列, 每个动作仍经 Permission → Executor
        """
        plan: List[EmbodiedAction] = []
        for item in recipe.action_sequence or []:
            action_type = (
                item.get("action_type") if isinstance(item, dict) else str(item)
            )
            parameters = dict(item.get("parameters", {})) if isinstance(item, dict) else {}
            # V4.4 配方泛化: 归一化参数 (方向 + 距离等级) → 场景无关 dx/dy
            if action_type == EmbodiedActionType.MOVE.value:
                norm = denormalize_move_parameters(
                    parameters.get("direction"),
                    parameters.get("distance_level"),
                )
                if norm.get("dx") or norm.get("dy"):
                    parameters = {**parameters, **norm}
            plan.append(EmbodiedAction.create(
                action_type=action_type,
                intent=goal.intent or recipe.strategy,
                target=goal.target,
                parameters=parameters,
                reason=f"经验模板: {recipe.trigger} (可解释规则)",
                confidence=0.7,
            ))
        if not plan:
            plan = self.plan_actions(goal)
        return plan

    def _compute_move_step(self, target: str) -> tuple:
        """计算朝目标对象移动一步的 dx/dy (自适应规划用)

        Returns:
            (dx, dy, has_target): 无目标/无状态时 has_target=False
        """
        latest = self._manager.world_model.get_latest()
        if latest is None or not target:
            return 0, 0, False
        objs = self._manager.world_model.find_objects(name=target, use_latest=True)
        if not objs:
            return 0, 0, False
        obj = objs[0]
        dx = int(round(obj.position.get("x", 0) - latest.location.get("x", 0)))
        dy = int(round(obj.position.get("y", 0) - latest.location.get("y", 0)))
        return dx, dy, True

    # ── 查询 ──────────────────────────────────────────────────────
    def get_feedback(self, action_id: str) -> Optional[Feedback]:
        return self._manager.feedback.get(action_id)

    def feedback_history(
        self,
        result: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        return self._manager.feedback.query_dicts(result=result, limit=limit)

    def world_history(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        return self._manager.world_model.history_dicts(limit=limit)

    def world_state(self) -> Optional[EnvironmentState]:
        return self._manager.world_model.get_latest()

    def state_changes(self, limit: int = 10) -> List[Dict[str, Any]]:
        """最近状态变化历史 (V4.1)"""
        return self._manager.world_model.state_changes(limit=limit)

    def memory_query(
        self,
        type: Optional[str] = None,
        action_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """查询环境记忆 (V4.1)"""
        return self._manager.memory.query(type=type, action_id=action_id, limit=limit)

    # ── 事件时间线 (V4.2) ─────────────────────────────────────────
    def get_events(
        self,
        limit: int = 100,
        event_type: Optional[str] = None,
        action_type: Optional[str] = None,
        result: Optional[str] = None,
    ) -> List[EnvironmentEvent]:
        """查询环境事件时间线 (最新在前)"""
        return self._manager.event_log.get_events(
            limit=limit, event_type=event_type,
            action_type=action_type, result=result,
        )

    def event_history(
        self,
        limit: int = 100,
        event_type: Optional[str] = None,
        action_type: Optional[str] = None,
        result: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """查询环境事件时间线 (dict 形式, 便于序列化)"""
        return self._manager.event_log.event_history(
            limit=limit, event_type=event_type,
            action_type=action_type, result=result,
        )

    def event_stats(self) -> Dict[str, Any]:
        """事件统计 (按类型 / 结果 / 因果)"""
        return self._manager.event_log.stats()

    # ── 经验摘要 (V4.2) ───────────────────────────────────────────
    def experience_summary(self) -> ExperienceSummary:
        """具身经验摘要: 高频失败模式 / 成功率趋势 / 因果统计"""
        return self._manager.memory.summary()

    def save_memory(self, path: str) -> int:
        """持久化环境记忆 (跨进程复用)"""
        return self._manager.memory.save_to_file(path)

    def load_memory(self, path: str) -> int:
        """加载环境记忆 (跨进程复用)"""
        return self._manager.memory.load_from_file(path)

    # ── Goal Replay (V4.3 目标回放) ───────────────────────────────
    def replay_goal(self, goal_id: str) -> Dict[str, Any]:
        """回放目标轨迹: Step N: Observe → Action → Feedback

        Args:
            goal_id: 目标 ID (run_goal 执行后自动记录)

        Returns:
            {
                'goal_id': ...,
                'environment': ...,
                'steps': [{'step': 1, 'observe': {...}, 'action': {...}, 'feedback': {...}, 'analysis': {...}, 'result': ...}, ...],
                'final_status': ...,
                'success': ...,
                'final_state': ...,
            }

        Raises:
            EmbodiedServiceError: 目标轨迹不存在
        """
        trace = self._traces.get(goal_id)
        if trace is None:
            raise EmbodiedServiceError(f"目标轨迹不存在: {goal_id}")
        return trace.replay_dict()

    def compare_goals(
        self,
        goal_id_a: str,
        goal_id_b: str,
    ) -> Dict[str, Any]:
        """比较两个目标: 步骤数量 / 失败位置 / 时间 / 最终结果

        Raises:
            EmbodiedServiceError: 任一目标轨迹不存在
        """
        a = self._traces.get(goal_id_a)
        if a is None:
            raise EmbodiedServiceError(f"目标轨迹不存在: {goal_id_a}")
        b = self._traces.get(goal_id_b)
        if b is None:
            raise EmbodiedServiceError(f"目标轨迹不存在: {goal_id_b}")
        return {
            "goal_a": {
                "goal_id": a.goal_id,
                "step_count": a.step_count,
                "failure_positions": a.failure_positions,
                "failures": a.failures,
                "duration_ms": round(a.duration_ms, 2),
                "final_status": a.final_status,
                "success": a.success,
            },
            "goal_b": {
                "goal_id": b.goal_id,
                "step_count": b.step_count,
                "failure_positions": b.failure_positions,
                "failures": b.failures,
                "duration_ms": round(b.duration_ms, 2),
                "final_status": b.final_status,
                "success": b.success,
            },
            "comparison": {
                "step_count_delta": a.step_count - b.step_count,
                "failure_count_delta": a.failures - b.failures,
                "duration_delta_ms": round(a.duration_ms - b.duration_ms, 2),
                "result_a": a.final_status,
                "result_b": b.final_status,
                "both_success": a.success and b.success,
                "a_better": (a.success and not b.success) or (
                    a.success == b.success and a.step_count < b.step_count
                ),
            },
        }

    def export_goal_trace(
        self,
        goal_id: str,
        format: str = "json",
    ) -> Dict[str, Any]:
        """导出目标轨迹 (JSON / Structured Text, 供验收 / Debug / 复盘)

        Args:
            goal_id: 目标 ID
            format:  'json' → 轨迹 dict; 'text' → 结构化文本 (export_text 字段)

        Raises:
            EmbodiedServiceError: 目标轨迹不存在 / 格式不支持
        """
        trace = self._traces.get(goal_id)
        if trace is None:
            raise EmbodiedServiceError(f"目标轨迹不存在: {goal_id}")
        if format == "json":
            return {
                "format": "json",
                "trace": trace.to_dict(),
            }
        if format in ("text", "txt"):
            return {
                "format": "text",
                "export": trace.export_text(),
            }
        raise EmbodiedServiceError(f"不支持的导出格式: {format} (可选: json / text)")

    # ── 经验策略查询 (V4.3) ───────────────────────────────────────
    def policy_stats(self) -> Dict[str, Any]:
        """经验策略统计: 数量 / 建议 / 采纳 / 成功 / 命中率 / 降级"""
        return self._experience.stats()

    def query_policies(
        self,
        kind: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """查询经验策略表 (只读)

        Args:
            kind: 'failure' / 'success' / None=全部
        """
        if kind:
            return [p.to_dict() for p in self._experience.table.by_kind(kind, limit=limit)]
        return [p.to_dict() for p in self._experience.table.all(limit=limit)]

    def save_policy(self, path: str) -> int:
        """持久化策略表 (embodied_policy.jsonl)"""
        return self._experience.save_policy(path)

    def load_policy(self, path: str) -> int:
        """加载策略表 (跨进程复用)"""
        return self._experience.load_policy(path)

    # ── V4.4 策略生命周期管理 ─────────────────────────────────────
    def archive_policy(self, trigger: str) -> Optional[Dict[str, Any]]:
        """归档策略: active → archived (不是删除, 可恢复)

        Args:
            trigger: 策略触发标识

        Returns:
            策略 dict / None (策略不存在)
        """
        policy = self._experience.archive_policy(trigger)
        if policy is None:
            return None
        self._audit.record(
            trigger=trigger, action="archive", applied=False,
            reason="人工归档 (策略生命周期管理)",
        )
        return policy.to_dict()

    def restore_policy(self, trigger: str) -> Optional[Dict[str, Any]]:
        """恢复策略: archived → active (重新参与建议)"""
        policy = self._experience.restore_policy(trigger)
        if policy is None:
            return None
        self._audit.record(
            trigger=trigger, action="restore", applied=False,
            reason="人工恢复 (策略生命周期管理)",
        )
        return policy.to_dict()

    def policy_history(self, trigger: str) -> List[Dict[str, Any]]:
        """策略版本历史 (V4.4): 最旧 → 最新 (含当前版本)"""
        return self._experience.policy_history(trigger)

    def evaluate_lifecycle(self) -> Dict[str, Any]:
        """生命周期评估 (V4.4): 老化 → stale / 降级恢复 / 自动降级

        Returns:
            {'aged_to_stale': [...], 'recovered': [...], 'degraded': [...]}
        """
        return self._experience.evaluate_lifecycle()

    def policy_lifecycle_stats(self) -> Dict[str, Any]:
        """策略生命周期统计: 状态分布 (active/degraded/stale/archived)"""
        return self._experience.table.stats()["status_counts"]

    # ── V4.4 趋势统计系统 (数据源 GoalTraceStore) ─────────────────
    def trend_stats(self) -> Dict[str, Any]:
        """趋势统计: 场景成功率 (room/warehouse/custom) + 目标成功率 (pick/move/place/inspect/scan)

        Returns:
            {
                'window': 10,
                'overall': {...},
                'by_scene': {'room': {...}, 'warehouse': {...}},
                'by_goal_type': {'pick': {...}, ...},
                'mode': 'rule_based',
            }
        """
        return self._trends.trend_stats(self._traces.all())

    # ── V4.4 决策审计系统 (独立 Audit Log) ────────────────────────
    def audit_policy_log(self, limit: int = 50, action: Optional[str] = None) -> Dict[str, Any]:
        """决策审计汇总: 应用次数 / 拒绝次数 / 原因 / 近期明细

        Args:
            limit: 近期明细条数 (最新在前)
            action: 按审计动作过滤 (V4.5 治理追踪, 如 'consolidate' / 'rollback')

        Returns:
            {
                'total', 'applied_count', 'rejected_count',
                'by_action', 'by_trigger', 'top_reasons', 'recent',
            }
        """
        return self._audit.audit_policy_log(limit=limit, action=action)

    def audit_entries(self, limit: int = 100) -> List[Dict[str, Any]]:
        """审计明细 (最新在前)"""
        return self._audit.entries(limit=limit)

    def save_audit(self, path: str) -> int:
        """持久化审计日志 (独立存储, 不进入 Agent Memory)"""
        return self._audit.save_to_file(path)

    def load_audit(self, path: str) -> int:
        """加载审计日志 (跨进程复用)"""
        return self._audit.load_from_file(path)

    # ── V4.4 Dry Run 策略预演 (P1: 只模拟不执行) ──────────────────
    def dry_run_suggestion(
        self,
        goal: EmbodiedGoal,
        plan: Optional[List[Any]] = None,
        scene: str = "",
        goal_type: str = "",
    ) -> Dict[str, Any]:
        """策略预演: 只模拟"使用哪个策略 / 计划如何变化"

        特点:
            - 不写统计 (suggest_count 不变)
            - 不修改计划 (调用方 plan 不变)
            - 不写审计 (仅查询模拟)

        Args:
            goal:      目标
            plan:      初始计划 (None → 自动规划)
            scene:     场景 (V4.4 调度维度)
            goal_type: 目标类型 (V4.4 调度维度, 空=自动推断)

        Returns:
            {
                'dry_run': True,
                'suggestions': [...],        # 建议 (dry_run 标记)
                'would_apply_trigger': ... | None,   # 会被应用的最佳模板
                'plan_after': [...],          # 预演后的计划 (仅返回, 不生效)
                'scene': ..., 'goal_type': ...,
            }
        """
        plan = list(plan) if plan else self.plan_actions(goal)
        if not scene:
            scene = (
                goal.scene
                or self._manager.get_default_name()
                or ""
            )
        suggestions = self._experience.suggest_for_goal(
            goal, plan, scene=scene, goal_type=goal_type, dry_run=True,
        )
        template = next(
            (s for s in suggestions if s["type"] == "template"), None
        )
        would_apply: Optional[str] = None
        plan_after = [a.to_dict() for a in plan]
        if template is not None:
            recipe = self._experience.get_policy(template["trigger"])
            if recipe is not None:
                would_apply = template["trigger"]
                plan_after = [a.to_dict() for a in self._build_plan_from_recipe(recipe, goal)]
        return {
            "dry_run": True,
            "suggestions": suggestions,
            "would_apply_trigger": would_apply,
            "plan_after": plan_after,
            "scene": scene,
            "goal_type": goal_type
            or infer_goal_type(goal.to_dict(), plan),
        }

    # ── V4.5 元策略管理 (Meta Strategy Management) ────────────────
    # 一、Strategy System Overview
    def strategy_system_overview(self) -> Dict[str, Any]:
        """策略体系总览: 策略矩阵 (scene×goal_type×kind) + 质量 + 一致性检查

        Returns:
            {
                'generated_at', 'mode',
                'matrix', 'stats' (total/active/degraded/stale/archived/deleted/
                                  version_total/recovered_count),
                'quality' (avg_hit_rate/avg_acceptance_rate/version_health/
                           latest_quality_changes),
                'consistency' (ok/violations),
            }
        """
        return self.governance.strategy_system_overview()

    def strategy_system_report(self) -> str:
        """策略体系总览文本报告"""
        return self.governance.strategy_system_report()

    # 二、Strategy Governance (冗余 / 冲突 / 低效归档 / 回收站)
    def redundant_policies(self) -> Dict[str, Any]:
        """冗余策略检测: 同 scene×goal_type×kind×action_type 且内容一致"""
        return self.governance.redundant_policies()

    def archive_redundant_policies(self, dry_run: bool = True) -> Dict[str, Any]:
        """冗余策略归档 (支持 dry_run 预演)"""
        return self.governance.archive_redundant_policies(dry_run=dry_run)

    def conflicting_policies(self) -> Dict[str, Any]:
        """冲突策略检测: 同一 trigger 多个 active version"""
        return self.governance.conflicting_policies()

    def resolve_conflicts(self, dry_run: bool = True) -> Dict[str, Any]:
        """冲突策略解决: 最新版本优先, 旧版本归档"""
        return self.governance.resolve_conflicts(dry_run=dry_run)

    def archive_candidates(self) -> Dict[str, Any]:
        """低效策略归档候选: 年龄 > min_archive_age_days 且 hit_rate < min_archive_hit_rate"""
        return self.governance.archive_candidates()

    def apply_archival(self, trigger: str, confirm: bool = True) -> Dict[str, Any]:
        """执行低效策略归档 (人工确认流程: 检测 → 建议 → 确认 → 执行)"""
        return self.governance.apply_archival(trigger, confirm=confirm)

    def delete_policy(self, trigger: str) -> Dict[str, Any]:
        """软删除策略 → 回收站 (deleted, retained, 可恢复)"""
        return self.governance.delete_policy(trigger)

    def restore_policy(self, trigger: str) -> Optional[Dict[str, Any]]:
        """恢复策略: archived / deleted → active (V4.4 兼容: 返回 dict / None)"""
        try:
            return self.governance.restore_policy(trigger)
        except Exception as e:
            logger.warning(f"[Embodied] 策略恢复失败: {e}")
            return None

    def purge_policy(self, trigger: str, confirm: bool = True) -> Dict[str, Any]:
        """彻底删除策略 (purge, 不可恢复, 必须 confirm)"""
        return self.governance.purge_policy(trigger, confirm=confirm)

    def recycle_bin(self, limit: int = 100) -> Dict[str, Any]:
        """策略回收站内容 (deleted 策略)"""
        return self.governance.recycle_bin(limit=limit)

    # 三、Strategy Evolution (同化 / 分裂 / 版本比较 / 回滚)
    def consolidate_similar_policies(self, dry_run: bool = True) -> Dict[str, Any]:
        """策略同化: 不同 trigger 相同内容 → Policy Family (共享父级统计)"""
        return self.governance.consolidate_similar_policies(dry_run=dry_run)

    def split_policy(
        self,
        trigger: str,
        by: str = "scene",
        values: Optional[List[str]] = None,
        dry_run: bool = True,
    ) -> Dict[str, Any]:
        """策略分裂: 按 scene / goal_type 拆分 (如 pick_object → warehouse_pick)"""
        return self.governance.split_policy(
            trigger, by=by, values=values, dry_run=dry_run,
        )

    def compare_policy_versions(self, trigger: str) -> Dict[str, Any]:
        """版本比较: version/updated_at/action_sequence/hit_rate/acceptance_rate/
        source_goal_id + healthy/regression 判定"""
        return self.governance.compare_policy_versions(trigger)

    def rollback_policy(self, trigger: str, dry_run: bool = True) -> Dict[str, Any]:
        """策略回滚: 仅最新版本 regression 才允许 (旧版本保留历史)"""
        return self.governance.rollback_policy(trigger, dry_run=dry_run)

    def policy_families(self) -> Dict[str, Any]:
        """Policy Family 汇总 (共享父级统计)"""
        return self.governance.policy_families()

    # P1: 健康检查 + 场景覆盖
    def policy_health_check(self) -> Dict[str, Any]:
        """策略健康检查: healthy/weak/stale/conflict/redundant + 健康评分"""
        return self.governance.policy_health_check()

    def scene_coverage(self) -> Dict[str, Any]:
        """策略覆盖范围: 覆盖率 / 未覆盖场景"""
        return self.governance.scene_coverage()

    # 五、治理 Dry Run 体系化 (统一入口)
    def governance_dry_run(self, action: str, **kwargs) -> Dict[str, Any]:
        """治理预演统一入口 (只模拟不执行)

        支持: archive_redundant / resolve_conflicts / apply_archival /
              consolidate / split / rollback / purge
        返回: 影响策略 / 执行后系统快照差异 / 保护规则检查结果
        """
        return self.governance.governance_dry_run(action, **kwargs)

    # ── V4.5 审计增强 (治理追踪 + 档案导出) ───────────────────────
    def audit_system_export(self) -> Dict[str, Any]:
        """导出完整 JSON 审计档案 (策略体系 + 审计日志 + 健康 + 快照)"""
        return {
            "exported_at": _time.time(),
            "version": "9.5.0",
            "mode": "rule_based",
            "strategy_system": self.strategy_system_overview(),
            "policies": [p.to_dict() for p in self._experience.table.all(limit=0)],
            "audit": {
                "summary": self._audit.audit_policy_log(limit=0),
                "entries": self._audit.entries(limit=0),
            },
            "families": self.governance.policy_families(),
            "recycle_bin": self.governance.recycle_bin(limit=0),
            "health": self.governance.policy_health_check(),
            "snapshot": {
                "policies_total": self._experience.table.count(),
                "status_counts": self._experience.table.stats()["status_counts"],
                "version_total": self._experience.table.stats()["version_total"],
            },
        }

    # ── V4.6 跨目标战略规划 (Cross-Goal Strategic Planning) ──────
    def cross_goal_plan(
        self,
        goals: List[EmbodiedGoal],
        budget: Optional[int] = None,
    ) -> Dict[str, Any]:
        """跨目标战略规划主入口

        Args:
            goals: 目标列表 (>= 1, EmbodiedGoal 或 dict)
            budget: 总步骤预算 (None=默认 max_budget)

        Returns:
            CrossGoalPlan:
                plan_id / goals / groups / shared_steps /
                budget_allocation / explainable_reason / mode
        """
        goal_objs = self._normalize_goals(goals)
        return self.planner.plan(goal_objs, budget=budget, record_audit=True)

    def cross_goal_groups(
        self,
        goals: List[EmbodiedGoal],
    ) -> Dict[str, Any]:
        """目标分组分析 (scene × goal_type × action_sequence)"""
        goal_objs = self._normalize_goals(goals)
        return self.planner.analyze_groups(goal_objs)

    def cross_goal_budget(
        self,
        goals: List[EmbodiedGoal],
        budget: Optional[int] = None,
    ) -> Dict[str, Any]:
        """跨目标预算分配 (优先级 + 策略质量 + 共享节省)"""
        goal_objs = self._normalize_goals(goals)
        if budget is not None and budget > 0:
            from backend.embodied.planning import BudgetAllocator
            alloc = BudgetAllocator(max_budget=budget)
            groups = self.planner.analyze_groups(goal_objs)
            sequences = {}
            for g in groups.get("groups", []):
                for goal_dict in g.get("goals", []):
                    sequences[goal_dict["goal_id"]] = len(
                        g.get("action_sequence", [])
                    )
            demands = alloc.demands(goal_objs, sequences=sequences)
            return alloc.allocate(
                goal_objs, demands=demands,
                strategy_quality=self._quality_map(goal_objs),
            )
        return self.planner.allocate_budget(goal_objs)

    def cross_goal_dry_run(
        self,
        goals: List[EmbodiedGoal],
        budget: Optional[int] = None,
    ) -> Dict[str, Any]:
        """跨目标规划预演 (只模拟不执行, 不写审计)

        Returns:
            {
                'dry_run': True, 'plan': {...}, 'protection_checks': {...},
            }
        """
        plan = self.planner.plan(
            self._normalize_goals(goals), budget=budget, record_audit=False,
        )
        return {
            "dry_run": True,
            "plan": plan,
            "protection_checks": {
                "checks": [
                    {"name": "no_device_control", "passed": True,
                     "reason": "规划只输出方案, 不控制任何设备"},
                    {"name": "no_agent_memory_write", "passed": True,
                     "reason": "规划结果不写入 Agent Memory"},
                    {"name": "permission_layer_untouched", "passed": True,
                     "reason": "执行仍经 Permission Layer (规划不绕过)"},
                    {"name": "rule_based_only", "passed": True,
                     "reason": "纯规则 + 统计 + 阈值, 无黑盒优化"},
                ],
                "passed": True,
            },
        }

    @staticmethod
    def _normalize_goals(goals: List[Any]) -> List[EmbodiedGoal]:
        """目标归一化: EmbodiedGoal 或 dict → EmbodiedGoal"""
        out: List[EmbodiedGoal] = []
        for g in goals or []:
            if isinstance(g, EmbodiedGoal):
                out.append(g)
            elif isinstance(g, dict):
                out.append(EmbodiedGoal.from_dict(g))
            else:
                raise EmbodiedServiceError(f"非法目标类型: {type(g)}")
        return out

    def _quality_map(self, goals: List[EmbodiedGoal]) -> Dict[str, float]:
        """目标最优策略质量 (供预算分配)"""
        q: Dict[str, float] = {}
        for g in goals:
            seq = self.plan_actions(g)
            action_type = seq[0].action_type if seq else ""
            candidates = self._experience.table.candidates(
                action_type=action_type or None,
                scene=g.scene or None,
                goal_type=g.intent or None,
            )
            q[g.goal_id] = max((p.hit_rate for p in candidates), default=0.0)
        return q

    # ── V4.7 长期任务规划 (Long Horizon Planning Layer) ───────────
    def long_horizon_plan(
        self,
        title: str,
        description: str = "",
        phases: Optional[List[str]] = None,
        priority: str = "medium",
        deadline: float = 0.0,
    ) -> Dict[str, Any]:
        """长期任务规划主入口: 创建 → 拆解 (自动/手动) → 任务树

        Args:
            title: 长期目标标题
            description: 描述
            phases: 阶段列表 (None=按模板自动生成)
            priority: 优先级
            deadline: 截止时间戳 (0=无)

        Returns:
            {
                'goal': {...}, 'task_tree': {...},
                'mode': 'rule_based',
            }
        """
        goal = self.long_horizon.create_long_goal(
            title=title, description=description,
            priority=priority, deadline=deadline,
        )
        if phases:
            tree = self.long_horizon.decompose_goal(goal["goal_id"], phases)
        else:
            gen = self.long_horizon.generate_milestones(goal["goal_id"])
            tree = {
                "goal_id": goal["goal_id"],
                "title": goal["title"],
                "status": "active",
                "milestones": gen["milestones"],
            }
        return {"goal": goal, "task_tree": tree, "mode": "rule_based"}

    def long_horizon_decompose(
        self,
        goal_id: str,
        phases: List[str],
        sub_goals_map: Optional[Dict[str, List[str]]] = None,
    ) -> Dict[str, Any]:
        """长期目标拆解 (手动阶段 + 子目标)"""
        return self.long_horizon.decompose_goal(
            goal_id, phases, sub_goals_map,
        )

    def long_horizon_progress(self, goal_id: str) -> Dict[str, Any]:
        """长期任务进度跟踪 (百分比/完成数/阻塞/下一步)"""
        return self.long_horizon.track_progress(goal_id)

    def long_horizon_report(self, goal_id: str) -> str:
        """长期任务进度文本报告"""
        return self.long_horizon.progress_report(goal_id)

    def long_horizon_milestone(
        self,
        goal_id: str,
        milestone_id: str,
        action: str = "complete",
    ) -> Dict[str, Any]:
        """里程碑管理: complete / rollback"""
        if action == "complete":
            return self.long_horizon.complete_milestone(goal_id, milestone_id)
        if action == "rollback":
            return self.long_horizon.rollback_milestone(goal_id, milestone_id)
        raise EmbodiedServiceError(
            f"非法里程碑动作: {action} (可选: complete / rollback)"
        )

    def long_horizon_dependencies(
        self,
        goal_id: str,
        deps: Optional[Dict[str, List[str]]] = None,
    ) -> Dict[str, Any]:
        """长期任务依赖图 (设置/查询)"""
        if deps:
            return self.long_horizon.set_dependencies(goal_id, deps)
        return self.long_horizon.dependency_graph(goal_id)

    def long_horizon_status(
        self,
        goal_id: str,
        action: str,
        reason: str = "",
    ) -> Dict[str, Any]:
        """长期任务状态管理: pause / resume / fail / archive"""
        if action == "pause":
            return self.long_horizon.pause_goal(goal_id, reason)
        if action == "resume":
            return self.long_horizon.resume_goal(goal_id, reason)
        if action == "fail":
            return self.long_horizon.fail_goal(goal_id, reason)
        if action == "archive":
            return self.long_horizon.archive_goal(goal_id, reason)
        raise EmbodiedServiceError(
            f"非法状态动作: {action} (可选: pause / resume / fail / archive)"
        )

    def long_horizon_adjust(
        self,
        goal_id: str,
        trigger: str = "time_change",
        reason: str = "",
    ) -> Dict[str, Any]:
        """长期任务计划调整 (触发条件 → 方案, 不自动执行)"""
        return self.long_horizon.adjust_plan(
            goal_id, trigger=trigger, reason=reason,
        )

    def long_horizon_risk(self, goal_id: str) -> Dict[str, Any]:
        """长期任务风险预测 (历史失败经验 → low/medium/high)"""
        return self.long_horizon.predict_risk(goal_id)

    def long_horizon_time(self, goal_id: str) -> Dict[str, Any]:
        """长期任务时间规划 (deadline / duration / time_window)"""
        return self.long_horizon.time_plan(goal_id)

    def long_horizon_snapshot(self, goal_id: str) -> Dict[str, Any]:
        """长期任务快照 (支持断点恢复)"""
        return self.long_horizon.snapshot(goal_id)

    def long_horizon_plan_milestones(self, goal_id: str) -> Dict[str, Any]:
        """里程碑 → V4.6 跨目标规划衔接 (阶段内子规划)"""
        return self.long_horizon.plan_milestone_goals(
            goal_id, cross_goal_planner=self.planner,
        )

    def long_horizon_dry_run(
        self,
        title: str,
        description: str = "",
        phases: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """长期任务预演: 拆解/时间估计/风险点/依赖关系 (禁止执行)"""
        return self.long_horizon.long_horizon_dry_run(
            title, description=description, phases=phases,
        )

    def long_horizon_list(self) -> List[Dict[str, Any]]:
        """全部长期任务 (简要)"""
        return self.long_horizon.list_goals()

    # ── V5.0 自适应伙伴架构 (Adaptive Companion Architecture) ─────
    def companion_handle(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """主伙伴 Agent 主入口: 意图 → 路由 → 委派 → 汇总

        Args:
            request: 请求 dict (text / intent / query + 附加参数)

        Returns:
            CompanionResponse:
                request_id / intent / assigned_agents / results /
                aggregated / explainable_reason / mode
        """
        if not isinstance(request, dict) or not request:
            raise EmbodiedServiceError("伙伴请求不能为空")
        response = self.companion.handle(request)
        # 审计追踪 (V5.0: companion_handle)
        try:
            self._audit.record(
                trigger="companion",
                action="companion_handle",
                applied=response["aggregated"].get("all_ok", False),
                goal_id=response.get("request_id", ""),
                kind="companion",
                reason=(
                    f"伙伴请求: '{response.get('intent', '')[:40]}' "
                    f"→ {len(response.get('assigned_agents', []))} 个专业 Agent"
                ),
            )
        except Exception as e:
            logger.warning(f"[Companion] 审计记录失败: {e}")
        return response

    def companion_agents(self) -> Dict[str, Any]:
        """专业 Agent 清单 (能力域 / 状态 / 调用数)"""
        return self.companion.agents()

    def companion_route(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """路由分析 (请求 → 专业 Agent, 不执行)"""
        return self.companion.route(request)

    def companion_dry_run(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """伙伴架构预演: 路由与委派方案 (不调用专业 Agent)"""
        return self.companion.dry_run(request)

    def companion_status(self) -> Dict[str, Any]:
        """伙伴架构状态 (人格 / 启用 / 处理数)"""
        return self.companion.status()

    def companion_stats(self) -> Dict[str, Any]:
        """伙伴协同统计 (V5.1: 委派次数 / 成功率 / 平均耗时 / Top 组合)"""
        return self.companion.stats()

    def companion_pipeline(self) -> Dict[str, Any]:
        """Agent 数据管道分析 (V5.2: 依赖顺序 / 阶段明细 / 可解释)"""
        return self.companion._delegator.pipeline.analyze()

    def companion_execute(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """伙伴执行入口 (V5.3: 规划 → 执行 → 反馈 → 闭环)

        Args:
            request: 请求 dict (description/intent/target/scene 等)

        Returns:
            ExecutionRecord:
                execution_id / goal / status / success / actions /
                latency_ms / feedback / error / permission_required
        """
        return self.companion_executor.execute(request)

    def companion_loop(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """伙伴闭环循环 (V5.3: 感知-策略-规划-执行-反馈, 上限内)

        Returns:
            {
                'loop_id', 'iterations', 'max_iterations', 'success',
                'executions': [...], 'feedbacks': [...],
                'final_status', 'explainable_reason', 'mode',
            }
        """
        return self.companion_executor.close_loop(request)

    def companion_correct(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """伙伴自我修正入口 (V5.4: 执行失败 → 规则调整 → 再执行)

        Returns:
            {
                'correction_id', 'success', 'attempts', 'max_attempts',
                'records': [CorrectionRecord...], 'final_status',
                'explainable_reason', 'mode',
            }
        """
        return self.companion_corrector.correct(request)

    def companion_learning(self) -> Dict[str, Any]:
        """伙伴学习结果 (V5.4: 失败/成功模式规则表)

        Returns:
            {
                'enabled', 'threshold',
                'failure_rules', 'success_rules',
                'failure_patterns', 'success_patterns',
                'mode',
            }
        """
        return self.companion_learner.learning()

    def companion_personality(self) -> Dict[str, Any]:
        """伙伴人格状态 (V5.5: 维度/统计/调整原因)

        Returns:
            PersonalityState:
                base / dimensions (warmth/patience/humor/serious) /
                interactions / success_rate / last_adjust
        """
        return self.companion_personality_engine.personality()

    def companion_adjust_personality(self, context: str) -> Dict[str, Any]:
        """伙伴人格调整 (V5.5: 情境 → 维度调整 → 审计)

        Args:
            context: 情境 (success / failure / consecutive_fail /
                     casual_chat / serious_task)

        Returns:
            {
                'applied', 'context', 'base', 'dimensions',
                'adjustment', 'result', 'reason',
            }
        """
        return self.companion_personality_engine.adjust(context)

    def companion_relationship(self) -> Dict[str, Any]:
        """伙伴关系状态 (V5.6: 信任/熟悉/沟通风格/阶段)"""
        return self.companion_relationship_manager.relationship()

    def companion_relationship_update(self, success: bool) -> Dict[str, Any]:
        """伙伴关系更新 (V5.6: 按互动结果规则更新)"""
        return self.companion_relationship_manager.update(success)

    def companion_personality_stability(self) -> Dict[str, Any]:
        """伙伴人格稳定状态 (V5.6: 当前/基础/衰减/调整历史)"""
        return self.companion.personality_stability()

    def companion_window_stats(self, days: int = 30) -> Dict[str, Any]:
        """伙伴窗口统计 (V5.6: 7/30 天成功率)"""
        return self.companion.window_stats(days=days)

    def companion_experience_stats(self) -> Dict[str, Any]:
        """经历统计 (V5.7: 数量/类型分布/平均价值)"""
        return self.companion.experience_stats()

    def companion_experience_relevant(
        self, trigger: str, limit: int = 5,
    ) -> List[Dict[str, Any]]:
        """相关经验 (V5.7: 供未来行为参考)"""
        return self.companion.experience_relevant(
            trigger=trigger, limit=limit,
        )

    def companion_experience_reflection(self) -> Dict[str, Any]:
        """反思报告 (V5.7: Observation/发现/Suggestion)"""
        return self.companion.experience_reflection()

    def companion_experience_audit(self, limit: int = 100) -> Dict[str, Any]:
        """经历审计 (V5.7)"""
        return self.companion.experience_audit(limit=limit)

    def companion_reflection(self) -> Dict[str, Any]:
        """反思报告 (V5.8: 经历 → 模式/失败/建议/置信度)"""
        return self.companion.reflection()

    def companion_reflection_validated(self) -> Dict[str, Any]:
        """反思已验证经历 (V5.8: 只 CONFIRMED 进入长期参考)"""
        return self.companion.reflection_with_verification()

    def companion_verification_stats(self) -> Dict[str, Any]:
        """验证统计 (V5.8: 状态分布)"""
        return self.companion.verification_stats()

    def companion_verification_confirm(self,
                                       experience_id: str) -> Dict[str, Any]:
        """手动验证经历 (V5.8: 补证据 → CONFIRMED)"""
        return self.companion.verification_confirm(experience_id)

    def companion_verification_reject(self,
                                      experience_id: str) -> Dict[str, Any]:
        """拒绝经验 (V5.8: 反例 → REJECTED)"""
        return self.companion.verification_reject(experience_id)

    def companion_proposal_stats(self) -> Dict[str, Any]:
        """改进建议统计 (V5.8: Proposal ≠ Action)"""
        return self.companion.proposal_stats()

    # ── V5.9 创造智能与价值发现 (Creative Intelligence) ─────────
    def companion_creative_run(self) -> Dict[str, Any]:
        """创造闭环 (V5.9: 发现机会 → 评估 → 推理 → 提案 → 模拟)

        注意: 不自动执行, 方案需审批
        """
        return self.companion.creative_run()

    def companion_creative_detect(self) -> List[Dict[str, Any]]:
        """发现价值机会 (V5.9: 只基于 CONFIRMED 经验)"""
        return self.companion.creative_detect()

    def companion_creative_evaluate(self,
                                    opportunity_id: str) -> Dict[str, Any]:
        """评估机会价值 (V5.9: Impact/Frequency/Benefit/Feasibility/Risk)"""
        return self.companion.creative_evaluate(opportunity_id)

    def companion_creative_propose(self,
                                   opportunity_id: str) -> Dict[str, Any]:
        """生成创造方案 (V5.9: 评估 + 推理 + 方案)"""
        return self.companion.creative_propose(opportunity_id)

    def companion_creative_simulate(self,
                                    proposal_id: str) -> Dict[str, Any]:
        """执行前模拟 (V5.9: 预期收益/风险/副作用)"""
        return self.companion.creative_simulate(proposal_id)

    def companion_creative_approve(self, proposal_id: str,
                                   approver: str = "user") -> Dict[str, Any]:
        """批准创造方案 (V5.9: PENDING → APPROVED)"""
        return self.companion.creative_approve(proposal_id, approver)

    def companion_creative_reject(self, proposal_id: str,
                                  reason: str = "") -> Dict[str, Any]:
        """拒绝创造方案 (V5.9)"""
        return self.companion.creative_reject(proposal_id, reason)

    def companion_creative_execute(self,
                                   proposal_id: str) -> Dict[str, Any]:
        """执行创造方案 (V5.9: 仅 APPROVED 可执行)"""
        return self.companion.creative_execute(proposal_id)

    def companion_creative_record_result(
        self, proposal_id: str, success: bool, result: str = "",
    ) -> Dict[str, Any]:
        """记录创造结果 → 新经验 (V5.9: 闭环)"""
        return self.companion.creative_record_result(
            proposal_id, success, result,
        )

    def companion_creative_stats(self) -> Dict[str, Any]:
        """创造层统计 (V5.9: 机会/评估/提案/模拟/记忆)"""
        return self.companion.creative_stats()

    def companion_creative_audit(self, limit: int = 100) -> Dict[str, Any]:
        """创造审计 (V5.9)"""
        return self.companion.creative_audit(limit=limit)

    # ── V6.0 长期身份与成长连续 (Continuity) ────────────────────
    def companion_persistence_save(self, path: str = "") -> int:
        """全量状态持久化 (V6.0: 经历/验证/关系/人格/反思/创造)

        Args:
            path: 目标路径 (空 → 配置路径)

        Returns:
            写入条数
        """
        return self.companion.persistence_save(path)

    def companion_persistence_load(self, path: str = "") -> Dict[str, Any]:
        """状态恢复 (V6.0: 失败跳过不崩溃, 审计记录)"""
        return self.companion.persistence_load(path)

    def companion_growth_report(self) -> Dict[str, Any]:
        """长期成长报告 (V6.0: 经验/认知/创造/关系四维)"""
        return self.companion.growth_report()

    def companion_experience_lifecycle(self) -> Dict[str, Any]:
        """记忆生命周期整理 (V6.0: Active/Cold/Archive/Recycle)"""
        return self.companion.experience_lifecycle()

    def companion_memory_overview(self) -> Dict[str, Any]:
        """记忆体系总览 (V6.0)"""
        return self.companion.memory_overview()

    def companion_identity_history(self,
                                   limit: int = 50) -> Dict[str, Any]:
        """身份历史 (V6.0: 快照/差异/审计)"""
        return self.companion.identity_history(limit=limit)

    def companion_identity_capture(self,
                                   reason: str = "") -> Dict[str, Any]:
        """记录身份快照 (V6.0)"""
        return self.companion.identity_capture(reason)

    def companion_identity_propose_change(
        self, reason: str, changes: Dict[str, Any],
    ) -> Dict[str, Any]:
        """提出身份变化 (V6.0: 必须审批, 不可变字段禁止)"""
        return self.companion.identity_propose_change(reason, changes)

    def companion_identity_approve_change(
        self, snapshot_id: str, approver: str = "user",
    ) -> Dict[str, Any]:
        """批准身份变化 (V6.0)"""
        return self.companion.identity_approve_change(
            snapshot_id, approver,
        )

    def companion_identity_reject_change(
        self, snapshot_id: str, reason: str = "",
    ) -> Dict[str, Any]:
        """拒绝身份变化 (V6.0)"""
        return self.companion.identity_reject_change(
            snapshot_id, reason,
        )

    def companion_growth_trend(self, bucket: str = "day") -> Dict[str, Any]:
        """成长趋势 (V6.0: 按天/周/月)"""
        return self.companion.growth_trend(bucket=bucket)

    def companion_growth_metrics(self) -> Dict[str, Any]:
        """成长指标 (V6.0)"""
        return self.companion.growth_metrics()

    def companion_continuity_stats(self) -> Dict[str, Any]:
        """连续层统计 (V6.0)"""
        return self.companion.continuity_stats()

    def companion_continuity_audit(self,
                                   limit: int = 100) -> Dict[str, Any]:
        """持久化审计 (V6.0)"""
        return self.companion.continuity_audit(limit=limit)

    # ── V6.1.1 情绪表征与成长节律 (Emotion & Rhythm) ────────────
    def companion_emotion(self) -> Dict[str, Any]:
        """当前情绪状态 (V6.1.1: positivity/energy/warmth)"""
        return self.companion.emotion()

    def companion_emotion_adjust(self, context: str) -> Dict[str, Any]:
        """按情境调整情绪 (V6.1.1: 规则驱动, 可解释)"""
        return self.companion.emotion_adjust(context)

    def companion_emotion_decay(self) -> Dict[str, Any]:
        """情绪自然衰减 (V6.1.1: 回归基线)"""
        return self.companion.emotion_decay()

    def companion_emotion_audit(self,
                                limit: int = 100) -> Dict[str, Any]:
        """情绪审计 (V6.1.1: 所有变化可追踪)"""
        return self.companion.emotion_audit(limit=limit)

    def companion_emotion_history(self,
                                  limit: int = 50) -> Dict[str, Any]:
        """情绪历史 (V6.1.1: 供 Reflection/Growth)"""
        return self.companion.emotion_history(limit=limit)

    def companion_growth_rhythm(self) -> Dict[str, Any]:
        """成长节律状态 (V6.1.1: 自动采集/整理/快照/反思)"""
        return self.companion.growth_rhythm()

    def companion_growth_rhythm_cycle(
        self, request: Dict[str, Any] = None,
        response: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        """手动运行节律循环 (V6.1.1)"""
        return self.companion.growth_rhythm_cycle(request, response)

    def companion_rhythm_audit(self,
                               limit: int = 100) -> Dict[str, Any]:
        """节律审计 (V6.1.1: 自动行为可追踪)"""
        return self.companion.rhythm_audit(limit=limit)

    # ── V6.2 多模态交互与感知 (Multimodal Interaction) ─────────
    def companion_expression_generate(
        self,
        emotion: Dict[str, Any] = None,
        relationship: Dict[str, Any] = None,
        task: Dict[str, Any] = None,
        conversation: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        """生成表达建议 (V6.2: style/tone/reason/confidence)"""
        return self.companion.expression_generate(
            emotion=emotion, relationship=relationship,
            task=task, conversation=conversation,
        )

    def companion_expression_status(self) -> Dict[str, Any]:
        """表达引擎状态 (V6.2: 规则命中/风格分布)"""
        return self.companion.expression_status()

    def companion_expression_audit(self,
                                   limit: int = 100) -> Dict[str, Any]:
        """表达审计 (V6.2)"""
        return self.companion.expression_audit(limit=limit)

    def companion_vision_ocr(self, image=None) -> Dict[str, Any]:
        """OCR (V6.2: 经权限, 未授权返回 PERMISSION_DENIED)"""
        return self.companion.vision_ocr(image)

    def companion_vision_detect(self, image=None) -> Dict[str, Any]:
        """目标检测 (V6.2: 经权限)"""
        return self.companion.vision_detect(image)

    def companion_perception_receive(
        self, source: str, content: Dict[str, Any],
        confidence: float = 0.0,
    ) -> Dict[str, Any]:
        """接收感知事件 (V6.2: 不直接进入 Memory)"""
        return self.companion.perception_receive(
            source=source, content=content, confidence=confidence,
        )

    def companion_perception_verify(self,
                                    event_id: str) -> Dict[str, Any]:
        """验证感知事件 (V6.2: 通过 → 记忆候选)"""
        return self.companion.perception_verify(event_id)

    def companion_perception_audit(self,
                                   limit: int = 100) -> Dict[str, Any]:
        """感知审计 (V6.2: 所有自动行为可追踪)"""
        return self.companion.perception_audit(limit=limit)

    def companion_perception_stats(self) -> Dict[str, Any]:
        """感知统计 (V6.2: 事件/验证/权限, 保持旧结构)"""
        return self.companion_perception_service.stats()

    def companion_perception_memory_candidates(self) -> Dict[str, Any]:
        """感知记忆候选 (V6.2: 只读, 未存储)"""
        return self.companion.perception_memory_candidates()

    # ── V6.3 具身感知与行动集成 (Memory Gate & Pipeline) ────────
    def companion_perception_memory_gate(
        self, candidate_id: str,
    ) -> Dict[str, Any]:
        """记忆网关 (V6.3: 候选 → 校验 → 反思 → 批准 → 经历)"""
        return self.companion.perception_memory_gate(candidate_id)

    def companion_perception_memory_gate_stats(self) -> Dict[str, Any]:
        """记忆网关统计 (V6.3: 候选/批准/拒绝)"""
        return self.companion.perception_memory_gate_stats()

    def companion_perception_frame(
        self, content: Dict[str, Any], meaning: str = "",
        verified: bool = False, ftype: str = "vision",
    ) -> Dict[str, Any]:
        """感知帧注入管道 (V6.3: 未验证禁止行动)"""
        return self.companion.perception_frame(
            content=content, meaning=meaning,
            verified=verified, ftype=ftype,
        )

    def companion_perception_pipeline_stats(self) -> Dict[str, Any]:
        """感知管道统计 (V6.3: 帧数量/验证/行动拦截)"""
        return self.companion.perception_pipeline_stats()

    # ── V6.4 感知-记忆认知集成 (Reflection & Provenance) ────────
    def companion_reflection_evaluate(
        self, candidate: Dict[str, Any],
    ) -> Dict[str, Any]:
        """反思评估候选 (V6.4: Advisor, 非决策者)"""
        return self.companion.reflection_evaluate(candidate)

    def companion_counterfactual_check(
        self, candidate: Dict[str, Any],
    ) -> Dict[str, Any]:
        """反事实验证 (V6.4: 降低幻觉进入 Memory)"""
        return self.companion.counterfactual_check(candidate)

    def companion_experience_create(
        self, source: str, modalities: list,
        meaning: str, confidence: float = 0.0,
        impact: str = "",
    ) -> Dict[str, Any]:
        """创建多模态经验对象 (V6.4: 统一结构含 Provenance)"""
        return self.companion.experience_create(
            source=source, modalities=modalities,
            meaning=meaning, confidence=confidence,
            impact=impact,
        )

    def companion_experience_provenance(
        self, experience_id: str,
    ) -> Dict[str, Any]:
        """经验来源链 (V6.4: 可追溯)"""
        return self.companion.experience_provenance(experience_id)

    def companion_perception_cognitive_stats(self) -> Dict[str, Any]:
        """感知认知统计 (V6.4: 事件/验证/批准/拒绝/反思/反事实)"""
        return self.companion.perception_stats()

    def companion_multimodal_event_create(
        self, source: str, meaning: str,
        impact: str = "",
    ) -> Dict[str, Any]:
        """创建多模态成长事件 (V6.4: Growth Tracker)"""
        return self.companion.multimodal_event_create(
            source=source, meaning=meaning, impact=impact,
        )

    # ── V6.5 认知反思与自主成长 (Cognitive Reflection & Growth) ─
    def companion_reflection_analyze(self) -> Dict[str, Any]:
        """认知反思 (V6.5: 经历 → 认知总结)"""
        return self.companion.reflection_analyze()

    def companion_pattern_detect(self) -> Dict[str, Any]:
        """模式检测 (V6.5: 统计驱动)"""
        return self.companion.pattern_detect()

    def companion_contradiction_check(
        self, experience: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        """矛盾检测 (V6.5: 新经验 vs 旧知识 vs Identity)"""
        return self.companion.contradiction_check(experience)

    def companion_growth_generate(self) -> Dict[str, Any]:
        """生成成长建议 (V6.5)"""
        return self.companion.growth_generate()

    def companion_growth_evaluate(
        self, proposal: Dict[str, Any],
    ) -> Dict[str, Any]:
        """评估成长建议 (V6.5: Identity/Safety/Value)"""
        return self.companion.growth_evaluate(proposal)

    def companion_growth_apply(
        self, proposal: Dict[str, Any],
        evaluation: Dict[str, Any] = None,
        changes: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        """受控应用成长 (V6.5: 仅 approved, 默认需人工确认)"""
        return self.companion.growth_apply(
            proposal, evaluation, changes,
        )

    def companion_growth_audit(self,
                               limit: int = 100) -> Dict[str, Any]:
        """成长审计 (V6.5: 全过程可追溯)"""
        return self.companion.growth_audit(limit=limit)

    def companion_growth_stats(self) -> Dict[str, Any]:
        """成长统计 (V6.5: 反思/建议/评估/应用/守护)"""
        return self.companion.growth_stats()

    # ── V6.6 自主成长成熟化 (Autonomous Growth Maturation) ───────
    def companion_reflection_emotion_adjust(self) -> Dict[str, Any]:
        """反思-情绪集成 (V6.6: 经 Meaning, 不直接修改情绪/人格)"""
        return self.companion.reflection_emotion_adjust()

    def companion_growth_cycle_run(
        self, trigger: str = "auto",
    ) -> Dict[str, Any]:
        """运行成长闭环 (V6.6: 反思→建议→评估→待审批)"""
        return self.companion.growth_cycle_run(trigger=trigger)

    def companion_growth_pending_approvals(
        self, limit: int = 50,
    ) -> Dict[str, Any]:
        """待审批列表 (V6.6: 应用永远需人工)"""
        return self.companion.growth_pending_approvals(
            limit=limit,
        )

    def companion_growth_cycle_decide(
        self, pending_id: str, decision: str,
        reason: str = "",
    ) -> Dict[str, Any]:
        """待审批决策 (V6.6: 批准仅标记, 应用仍经人工审批)"""
        return self.companion.growth_cycle_decide(
            pending_id, decision, reason,
        )

    def companion_growth_trend_analysis(
        self, period: str = "day",
    ) -> Dict[str, Any]:
        """成长趋势分析 (V6.6: 反思/成长/身份/记忆)"""
        return self.companion.growth_trend_analysis(
            period=period,
        )

    # ── V6.8 混合智能层 (Hybrid Intelligence Layer) ──────────────
    def companion_hybrid_route(
        self, task_context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """智能调度路由 (V6.8: 任务 → LOCAL/CLOUD/HYBRID)"""
        return self.companion.hybrid_route(task_context)

    def companion_hybrid_execute(
        self, task_context: Dict[str, Any],
        request: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        """执行智能调用 (V6.8: 路由→执行→验证→审计)"""
        return self.companion.hybrid_execute(
            task_context, request,
        )

    def companion_hybrid_gateway_request(
        self, model: str,
        payload: Dict[str, Any] = None,
        value_score: float = 0.0,
    ) -> Dict[str, Any]:
        """网关直调 (V6.8: 低价值任务禁止高成本模型)"""
        return self.companion.hybrid_gateway_request(
            model, payload, value_score,
        )

    def companion_hybrid_stats(self) -> Dict[str, Any]:
        """混合智能层统计 (V6.8: 调度/成本/安全/审计)"""
        return self.companion.hybrid_stats()

    def companion_hybrid_audit(
        self, limit: int = 100,
    ) -> Dict[str, Any]:
        """智能调用审计 (V6.8: 可查询/可追踪/可回放)"""
        return self.companion.hybrid_audit(limit=limit)

    # ── V7.0 具身表达层 (Embodied Presence Layer) ────────────────
    def companion_presence_state(self) -> Dict[str, Any]:
        """当前表达状态 (V7.0: 表情/姿态/强度/互动模式)"""
        return self.companion.presence_state()

    def companion_presence_update(
        self, context: str = "idle",
    ) -> Dict[str, Any]:
        """表达状态机更新 (V7.0: 经映射/有限幅/身份守护)"""
        return self.companion.presence_update(context)

    def companion_presence_interpreter(
        self, context: str = "idle",
    ) -> Dict[str, Any]:
        """表达解释器 (V7.0: 只读映射, 不改变状态)"""
        return self.companion.presence_interpreter(context)

    def companion_presence_continuity(
        self, window_days: int = 30,
    ) -> Dict[str, Any]:
        """存在连续性 (V7.0: 沟通节奏/表达偏好)"""
        return self.companion.presence_continuity(
            window_days=window_days,
        )

    def companion_presence_stats(self) -> Dict[str, Any]:
        """表达引擎统计 (V7.0: 状态/映射/记忆/审计)"""
        return self.companion.presence_stats()

    # ── V8.0 宪法引擎 (Constitution Engine, 最高治理层) ──────────
    def companion_constitution_review(
        self, action_context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """治理审查 (V8.0: 任何模块行为必须接受约束)"""
        return self.companion.constitution_review(
            action_context,
        )

    def companion_constitution_arbitrate(
        self, conflict_event: Dict[str, Any],
    ) -> Dict[str, Any]:
        """跨层冲突仲裁 (V8.0: 固定优先级)"""
        return self.companion.constitution_arbitrate(
            conflict_event,
        )

    def companion_constitution_validate_output(
        self, output_text: str, source: str = "",
    ) -> Dict[str, Any]:
        """输出验证 (V8.0: 现实验证 + 防幻觉)"""
        return self.companion.constitution_validate_output(
            output_text, source,
        )

    def companion_constitution_principles(self) -> Dict[str, Any]:
        """治理原则定义 (V8.0)"""
        return self.companion.constitution_principles()

    def companion_constitution_ledger(
        self, limit: int = 100,
    ) -> Dict[str, Any]:
        """治理总账 (V8.0: 可查询/可回放/可审计)"""
        return self.companion.constitution_ledger(limit=limit)

    def companion_constitution_propose_evolution(
        self, change: str, reason: str = "",
        operator: str = "system",
    ) -> Dict[str, Any]:
        """演化建议 (V8.0: 最高原则修改, 永不自动应用)"""
        return self.companion.constitution_propose_evolution(
            change, reason, operator,
        )

    def companion_constitution_evolution_decide(
        self, proposal_id: str, decision: str,
        reviewer: str = "human",
    ) -> Dict[str, Any]:
        """演化建议审批 (V8.0: 批准仅标记)"""
        return self.companion.constitution_evolution_decide(
            proposal_id, decision, reviewer,
        )

    def companion_constitution_stats(self) -> Dict[str, Any]:
        """宪法引擎统计 (V8.0)"""
        return self.companion.constitution_stats()

    # ── V8.5 元创造力引擎 (Creative Intelligence Engine) ────────
    def companion_meta_creative_create(
        self, problem: str,
        context: Dict[str, Any] = None,
        human_input: str = None,
    ) -> Dict[str, Any]:
        """完整创造流程 (V8.5: 火花→重组→假设→验证→输出)"""
        return self.companion.meta_creative_create(
            problem, context, human_input,
        )

    def companion_meta_creative_sparks(
        self, problem: str,
    ) -> Dict[str, Any]:
        """思维火花 (V8.5)"""
        return self.companion.meta_creative_sparks(problem)

    def companion_meta_creative_hypothesis(
        self, problem: str,
    ) -> Dict[str, Any]:
        """假设构建 (V8.5: 经验证)"""
        return self.companion.meta_creative_hypothesis(problem)

    def companion_meta_creative_stats(self) -> Dict[str, Any]:
        """创造引擎统计 (V8.5)"""
        return self.companion.meta_creative_stats()

    # ── V9.0 自主研究探索 (Autonomous Research & Exploration) ──
    def companion_research_explore(
        self, goal: str, user_value: str = "",
    ) -> Dict[str, Any]:
        """受治理的主动探索 (V9.0)"""
        return self.companion.research_explore(goal, user_value)

    def companion_research_observe(
        self, obs_type: str, content: str,
        source: str = "system",
    ) -> Dict[str, Any]:
        """采集研究观察 (V9.0)"""
        return self.companion.research_observe(
            obs_type, content, source,
        )

    def companion_research_questions(self) -> Dict[str, Any]:
        """当前研究问题 (V9.0)"""
        return self.companion.research_questions()

    def companion_research_audit(
        self, limit: int = 100,
    ) -> Dict[str, Any]:
        """研究审计 (V9.0: 全过程可追踪)"""
        return self.companion.research_audit(limit=limit)

    def companion_research_stats(self) -> Dict[str, Any]:
        """研究引擎统计 (V9.0)"""
        return self.companion.research_stats()

    # ── V9.5 元认知引擎 (Meta-Cognition Engine) ─────────────────
    def companion_meta_cognition_monitor(
        self, task: str, reasoning_type: str = "rules",
        confidence: float = 0.5, uncertainty: str = "",
        resources: list = None,
    ) -> Dict[str, Any]:
        """记录认知过程 (V9.5)"""
        return self.companion.meta_cognition_monitor(
            task, reasoning_type, confidence, uncertainty,
            resources,
        )

    def companion_meta_cognition_evaluate(
        self, monitor_entry: Dict[str, Any],
        output_text: str = "",
    ) -> Dict[str, Any]:
        """推理四维评价 (V9.5)"""
        return self.companion.meta_cognition_evaluate(
            monitor_entry, output_text,
        )

    def companion_meta_cognition_detect_error(
        self, error_text: str, trigger: str = "",
    ) -> Dict[str, Any]:
        """错误分类 (V9.5)"""
        return self.companion.meta_cognition_detect_error(
            error_text, trigger,
        )

    def companion_meta_cognition_reflect(
        self, experience: str, analysis: str = "",
        adjustment: str = "",
    ) -> Dict[str, Any]:
        """认知反思 (V9.5: 调整经宪法)"""
        return self.companion.meta_cognition_reflect(
            experience, analysis, adjustment,
        )

    def companion_meta_cognition_verify(
        self, conclusion: str, evidence: str = "",
        reasoning: str = "", confidence: float = 0.5,
    ) -> Dict[str, Any]:
        """输出前自我验证 (V9.5)"""
        return self.companion.meta_cognition_verify(
            conclusion, evidence, reasoning, confidence,
        )

    def companion_meta_cognition_stats(self) -> Dict[str, Any]:
        """元认知引擎统计 (V9.5)"""
        return self.companion.meta_cognition_stats()

    # ── V10.0 热机健康指标 (Warm Runtime Health Metrics) ───────
    def companion_health(self) -> Dict[str, Any]:
        """热机健康指标 (V10.0: Cognitive/Memory/Growth/Safety 四维)

        Returns:
            {
                'mode', 'enabled', 'version', 'generated_at',
                'overall': {'score', 'level', 'reason'},
                'cognitive': {...}, 'memory': {...},
                'growth': {...}, 'safety': {...},
            }
        """
        return self.companion.health()

    # ── V10.1 交互协议 (Interaction Protocol Layer) ─────────────
    def companion_interaction_begin_session(
        self, goal: str = "", mode: str = "casual",
    ) -> Dict[str, Any]:
        """开始交互会话 (V10.1: 目标/交流模式)"""
        return self.companion.interaction_begin_session(goal, mode)

    def companion_interaction_update_stage(
        self, stage: str,
    ) -> Dict[str, Any]:
        """更新会话任务阶段 (V10.1)"""
        return self.companion.interaction_update_stage(stage)

    def companion_interaction_set_context(
        self, context: str,
    ) -> Dict[str, Any]:
        """设置当前上下文 (V10.1: 经筛选, 不等同长期记忆)"""
        return self.companion.interaction_set_context(context)

    def companion_interaction_add_pending(
        self, item: str,
    ) -> Dict[str, Any]:
        """添加未完成事项 (V10.1)"""
        return self.companion.interaction_add_pending(item)

    def companion_interaction_conversation_snapshot(
        self,
    ) -> Dict[str, Any]:
        """会话状态快照 (V10.1)"""
        return self.companion.interaction_conversation_snapshot()

    def companion_interaction_filter_context(
        self, text: str,
    ) -> Dict[str, Any]:
        """上下文筛选 (V10.1)"""
        return self.companion.interaction_filter_context(text)

    def companion_interaction_begin_tool_flow(
        self, intent: str,
    ) -> Dict[str, Any]:
        """开始工具交互流程 (V10.1)"""
        return self.companion.interaction_begin_tool_flow(intent)

    def companion_interaction_advance_tool_flow(
        self, flow_id: str, stage: str, detail: str = "",
    ) -> Dict[str, Any]:
        """推进工具流程 (V10.1)"""
        return self.companion.interaction_advance_tool_flow(
            flow_id, stage, detail,
        )

    def companion_interaction_execute_tool(
        self,
        flow_id: str,
        tool_name: str,
        args: dict = None,
    ) -> Dict[str, Any]:
        """执行工具调用 (V10.1: 交互协议只编排记录, 不执行工具)"""
        return self.companion.interaction_execute_tool(
            flow_id, tool_name, None, args,
        )

    def companion_interaction_finish_tool_flow(
        self, flow_id: str, response: str = "",
    ) -> Dict[str, Any]:
        """完成工具流程 (V10.1)"""
        return self.companion.interaction_finish_tool_flow(
            flow_id, response,
        )

    def companion_interaction_trace_tool_flow(
        self, flow_id: str,
    ) -> Dict[str, Any]:
        """回溯工具流程 (V10.1: 可审计)"""
        return self.companion.interaction_trace_tool_flow(flow_id)

    def companion_interaction_set_partner_goal(
        self, goal: str,
    ) -> Dict[str, Any]:
        """设置伙伴协作目标 (V10.1)"""
        return self.companion.interaction_set_partner_goal(goal)

    def companion_interaction_partner_snapshot(
        self,
    ) -> Dict[str, Any]:
        """伙伴交互状态快照 (V10.1)"""
        return self.companion.interaction_partner_snapshot()

    def companion_interaction_mark_latency(
        self, stage: str, latency_ms: float,
    ) -> Dict[str, Any]:
        """记录链路延迟 (V10.1)"""
        return self.companion.interaction_mark_latency(
            stage, latency_ms,
        )

    def companion_interaction_latency_report(
        self,
    ) -> Dict[str, Any]:
        """延迟报告 (V10.1)"""
        return self.companion.interaction_latency_report()

    def companion_interaction_audit(
        self, limit: int = 100,
    ) -> Dict[str, Any]:
        """交互审计报告 (V10.1)"""
        return self.companion.interaction_audit(limit=limit)

    def companion_interaction_stats(self) -> Dict[str, Any]:
        """交互协议统计 (V10.1)"""
        return self.companion.interaction_stats()

    # ── V10.1 记忆稳定化 (Memory Stabilization) ─────────────────
    def companion_memory_stabilize(
        self,
        records: list = None,
        confirmed_ids: list = None,
        referenced_ids: list = None,
    ) -> Dict[str, Any]:
        """记忆稳定化总报告 (V10.1: 压缩+权重+冲突, 不执行淘汰)"""
        return self.companion.memory_stabilize(
            records, confirmed_ids, referenced_ids,
        )

    def companion_memory_prune_candidates(
        self,
        records: list = None,
        confirmed_ids: list = None,
    ) -> Dict[str, Any]:
        """记忆淘汰候选 (V10.1: 只出方案, 不执行)"""
        return self.companion.memory_prune_candidates(
            records, confirmed_ids,
        )

    def companion_memory_prune_execute(
        self,
        record_ids: list,
        records: list = None,
    ) -> Dict[str, Any]:
        """显式执行记忆淘汰 (V10.1: 经经历存储 forget + 审计)"""
        return self.companion.memory_prune_execute(
            record_ids, records,
        )

    def companion_memory_stabilization_stats(self) -> Dict[str, Any]:
        """记忆稳定化统计 (V10.1)"""
        return self.companion.memory_stabilization_stats()

    def companion_memory_stabilization_audit(
        self, limit: int = 100,
    ) -> Dict[str, Any]:
        """记忆稳定化审计报告 (V10.1: 热机可追踪)"""
        return self.companion.memory_stabilization_audit(
            limit=limit,
        )



    # ── Embodied Report (V4.3 状态报告) ───────────────────────────
    def report(self) -> Dict[str, Any]:
        """Embodied Report: 统一状态报告

        输出 (供管理界面 / Agent 长上下文):
            World Model → Memory → Feedback → Prediction → Events → Scene → Experience Policy
        """
        env = None
        try:
            env = self._resolve_environment(None)
        except EmbodiedServiceError:
            pass
        latest = self._manager.world_model.get_latest()
        pred = None
        if latest is not None and self._manager.predictor is not None:
            try:
                pred = self._manager.predictor.predict(None, latest)
            except Exception as e:
                logger.warning(f"[Embodied] Report 预测失败: {e}")
        events_stats = self._manager.event_log.stats()
        scene = None
        if env is not None:
            env_name = self._manager.get_default_name() or env.name
            scene = self._scene_summary_of(env, latest, events_stats, env_name)
        return {
            "report_id": uuid.uuid4().hex,
            "version": "9.5.0",
            "generated_at": _time.time(),
            "world_model": {
                "states": self._manager.world_model.count(),
                "changes": self._manager.world_model.change_count(),
                "objects": self._manager.world_model.object_count(),
                "latest_state": latest.to_dict() if latest else None,
            },
            "memory": {
                "stats": self._manager.memory.stats(),
                "summary": self._manager.memory.summary().to_dict(),
            },
            "feedback": self._manager.feedback.stats(),
            "prediction": {
                "enabled": self._manager.predictor is not None,
                "mode": "rule_based",
                "stability_confidence": round(pred.confidence, 4) if pred else 0.0,
            },
            "events": {
                "stats": events_stats,
                "recent": self._manager.event_log.event_history(limit=8),
            },
            "scene": scene,
            "experience_policy": self._experience.report_dict(),
            "strategy": {
                "audit": self._audit.audit_policy_log(limit=5),
                "trends": self._trends.trend_stats(self._traces.all()),
                "lifecycle": self._experience.table.stats()["status_counts"],
                "mode": "rule_based",
            },
            "governance": {
                "overview": self.governance.strategy_system_overview(),
                "health_score": self.governance.policy_health_check()["health_score"],
                "coverage": self.governance.scene_coverage(),
                "mode": "rule_based",
            },
        }

    def report_text(self) -> str:
        """Embodied Report 文本版 (管理界面展示)"""
        r = self.report()
        wm = r["world_model"]
        fb = r["feedback"]
        ev = r["events"]["stats"]
        sc = r["scene"] or {}
        pol = r["experience_policy"]["stats"]
        audit = r["strategy"]["audit"]
        trends = r["strategy"]["trends"]
        lines = [
            f"[Embodied Report v{r['version']}]",
            f"World Model: states={wm['states']} changes={wm['changes']} objects={wm['objects']}",
            f"Memory: total={r['memory']['stats'].get('total', 0)} "
            f"success_rate={r['memory']['summary'].get('success_rate', 0.0)}",
            f"Feedback: total={fb.get('total', 0)} success_rate={fb.get('success_rate', 0.0)} "
            f"failure_count={fb.get('failure_count', 0)}",
            f"Prediction: enabled={r['prediction']['enabled']} "
            f"stability_confidence={r['prediction']['stability_confidence']}",
            f"Events: total={ev.get('total', 0)} failures={(ev.get('by_result') or {}).get('failure', 0)}",
            f"Scene: environment={sc.get('environment', '-')} scene={sc.get('scene', '-')} "
            f"active_objects={sc.get('active_objects', [])}",
            f"Experience Policy: total={pol.get('total', 0)} "
            f"suggest={pol.get('suggest_count', 0)} accepted={pol.get('accepted_count', 0)} "
            f"hit_rate={pol.get('hit_rate', 0.0)} degraded={pol.get('degraded_count', 0)}",
            f"Strategy Lifecycle: {r['strategy']['lifecycle']}",
            f"Strategy Audit: total={audit.get('total', 0)} "
            f"applied={audit.get('applied_count', 0)} rejected={audit.get('rejected_count', 0)}",
            f"Trend: scene_success={trends.get('by_scene', {})} "
            f"goal_success={trends.get('by_goal_type', {})}",
            f"Governance: health_score={r['governance']['health_score']} "
            f"coverage_rate={r['governance']['coverage'].get('coverage_rate', 0.0)}",
            f"generated_at: {r['generated_at']}",
        ]
        return "\n".join(lines)

    # ── 状态 ──────────────────────────────────────────────────────
    def status(self) -> Dict[str, Any]:
        return {
            "version": "9.5.0",
            "initialized": self._initialized,
            "permission": self._permission.to_dict(),
            "manager": self._manager.status(),
            "feedback_stats": self._manager.feedback.stats(),
            "world_model_states": self._manager.world_model.count(),
            "memory_stats": self._manager.memory.stats(),
            "event_stats": self._manager.event_log.stats(),
            "reasoning": {
                "causal": self._manager.causal_analyzer.stats()["mode"],
                "invariants": self._manager.invariants.stats()["mode"],
                "semantics": self._manager.semantics.stats()["mode"],
                "multi_step_prediction": bool(self._manager.predictor),
            },
            "scene": {
                "environments": self.list_environments(),
                "default": self._manager.get_default_name(),
                "migrations": self._scene_manager.count(),
            },
            "experience": self._experience.stats(),
            "replay": self._traces.stats(),
            "strategy": {
                "audit": self._audit.count(),
                "trends_window": self._trends.window,
                "lifecycle": self._experience.table.stats()["status_counts"],
                "mode": "rule_based",
            },
            "governance": {
                "version": "9.5.0",
                "mode": "rule_based",
                "thresholds": self.governance.thresholds(),
                "health_score": self.governance.policy_health_check()["health_score"],
            },
        }


# ── 全局单例 ─────────────────────────────────────────────────────
_global_service: Optional[EmbodiedService] = None
_service_lock = threading.Lock()


def get_service() -> EmbodiedService:
    """获取全局 EmbodiedService 单例"""
    global _global_service
    with _service_lock:
        if _global_service is None:
            _global_service = EmbodiedService(manager=get_manager())
        return _global_service


def reset_service() -> None:
    """重置全局 Service (测试用)"""
    global _global_service
    with _service_lock:
        _global_service = None
    reset_manager()


__all__ = [
    "EmbodiedService",
    "EmbodiedServiceError",
    "EmbodiedOperationResult",
    "get_service",
    "reset_service",
]
