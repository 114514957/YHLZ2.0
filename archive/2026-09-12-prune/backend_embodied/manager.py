"""
YHLZ Embodied AI V4.2 - 具身 Manager (Environment Reasoning Layer)

职责:
    - Environment 注册 (注册表)
    - WorldModel 管理 (状态保存 / 查询 / 差异分析)
    - Environment Memory 管理 (Embodied 专用记忆 + 经验摘要)
    - Feedback 管理 (存储 / 分析 / 因果处理链路)
    - State Predictor 管理 (状态预测 + 多步条件预测 + 不变式)
    - Event Log 管理 (环境事件时间线)
    - Causal / Invariant / Semantic 管理 (环境推理组件)
    - 生命周期 (start / stop / reset)
    - 全局单例 + 可重置 (测试隔离)

架构位置:
    Service → Manager → Registry → Adapter (Environment)
    Manager 持有: EnvironmentRegistry + WorldModel + EnvironmentMemory
                 + FeedbackStore + FeedbackAnalyzer + StatePredictor
                 + EnvironmentEventLog + CausalAnalyzer + InvariantChecker + SemanticAnalyzer

设计原则:
    - 注册表模式: 多环境共存 (mock / 仿真 / 未来硬件)
    - 默认注册: Mock 必注册 (测试/演示); Hardware 占位注册 (不可用)
    - 数据独立存储 (绝不写入 Agent Memory)
    - WorldModel 禁止直接执行 Action (必须经 Service → Permission → Executor)
    - 推理结果禁止直接执行 (必须经 Permission → Executor)
    - 线程安全 (RLock)
    - 可重置 (测试隔离)
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List, Optional

from backend.embodied.environment.adapter import HardwareEnvironment
from backend.embodied.environment.interface import Environment
from backend.embodied.environment.mock import MockEnvironment
from backend.embodied.environment.registry import EnvironmentRegistry
from backend.embodied.feedback.analyzer import FeedbackAnalyzer
from backend.embodied.feedback.processor import FeedbackStore
from backend.embodied.reasoning.cause import CausalAnalyzer
from backend.embodied.reasoning.event_log import EnvironmentEventLog
from backend.embodied.reasoning.invariants import InvariantChecker
from backend.embodied.reasoning.semantics import SemanticAnalyzer
from backend.embodied.schema import (
    CausalAnalysis,
    EmbodiedAction,
    EnvironmentEvent,
    EnvironmentPrediction,
    EnvironmentState,
    MultiStepPrediction,
)
from backend.embodied.world_model.memory import EnvironmentMemory
from backend.embodied.world_model.predictor import StatePredictor
from backend.embodied.world_model.state import WorldModel

logger = logging.getLogger(__name__)


class EmbodiedManagerError(Exception):
    """Embodied Manager 操作异常"""


class EmbodiedManager:
    """具身管理器

    用法:
        mgr = EmbodiedManager()
        mgr.register_defaults()
        env = mgr.route(action)        # 路由到环境
        wm = mgr.world_model           # 世界模型
        pred = mgr.predict(action)     # 状态预测
        analysis = mgr.process_feedback(feedback, state=state)  # 反馈处理
    """

    def __init__(
        self,
        state_history_max: int = 100,
        feedback_max: int = 200,
        memory_max: int = 100,
        event_log_max: int = 200,
        predictor_enabled: bool = True,
    ):
        self._lock = threading.RLock()
        self._registry = EnvironmentRegistry()
        self._world_model = WorldModel(max_history=state_history_max)
        self._memory = EnvironmentMemory(max_entries=memory_max)
        self._feedback = FeedbackStore(max_entries=feedback_max)
        self._analyzer = FeedbackAnalyzer()
        self._predictor = StatePredictor() if predictor_enabled else None
        self._event_log = EnvironmentEventLog(max_events=event_log_max)
        self._causal_analyzer = CausalAnalyzer()
        self._invariants = InvariantChecker()
        self._semantics = SemanticAnalyzer()
        self._default_registered = False
        self._running = False

    # ── Environment 注册 ──────────────────────────────────────────
    def register_environment(
        self,
        name: str,
        env: Environment,
        override: bool = False,
    ) -> None:
        """注册环境"""
        self._registry.register(name, env, override=override)

    def unregister_environment(self, name: str) -> bool:
        """注销环境, 返回是否成功"""
        return self._registry.unregister(name)

    def get_environment(self, name: str) -> Optional[Environment]:
        """按名获取环境"""
        return self._registry.get(name)

    def get_default_environment(self) -> Optional[Environment]:
        """获取默认环境 (第一个注册的)"""
        return self._registry.get_default()

    def list_environments(self) -> list:
        return self._registry.list()

    def list_names(self) -> list:
        return self._registry.list_names()

    # ── 默认环境切换 (V4.3 场景生命周期) ─────────────────────────
    def set_default_environment(self, name: str) -> bool:
        """设置默认环境 (场景切换后路由目标), 返回是否成功"""
        return self._registry.set_default(name)

    def get_default_name(self) -> Optional[str]:
        """当前默认环境名 (None=未显式设置)"""
        return self._registry.get_default_name()

    # ── 路由 ──────────────────────────────────────────────────────
    def route(self, action: EmbodiedAction) -> Optional[Environment]:
        """路由动作到环境 (优先 parameters['environment'], 否则默认)"""
        return self._registry.route(action)

    # ── 基础设施 (组合) ───────────────────────────────────────────
    @property
    def world_model(self) -> WorldModel:
        """世界模型: 环境状态记忆与差异分析"""
        return self._world_model

    @property
    def memory(self) -> EnvironmentMemory:
        """环境记忆 (Embodied 专用, 独立于 Agent Memory)"""
        return self._memory

    @property
    def feedback(self) -> FeedbackStore:
        """反馈存储"""
        return self._feedback

    @property
    def analyzer(self) -> FeedbackAnalyzer:
        """反馈分析器"""
        return self._analyzer

    @property
    def predictor(self) -> Optional[StatePredictor]:
        """状态预测器 (None=已禁用)"""
        return self._predictor

    @property
    def event_log(self) -> EnvironmentEventLog:
        """环境事件日志 (V4.2 时间线)"""
        return self._event_log

    @property
    def causal_analyzer(self) -> CausalAnalyzer:
        """因果分析器 (V4.2)"""
        return self._causal_analyzer

    @property
    def invariants(self) -> InvariantChecker:
        """状态不变式检测器 (V4.2)"""
        return self._invariants

    @property
    def semantics(self) -> SemanticAnalyzer:
        """语义环境分析器 (V4.2)"""
        return self._semantics

    # ── 状态预测 ──────────────────────────────────────────────────
    def predict(self, action: EmbodiedAction) -> Optional[EnvironmentPrediction]:
        """预测动作对环境的预期影响 (规则驱动)

        返回 None = 预测器已禁用 / 环境尚无状态
        """
        if self._predictor is None:
            return None
        latest = self._world_model.get_latest()
        if latest is None:
            return None
        return self._predictor.predict(action, latest)

    def predict_sequence(
        self,
        actions: List[EmbodiedAction],
        environment: Optional[str] = None,
    ) -> Optional[MultiStepPrediction]:
        """多步骤条件预测 (V4.2): 动作序列 → 逐步预期 + 最终预期

        返回 None = 预测器已禁用 / 环境尚无状态
        """
        if self._predictor is None:
            return None
        latest = self._world_model.get_latest()
        if latest is None:
            if environment:
                env = self.get_environment(environment)
                if env is not None and env.is_available():
                    latest = env.get_state()
            if latest is None:
                return None
        return self._predictor.predict_sequence(actions, latest)

    def verify_prediction(
        self,
        prediction: EnvironmentPrediction,
        actual_change: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """验证预测与实际变化是否一致"""
        if self._predictor is None or prediction is None:
            return None
        return self._predictor.verify(prediction, actual_change)

    def analyze_cause(
        self,
        feedback,
        action: Optional[EmbodiedAction] = None,
        state: Optional[EnvironmentState] = None,
        previous_state: Optional[EnvironmentState] = None,
    ) -> CausalAnalysis:
        """因果分析 (V4.2): 为什么失败 → 补救"""
        return self._causal_analyzer.analyze(
            feedback, action=action, state=state, previous_state=previous_state,
        )

    # ── 事件记录 (V4.2) ───────────────────────────────────────────
    def record_event(self, event: EnvironmentEvent) -> str:
        """记录环境事件到时间线"""
        return self._event_log.record(event)

    # ── 反馈处理 ──────────────────────────────────────────────────
    def process_feedback(
        self,
        feedback,
        action: Optional[EmbodiedAction] = None,
        state: Optional[EnvironmentState] = None,
        record_memory: bool = True,
    ):
        """处理反馈: 存储 → 分析 → 因果 → 记忆 → 事件 → 世界模型对照

        Args:
            feedback:       行动反馈
            action:         对应动作 (可选)
            state:          动作后状态 (可选)
            record_memory:  是否写入环境记忆 (默认 True)
        """
        # 1. 存储
        self._feedback.add(feedback)

        # 2. 分析
        analysis = self._analyzer.analyze(feedback, action=action, state=state)

        # 3. 因果分析 (V4.2): 失败 → 为什么失败
        causal = self._causal_analyzer.analyze(
            feedback, action=action, state=state,
            previous_state=self._world_model.get_latest(),
        )
        if causal.cause:
            analysis.cause = causal.cause
            analysis.cause_detail = causal.mechanism
            if analysis.failure_reason is None:
                analysis.failure_reason = causal.mechanism
        else:
            analysis.cause = None
            analysis.cause_detail = None

        # 4. 记忆 (Embodied 专用)
        if record_memory:
            self._memory.record_action(
                feedback=feedback.to_dict(),
                analysis=analysis.to_dict(),
                metadata={"action_type": action.action_type if action else ""},
            )
            if feedback.environment_change:
                self._memory.record_change(
                    change=feedback.environment_change,
                    state_id=feedback.new_state.state_id if feedback.new_state else "",
                )

        # 5. 事件时间线 (V4.2)
        self._record_feedback_event(feedback, action, causal)

        # 6. 世界模型对照
        latest = self._world_model.get_latest()
        if latest is not None and state is not None:
            try:
                diff = self._world_model.diff_states(latest, state)
                analysis.environment_change.setdefault("state_diff", diff)
            except Exception as e:
                logger.warning(f"[Embodied] 状态对照失败: {e}")

        logger.info(
            f"[Embodied] 反馈处理完成 action_id={feedback.action_id} "
            f"result={feedback.result} success={analysis.success} "
            f"cause={analysis.cause or 'none'}"
        )
        return analysis

    def _record_feedback_event(self, feedback, action, causal) -> None:
        """将反馈写入事件时间线 (含对象变化 / 主体位置 / 因果)"""
        change = feedback.environment_change or {}
        position_from = None
        position_to = None
        if change.get("from") and isinstance(change.get("from"), list):
            position_from = change["from"]
        if change.get("to") and isinstance(change.get("to"), list):
            position_to = change["to"]
        object_changes: List[Dict[str, Any]] = []
        if change.get("object"):
            object_changes.append({
                "name": change.get("object"),
                "result": feedback.result,
            })
        try:
            self._event_log.record_action(
                action=action,
                result=feedback.result,
                change=change,
                cause=causal.cause if causal and causal.cause else None,
                object_changes=object_changes,
                position_from=position_from,
                position_to=position_to,
            )
        except Exception as e:
            logger.warning(f"[Embodied] 事件记录失败: {e}")

    # ── 生命周期 ──────────────────────────────────────────────────
    def start(self) -> None:
        """启动 Manager"""
        with self._lock:
            self._running = True
        logger.info("[Embodied] EmbodiedManager 已启动")

    def stop(self) -> None:
        """停止 Manager (关闭所有环境)"""
        with self._lock:
            envs = list(self._registry.list_names())
            for name in envs:
                env = self._registry.get(name)
                if env is not None:
                    try:
                        env.close()
                    except Exception as e:
                        logger.warning(f"[Embodied] 关闭环境 {name} 异常: {e}")
            self._registry.reset()
            self._default_registered = False
            self._running = False
        logger.info("[Embodied] EmbodiedManager 已停止")

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._running

    # ── 默认注册 ──────────────────────────────────────────────────
    def register_defaults(self) -> None:
        """注册默认环境

        行为:
            - Mock 环境必注册 (测试/演示/具身闭环验证)
            - Hardware 适配器注册为占位 (is_available=False, 本版本不控制真实设备)
        """
        with self._lock:
            if self._default_registered:
                return
            self._registry.register("mock", MockEnvironment(scene="room"), override=True)
            self._registry.register("hardware", HardwareEnvironment(), override=True)
            self._default_registered = True
            logger.info("[Embodied] 默认环境已注册: mock (房间场景) / hardware (占位不可用)")

    # ── 状态 ──────────────────────────────────────────────────────
    def status(self) -> Dict[str, Any]:
        """Manager 整体状态 + 指标"""
        with self._lock:
            default = self.get_default_environment()
            latest = self._world_model.get_latest()
            return {
                "environments_count": self._registry.count(),
                "environments": self._registry.list(),
                "default_environment": default.name if default else None,
                "default_registered": self._default_registered,
                "running": self._running,
                "world_model": {
                    "states": self._world_model.count(),
                    "changes": self._world_model.change_count(),
                    "objects": self._world_model.object_count(),
                },
                "memory": self._memory.stats(),
                "feedback": self._feedback.stats(),
                "event_log": self._event_log.stats(),
                "predictor": {
                    "enabled": self._predictor is not None,
                },
                "reasoning": {
                    "causal_analyzer": self._causal_analyzer.stats(),
                    "invariants": self._invariants.stats()["rules_count"],
                    "semantics": self._semantics.stats(),
                },
            }

    def reset(self) -> None:
        """清空注册 + 全部状态 (不关闭环境, 供测试复用)"""
        with self._lock:
            self._registry.reset()
            self._world_model.reset()
            self._memory.clear()
            self._feedback.clear()
            self._analyzer.reset()
            self._event_log.clear()
            self._causal_analyzer.reset()
            self._invariants.reset()
            self._semantics.reset()
            self._default_registered = False
            self._running = False
        logger.info("[Embodied] EmbodiedManager 已重置")


# ── 全局单例 ─────────────────────────────────────────────────────
_global_manager: Optional[EmbodiedManager] = None
_manager_lock = threading.Lock()


def get_manager() -> EmbodiedManager:
    """获取全局 EmbodiedManager 单例"""
    global _global_manager
    with _manager_lock:
        if _global_manager is None:
            _global_manager = EmbodiedManager()
            _global_manager.register_defaults()
        return _global_manager


def reset_manager() -> None:
    """重置全局 Manager (测试用)"""
    global _global_manager
    with _manager_lock:
        if _global_manager is not None:
            _global_manager.reset()
        _global_manager = None


__all__ = [
    "EmbodiedManager",
    "EmbodiedManagerError",
    "get_manager",
    "reset_manager",
]
