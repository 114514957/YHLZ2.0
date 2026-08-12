"""
YHLZ Embodied AI V4.2 - 具身智能数据结构 (Environment Reasoning Layer)

职责:
    - 定义环境状态 (EnvironmentState / EnvironmentObject)
    - 定义环境关系 (relations) 与状态置信度
    - 定义具身动作 (EmbodiedAction)
    - 定义反馈 (Feedback / FeedbackAnalysis, 含因果 cause)
    - 定义历史 (WorldStateHistory) / 预测 (EnvironmentPrediction) / 目标 (EmbodiedGoal)
    - 定义事件时间线 (EnvironmentEvent) / 因果分析 (CausalAnalysis)
    - 定义多步条件预测 (MultiStepPrediction) / 经验摘要 (ExperienceSummary)
    - 枚举: EmbodiedActionType / EmbodiedStatus / FeedbackResult / EventType
    - 不依赖任何外部库 (仅 stdlib + typing)
    - 不依赖 Agent / Voice / Vision / Action (自包含, 便于独立测试)

设计原则:
    - 不可变 (dataclass + 明确字段)
    - 类型注解完整
    - 兼容 JSON 序列化 (to_dict / from_dict)
    - 与真实设备解耦: 全部为抽象环境表示
    - 反馈/记忆独立存储 (绝不写入 Agent Memory)
    - 先理解后行动: 动作必须携带 intent / reason / confidence
    - 因果优先: 失败必须携带 cause (位置不匹配 / 边界限制 / 对象缺失等)
    - 只预测不执行: 预测结果必须经 Permission → Executor 才能落地
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


# ----------------------------------------------------------------------
# 枚举
# ----------------------------------------------------------------------

class EmbodiedActionType(str, Enum):
    """具身动作类型 (抽象环境动作, 非设备操作)"""
    MOVE = "move"                # 移动 (机器人 / 虚拟角色)
    PICK = "pick"                # 拾取对象
    PLACE = "place"              # 放置对象
    SCAN = "scan"                # 扫描环境
    INSPECT = "inspect"          # 检查对象
    EXPLORE = "explore"          # 探索环境
    INTERACT = "interact"        # 交互对象
    WAIT = "wait"                # 等待 / 空操作
    CUSTOM = "custom"            # 自定义

    @classmethod
    def values(cls) -> List[str]:
        return [t.value for t in cls]


class EmbodiedStatus(str, Enum):
    """具身动作状态"""
    PENDING = "pending"                  # 已创建, 待执行
    RUNNING = "running"                  # 执行中
    OK = "ok"                            # 成功
    DENIED = "denied"                    # 权限拒绝
    INVALID = "invalid"                  # 请求不合法
    AWAITING_CONFIRM = "awaiting_confirm"  # 高风险待确认
    CANCELLED = "cancelled"              # 已取消
    ERROR = "error"                      # 执行错误
    UNSUPPORTED = "unsupported"          # 环境不支持
    TIMEOUT = "timeout"                  # 超时


class FeedbackResult(str, Enum):
    """行动反馈结果"""
    SUCCESS = "success"            # 成功
    FAILURE = "failure"            # 失败
    PARTIAL = "partial"            # 部分成功
    NO_CHANGE = "no_change"        # 无状态变化

    @classmethod
    def values(cls) -> List[str]:
        return [r.value for r in cls]


class EventType(str, Enum):
    """环境事件类型 (V4.2 事件时间线)

    时间线回答: 过去发生了什么 → 为什么发生 → 造成什么结果
    """
    ACTION = "action"              # 动作执行 (含结果)
    OBJECT_CHANGE = "object_change"  # 对象状态/位置变化
    MOVE = "move"                  # 主体位置变化
    RESET = "reset"                # 环境重置
    OBSERVE = "observe"            # 观察快照
    FAILURE = "failure"            # 失败 (含因果分析)
    SYSTEM = "system"              # 系统事件 (启用/停用等)

    @classmethod
    def values(cls) -> List[str]:
        return [t.value for t in cls]


class CauseType(str, Enum):
    """失败因果类型 (V4.2 因果分析)

    因果分析回答: 为什么失败 → 补救措施
    """
    POSITION_MISMATCH = "position_mismatch"   # 位置不匹配 (拾取对象不在当前位置)
    BOUNDARY_LIMIT = "boundary_limit"         # 边界限制 (移动越界)
    OBJECT_MISSING = "object_missing"         # 对象缺失 (目标对象不存在)
    OBJECT_NOT_HELD = "object_not_held"       # 对象未持有 (放置前未拾取)
    INVALID_PARAMETER = "invalid_parameter"   # 参数不合法 (dx/dy 非数值等)
    UNSUPPORTED_ACTION = "unsupported_action" # 动作类型不支持
    ENV_UNAVAILABLE = "env_unavailable"       # 环境不可用
    PERMISSION_DENIED = "permission_denied"   # 权限拒绝
    INVARIANT_VIOLATION = "invariant_violation"  # 状态不变式违反
    UNKNOWN = "unknown"                       # 未识别原因

    @classmethod
    def values(cls) -> List[str]:
        return [c.value for c in cls]


# ----------------------------------------------------------------------
# 环境对象 / 状态
# ----------------------------------------------------------------------

@dataclass
class EnvironmentObject:
    """环境中的对象

    Attributes:
        object_id:  对象唯一 ID
        name:       对象名 (如 'lamp' / 'door')
        category:   对象类别 (如 'light' / 'container')
        position:   位置 (如 {'x': 1, 'y': 2})
        properties: 属性 (如 {'color': 'red', 'weight': 1.5})
        state:      对象状态 (如 'on' / 'off' / 'open' / 'closed' / 'held')
        timestamp:  最后更新时间
    """
    object_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    name: str = ""
    category: str = ""
    position: Dict[str, float] = field(default_factory=dict)
    properties: Dict[str, Any] = field(default_factory=dict)
    state: str = ""
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "object_id": self.object_id,
            "name": self.name,
            "category": self.category,
            "position": self.position,
            "properties": self.properties,
            "state": self.state,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "EnvironmentObject":
        return cls(
            object_id=d.get("object_id", uuid.uuid4().hex),
            name=d.get("name", ""),
            category=d.get("category", ""),
            position=dict(d.get("position", {}) or {}),
            properties=dict(d.get("properties", {}) or {}),
            state=d.get("state", ""),
            timestamp=float(d.get("timestamp", time.time())),
        )

    @classmethod
    def create(
        cls,
        name: str = "",
        category: str = "",
        position: Optional[Dict[str, float]] = None,
        properties: Optional[Dict[str, Any]] = None,
        state: str = "",
    ) -> "EnvironmentObject":
        """构造环境对象"""
        return cls(
            name=name, category=category,
            position=position or {}, properties=properties or {}, state=state,
        )


@dataclass
class EnvironmentState:
    """环境状态快照

    Attributes:
        state_id:   状态快照唯一 ID
        objects:    环境中的对象列表
        location:   主体位置 (如 {'x': 0, 'y': 0})
        conditions: 环境条件 (如 {'temperature': 24.0, 'lighting': 'bright'})
        relations:  对象间关系 (如 [{'type': 'near', 'object_a': 'lamp', 'object_b': 'desk'}])
        history:    最近事件记录 (List[Dict])
        timestamp:  快照时间
        confidence: 状态置信度 (0.0 ~ 1.0, 预测/降级状态下降低)
        metadata:   附加元数据
    """
    state_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    objects: List[EnvironmentObject] = field(default_factory=list)
    location: Dict[str, float] = field(default_factory=dict)
    conditions: Dict[str, Any] = field(default_factory=dict)
    relations: List[Dict[str, Any]] = field(default_factory=list)
    history: List[Dict[str, Any]] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)
    confidence: float = 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    # ── 兼容别名: position ⇄ location ────────────────────────────
    @property
    def position(self) -> Dict[str, float]:
        """兼容别名 (旧版字段名 position)"""
        return self.location

    @position.setter
    def position(self, value: Dict[str, float]) -> None:
        self.location = value

    def to_dict(self) -> Dict[str, Any]:
        return {
            "state_id": self.state_id,
            "objects": [o.to_dict() for o in self.objects],
            "location": self.location,
            "conditions": self.conditions,
            "relations": self.relations,
            "history": self.history,
            "timestamp": self.timestamp,
            "confidence": round(self.confidence, 4),
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "EnvironmentState":
        location = dict(d.get("location", {}) or {})
        if not location:
            location = dict(d.get("position", {}) or {})  # 兼容旧字段
        return cls(
            state_id=d.get("state_id", uuid.uuid4().hex),
            objects=[EnvironmentObject.from_dict(o) for o in (d.get("objects") or [])],
            location=location,
            conditions=dict(d.get("conditions", {}) or {}),
            relations=list(d.get("relations", []) or []),
            history=list(d.get("history", []) or []),
            timestamp=float(d.get("timestamp", time.time())),
            confidence=float(d.get("confidence", 1.0)),
            metadata=dict(d.get("metadata", {}) or {}),
        )

    @classmethod
    def create(
        cls,
        objects: Optional[List[EnvironmentObject]] = None,
        location: Optional[Dict[str, float]] = None,
        position: Optional[Dict[str, float]] = None,
        conditions: Optional[Dict[str, Any]] = None,
        relations: Optional[List[Dict[str, Any]]] = None,
        history: Optional[List[Dict[str, Any]]] = None,
        confidence: float = 1.0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "EnvironmentState":
        """构造环境状态快照"""
        if location is None:
            location = position or {}  # 兼容旧字段名
        return cls(
            objects=objects or [], location=location,
            conditions=conditions or {}, relations=relations or [],
            history=history or [], confidence=confidence, metadata=metadata or {},
        )


# ----------------------------------------------------------------------
# 具身动作
# ----------------------------------------------------------------------

@dataclass
class EmbodiedAction:
    """具身动作

    Attributes:
        action_id:   动作唯一 ID
        action_type: 动作类型 (EmbodiedActionType)
        intent:      意图描述 (如 '拿起桌子上的杯子')
        target:      动作目标 (对象名 / 位置 / 区域)
        parameters:  参数 (如 {'dx': 1, 'dy': 0} / {'object': 'cup'})
        risk_level:  声明的风险等级 (实际由 Permission 规则评估)
        confidence:  置信度 (0.0 ~ 1.0)
        reason:      动作理由 (用于审计 / 解释)
        status:      动作状态 (EmbodiedStatus)
        created_at:  创建时间
    """
    action_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    action_type: str = EmbodiedActionType.CUSTOM.value
    intent: str = ""
    target: str = ""
    parameters: Dict[str, Any] = field(default_factory=dict)
    risk_level: str = "low"
    confidence: float = 0.0
    reason: str = ""
    status: str = EmbodiedStatus.PENDING.value
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action_id": self.action_id,
            "action_type": self.action_type,
            "intent": self.intent,
            "target": self.target,
            "parameters": self.parameters,
            "risk_level": self.risk_level,
            "confidence": round(self.confidence, 4),
            "reason": self.reason,
            "status": self.status,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "EmbodiedAction":
        return cls(
            action_id=d.get("action_id", uuid.uuid4().hex),
            action_type=d.get("action_type", EmbodiedActionType.CUSTOM.value),
            intent=d.get("intent", ""),
            target=d.get("target", ""),
            parameters=dict(d.get("parameters", {}) or {}),
            risk_level=d.get("risk_level", "low"),
            confidence=float(d.get("confidence", 0.0)),
            reason=d.get("reason", ""),
            status=d.get("status", EmbodiedStatus.PENDING.value),
            created_at=float(d.get("created_at", time.time())),
        )

    @classmethod
    def create(
        cls,
        action_type: str = EmbodiedActionType.CUSTOM.value,
        intent: str = "",
        target: str = "",
        parameters: Optional[Dict[str, Any]] = None,
        risk_level: str = "low",
        confidence: float = 0.0,
        reason: str = "",
    ) -> "EmbodiedAction":
        """构造具身动作"""
        return cls(
            action_type=action_type, intent=intent, target=target,
            parameters=parameters or {}, risk_level=risk_level,
            confidence=confidence, reason=reason,
        )


# ----------------------------------------------------------------------
# 反馈
# ----------------------------------------------------------------------

@dataclass
class Feedback:
    """行动反馈

    Attributes:
        feedback_id:         反馈唯一 ID
        action_id:           关联动作 ID
        result:              反馈结果 (FeedbackResult)
        environment_change:  环境变化描述 (如 {'event': 'move', 'to': [1, 1]})
        new_state:           动作后的新状态 (可选)
        error:               错误信息 (None=无错误)
        latency_ms:          耗时 (毫秒)
        timestamp:           反馈时间
    """
    feedback_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    action_id: str = ""
    result: str = FeedbackResult.SUCCESS.value
    environment_change: Dict[str, Any] = field(default_factory=dict)
    new_state: Optional["EnvironmentState"] = None
    error: Optional[str] = None
    latency_ms: float = 0.0
    timestamp: float = field(default_factory=time.time)

    @property
    def success(self) -> bool:
        """是否成功 (SUCCESS 视为成功)"""
        return self.result == FeedbackResult.SUCCESS.value

    def to_dict(self) -> Dict[str, Any]:
        return {
            "feedback_id": self.feedback_id,
            "action_id": self.action_id,
            "result": self.result,
            "environment_change": self.environment_change,
            "new_state": self.new_state.to_dict() if self.new_state else None,
            "error": self.error,
            "latency_ms": round(self.latency_ms, 2),
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Feedback":
        new_state = d.get("new_state")
        return cls(
            feedback_id=d.get("feedback_id", uuid.uuid4().hex),
            action_id=d.get("action_id", ""),
            result=d.get("result", FeedbackResult.SUCCESS.value),
            environment_change=dict(d.get("environment_change", {}) or {}),
            new_state=EnvironmentState.from_dict(new_state) if isinstance(new_state, dict) else None,
            error=d.get("error"),
            latency_ms=float(d.get("latency_ms", 0.0)),
            timestamp=float(d.get("timestamp", time.time())),
        )

    @classmethod
    def create(
        cls,
        action_id: str = "",
        result: str = FeedbackResult.SUCCESS.value,
        environment_change: Optional[Dict[str, Any]] = None,
        new_state: Optional["EnvironmentState"] = None,
        error: Optional[str] = None,
        latency_ms: float = 0.0,
    ) -> "Feedback":
        """构造反馈"""
        return cls(
            action_id=action_id, result=result,
            environment_change=environment_change or {},
            new_state=new_state, error=error, latency_ms=latency_ms,
        )


@dataclass
class FeedbackAnalysis:
    """反馈分析结果

    Attributes:
        analysis_id:       分析唯一 ID
        action_id:         关联动作 ID
        success:           是否成功 (业务判断)
        failure_reason:    失败原因 (成功时为 None)
        suggestion:        下一步建议 (供自适应规划使用)
        cause:             失败因果类型 (V4.2, CauseType 值, 成功/未知为 None)
        cause_detail:      因果细节描述 (V4.2, 如 '对象不在当前位置')
        environment_change: 环境变化摘要
        timestamp:         分析时间
    """
    analysis_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    action_id: str = ""
    success: bool = True
    failure_reason: Optional[str] = None
    suggestion: str = ""
    cause: Optional[str] = None
    cause_detail: Optional[str] = None
    environment_change: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "analysis_id": self.analysis_id,
            "action_id": self.action_id,
            "success": self.success,
            "failure_reason": self.failure_reason,
            "suggestion": self.suggestion,
            "cause": self.cause,
            "cause_detail": self.cause_detail,
            "environment_change": self.environment_change,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "FeedbackAnalysis":
        return cls(
            analysis_id=d.get("analysis_id", uuid.uuid4().hex),
            action_id=d.get("action_id", ""),
            success=bool(d.get("success", True)),
            failure_reason=d.get("failure_reason"),
            suggestion=d.get("suggestion", ""),
            cause=d.get("cause"),
            cause_detail=d.get("cause_detail"),
            environment_change=dict(d.get("environment_change", {}) or {}),
            timestamp=float(d.get("timestamp", time.time())),
        )

    @classmethod
    def create(
        cls,
        action_id: str = "",
        success: bool = True,
        failure_reason: Optional[str] = None,
        suggestion: str = "",
        cause: Optional[str] = None,
        cause_detail: Optional[str] = None,
        environment_change: Optional[Dict[str, Any]] = None,
    ) -> "FeedbackAnalysis":
        """构造反馈分析"""
        return cls(
            action_id=action_id, success=success, failure_reason=failure_reason,
            suggestion=suggestion, cause=cause, cause_detail=cause_detail,
            environment_change=environment_change or {},
        )


# ----------------------------------------------------------------------
# 历史 / 预测
# ----------------------------------------------------------------------

@dataclass
class WorldStateHistory:
    """环境状态历史 (两次状态快照之间的变化)

    Attributes:
        history_id:     历史唯一 ID
        previous_state: 先前状态
        current_state:  当前状态
        change:         状态变化摘要 (added / removed / modified / location / conditions)
        timestamp:      记录时间
    """
    history_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    previous_state: Optional["EnvironmentState"] = None
    current_state: Optional["EnvironmentState"] = None
    change: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "history_id": self.history_id,
            "previous_state": self.previous_state.to_dict() if self.previous_state else None,
            "current_state": self.current_state.to_dict() if self.current_state else None,
            "change": self.change,
            "timestamp": self.timestamp,
        }

    @classmethod
    def create(
        cls,
        previous_state: Optional["EnvironmentState"] = None,
        current_state: Optional["EnvironmentState"] = None,
        change: Optional[Dict[str, Any]] = None,
    ) -> "WorldStateHistory":
        """构造状态历史"""
        return cls(
            previous_state=previous_state, current_state=current_state,
            change=change or {},
        )


@dataclass
class EnvironmentPrediction:
    """环境状态预测 (规则驱动, 非 AI 训练)

    Attributes:
        prediction_id:   预测唯一 ID
        current_state:   预测时的当前状态
        expected_change: 预期变化 (如 {'event': 'move', 'to': [1, 0]})
        confidence:      预测置信度 (0.0 ~ 1.0)
        timestamp:       预测时间
    """
    prediction_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    current_state: Optional["EnvironmentState"] = None
    expected_change: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "prediction_id": self.prediction_id,
            "current_state": self.current_state.to_dict() if self.current_state else None,
            "expected_change": self.expected_change,
            "confidence": round(self.confidence, 4),
            "timestamp": self.timestamp,
        }

    @classmethod
    def create(
        cls,
        current_state: Optional["EnvironmentState"] = None,
        expected_change: Optional[Dict[str, Any]] = None,
        confidence: float = 0.0,
    ) -> "EnvironmentPrediction":
        """构造环境预测"""
        return cls(
            current_state=current_state, expected_change=expected_change or {},
            confidence=confidence,
        )


@dataclass
class EnvironmentEvent:
    """环境事件 (V4.2 事件时间线条目)

    时间线记录: 动作 / 结果 / 对象变化 / 主体位置, 回答"过去发生了什么 / 为什么 / 结果如何"。

    Attributes:
        event_id:      事件唯一 ID
        event_type:    事件类型 (EventType)
        action_id:     关联动作 ID (非动作事件为空)
        action_type:   动作类型 (EmbodiedActionType 值, 非动作事件为空)
        target:        动作目标 (对象名 / 位置)
        result:        行动结果 (FeedbackResult 值, 非动作事件为空)
        cause:         失败因果 (CauseType 值, V4.2, 失败事件携带)
        object_changes: 对象变化摘要 (List[Dict])
        position_from: 主体位置变化前 (None=未变)
        position_to:   主体位置变化后 (None=未变)
        summary:       事件摘要 (一句话, 供 LLM 上下文)
        timestamp:     事件时间
        metadata:      附加元数据
    """
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    event_type: str = EventType.ACTION.value
    action_id: str = ""
    action_type: str = ""
    target: str = ""
    result: str = ""
    cause: Optional[str] = None
    object_changes: List[Dict[str, Any]] = field(default_factory=list)
    position_from: Optional[List[float]] = None
    position_to: Optional[List[float]] = None
    summary: str = ""
    timestamp: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "action_id": self.action_id,
            "action_type": self.action_type,
            "target": self.target,
            "result": self.result,
            "cause": self.cause,
            "object_changes": self.object_changes,
            "position_from": self.position_from,
            "position_to": self.position_to,
            "summary": self.summary,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "EnvironmentEvent":
        return cls(
            event_id=d.get("event_id", uuid.uuid4().hex),
            event_type=d.get("event_type", EventType.ACTION.value),
            action_id=d.get("action_id", ""),
            action_type=d.get("action_type", ""),
            target=d.get("target", ""),
            result=d.get("result", ""),
            cause=d.get("cause"),
            object_changes=list(d.get("object_changes", []) or []),
            position_from=d.get("position_from"),
            position_to=d.get("position_to"),
            summary=d.get("summary", ""),
            timestamp=float(d.get("timestamp", time.time())),
            metadata=dict(d.get("metadata", {}) or {}),
        )

    @classmethod
    def create(
        cls,
        event_type: str = EventType.ACTION.value,
        action_id: str = "",
        action_type: str = "",
        target: str = "",
        result: str = "",
        cause: Optional[str] = None,
        object_changes: Optional[List[Dict[str, Any]]] = None,
        position_from: Optional[List[float]] = None,
        position_to: Optional[List[float]] = None,
        summary: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "EnvironmentEvent":
        """构造环境事件"""
        return cls(
            event_type=event_type, action_id=action_id, action_type=action_type,
            target=target, result=result, cause=cause,
            object_changes=object_changes or [],
            position_from=position_from, position_to=position_to,
            summary=summary, metadata=metadata or {},
        )


@dataclass
class CausalAnalysis:
    """因果分析 (V4.2, 失败原因解析)

    回答: 为什么失败 → 补救措施。规则驱动, 禁止 AI 猜测。

    Attributes:
        causal_id:   因果分析唯一 ID
        action_id:   关联动作 ID
        cause:       因果类型 (CauseType)
        mechanism:   机制描述 (如 '目标位置超出环境网格边界')
        remedy:      补救措施 (如 '尝试反方向移动或缩短步长')
        confidence:  置信度 (0.0 ~ 1.0)
        evidence:    证据 (环境变化 / 错误信息 / 状态差异)
        timestamp:   分析时间
    """
    causal_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    action_id: str = ""
    cause: str = CauseType.UNKNOWN.value
    mechanism: str = ""
    remedy: str = ""
    confidence: float = 0.0
    evidence: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "causal_id": self.causal_id,
            "action_id": self.action_id,
            "cause": self.cause,
            "mechanism": self.mechanism,
            "remedy": self.remedy,
            "confidence": round(self.confidence, 4),
            "evidence": self.evidence,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "CausalAnalysis":
        return cls(
            causal_id=d.get("causal_id", uuid.uuid4().hex),
            action_id=d.get("action_id", ""),
            cause=d.get("cause", CauseType.UNKNOWN.value),
            mechanism=d.get("mechanism", ""),
            remedy=d.get("remedy", ""),
            confidence=float(d.get("confidence", 0.0)),
            evidence=dict(d.get("evidence", {}) or {}),
            timestamp=float(d.get("timestamp", time.time())),
        )

    @classmethod
    def create(
        cls,
        action_id: str = "",
        cause: str = CauseType.UNKNOWN.value,
        mechanism: str = "",
        remedy: str = "",
        confidence: float = 0.0,
        evidence: Optional[Dict[str, Any]] = None,
    ) -> "CausalAnalysis":
        """构造因果分析"""
        return cls(
            action_id=action_id, cause=cause, mechanism=mechanism,
            remedy=remedy, confidence=confidence, evidence=evidence or {},
        )


@dataclass
class MultiStepPrediction:
    """多步条件预测 (V4.2, State Predictor 升级)

    输入: 动作序列 [MOVE, PICK] + 当前状态
    输出: 逐步预期 + 最终预期 (如 object = held)

    设计: 规则驱动状态推演, 禁止黑盒 AI 预测; 同时检测状态不变式。

    Attributes:
        prediction_id:   预测唯一 ID
        actions:         动作序列 (List[Dict])
        steps:           每步预测 (List[Dict]: action / expected / confidence)
        final_expected:  最终预期状态摘要 (如 {'lamp': 'held'})
        invariants_ok:   是否全部通过不变式检测
        invariant_violations: 不变式违反列表
        confidence:      总体置信度 (0.0 ~ 1.0)
        timestamp:       预测时间
    """
    prediction_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    actions: List[Dict[str, Any]] = field(default_factory=list)
    steps: List[Dict[str, Any]] = field(default_factory=list)
    final_expected: Dict[str, Any] = field(default_factory=dict)
    invariants_ok: bool = True
    invariant_violations: List[Dict[str, Any]] = field(default_factory=list)
    confidence: float = 0.0
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "prediction_id": self.prediction_id,
            "actions": self.actions,
            "steps": self.steps,
            "final_expected": self.final_expected,
            "invariants_ok": self.invariants_ok,
            "invariant_violations": self.invariant_violations,
            "confidence": round(self.confidence, 4),
            "timestamp": self.timestamp,
        }

    @classmethod
    def create(
        cls,
        actions: Optional[List[Dict[str, Any]]] = None,
        steps: Optional[List[Dict[str, Any]]] = None,
        final_expected: Optional[Dict[str, Any]] = None,
        invariants_ok: bool = True,
        invariant_violations: Optional[List[Dict[str, Any]]] = None,
        confidence: float = 0.0,
    ) -> "MultiStepPrediction":
        """构造多步预测"""
        return cls(
            actions=actions or [], steps=steps or [],
            final_expected=final_expected or {},
            invariants_ok=invariants_ok,
            invariant_violations=invariant_violations or [],
            confidence=confidence,
        )

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "MultiStepPrediction":
        return cls(
            prediction_id=d.get("prediction_id", uuid.uuid4().hex),
            actions=list(d.get("actions", []) or []),
            steps=list(d.get("steps", []) or []),
            final_expected=dict(d.get("final_expected", {}) or {}),
            invariants_ok=bool(d.get("invariants_ok", True)),
            invariant_violations=list(d.get("invariant_violations", []) or []),
            confidence=float(d.get("confidence", 0.0)),
            timestamp=float(d.get("timestamp", time.time())),
        )


@dataclass
class ExperienceSummary:
    """具身经验摘要 (V4.2, Embodied Long-term Memory)

    汇总: 高频失败模式 / 成功率趋势 / 因果统计。

    Attributes:
        summary_id:      摘要唯一 ID
        total_actions:   行动总数
        success_count:   成功次数
        success_rate:    成功率 (0.0 ~ 1.0)
        failure_patterns: 高频失败模式 (List[Dict]: cause / count / example)
        success_trends:  成功率趋势 (按时间桶: List[Dict]: bucket / success_rate)
        cause_stats:     因果统计 (cause → 次数)
        top_failures:    失败事件示例 (List[Dict], 最多 N 条)
        generated_at:    生成时间
    """
    summary_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    total_actions: int = 0
    success_count: int = 0
    success_rate: float = 0.0
    failure_patterns: List[Dict[str, Any]] = field(default_factory=list)
    success_trends: List[Dict[str, Any]] = field(default_factory=list)
    cause_stats: Dict[str, int] = field(default_factory=dict)
    top_failures: List[Dict[str, Any]] = field(default_factory=list)
    generated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "summary_id": self.summary_id,
            "total_actions": self.total_actions,
            "success_count": self.success_count,
            "success_rate": round(self.success_rate, 4),
            "failure_patterns": self.failure_patterns,
            "success_trends": self.success_trends,
            "cause_stats": self.cause_stats,
            "top_failures": self.top_failures,
            "generated_at": self.generated_at,
        }

    @classmethod
    def create(
        cls,
        total_actions: int = 0,
        success_count: int = 0,
        success_rate: float = 0.0,
        failure_patterns: Optional[List[Dict[str, Any]]] = None,
        success_trends: Optional[List[Dict[str, Any]]] = None,
        cause_stats: Optional[Dict[str, int]] = None,
        top_failures: Optional[List[Dict[str, Any]]] = None,
    ) -> "ExperienceSummary":
        """构造经验摘要"""
        return cls(
            total_actions=total_actions, success_count=success_count,
            success_rate=success_rate, failure_patterns=failure_patterns or [],
            success_trends=success_trends or [], cause_stats=cause_stats or {},
            top_failures=top_failures or [],
        )

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ExperienceSummary":
        return cls(
            summary_id=d.get("summary_id", uuid.uuid4().hex),
            total_actions=int(d.get("total_actions", 0)),
            success_count=int(d.get("success_count", 0)),
            success_rate=float(d.get("success_rate", 0.0)),
            failure_patterns=list(d.get("failure_patterns", []) or []),
            success_trends=list(d.get("success_trends", []) or []),
            cause_stats=dict(d.get("cause_stats", {}) or {}),
            top_failures=list(d.get("top_failures", []) or []),
            generated_at=float(d.get("generated_at", time.time())),
        )


# ----------------------------------------------------------------------
# 目标 (Agent → Embodied 输入)
# ----------------------------------------------------------------------

@dataclass
class EmbodiedGoal:
    """具身目标 (Agent 提交给 Embodied Service 的任务)

    Attributes:
        goal_id:     目标唯一 ID
        description: 目标描述 (如 '检查房间里的台灯')
        intent:      目标意图 (可选, 未提供时由 Service 解析描述)
        target:      目标对象 / 位置 (可选)
        scene:       目标所在场景 (V4.4 策略调度维度, 空=未知)
        constraints: 约束 (如 {'max_steps': 5, 'allowed_actions': [...]})
        priority:    优先级 (low / medium / high)
        created_at:  创建时间
    """
    goal_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    description: str = ""
    intent: str = ""
    target: str = ""
    scene: str = ""  # V4.4: 目标所在场景 (room / warehouse / custom, 空=未知)
    constraints: Dict[str, Any] = field(default_factory=dict)
    priority: str = "medium"
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "goal_id": self.goal_id,
            "description": self.description,
            "intent": self.intent,
            "target": self.target,
            "scene": self.scene,
            "constraints": self.constraints,
            "priority": self.priority,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "EmbodiedGoal":
        return cls(
            goal_id=d.get("goal_id", uuid.uuid4().hex),
            description=d.get("description", ""),
            intent=d.get("intent", ""),
            target=d.get("target", ""),
            scene=d.get("scene", ""),
            constraints=dict(d.get("constraints", {}) or {}),
            priority=d.get("priority", "medium"),
            created_at=float(d.get("created_at", time.time())),
        )

    @classmethod
    def create(
        cls,
        description: str = "",
        intent: str = "",
        target: str = "",
        scene: str = "",
        constraints: Optional[Dict[str, Any]] = None,
        priority: str = "medium",
    ) -> "EmbodiedGoal":
        """构造具身目标"""
        return cls(
            description=description, intent=intent, target=target,
            scene=scene, constraints=constraints or {}, priority=priority,
        )


__all__ = [
    "EmbodiedActionType",
    "EmbodiedStatus",
    "FeedbackResult",
    "EventType",
    "CauseType",
    "EnvironmentObject",
    "EnvironmentState",
    "EmbodiedAction",
    "Feedback",
    "FeedbackAnalysis",
    "WorldStateHistory",
    "EnvironmentPrediction",
    "EnvironmentEvent",
    "CausalAnalysis",
    "MultiStepPrediction",
    "ExperienceSummary",
    "EmbodiedGoal",
]
