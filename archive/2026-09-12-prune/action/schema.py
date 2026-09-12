"""
YHLZ Vision Action V1.0 - 行动层数据结构

职责:
    - 定义统一行动请求 (ActionRequest)
    - 定义统一行动结果 (ActionResult)
    - 枚举: ActionType / ActionStatus / RiskLevel
    - 检索条件 (ActionQuery)
    - 不依赖任何外部库 (仅 stdlib + typing)
    - 不依赖 Agent / Voice / Vision (自包含, 便于独立测试)

设计原则:
    - 不可变 (frozen dataclass 语义: 使用 dataclass + 明确字段)
    - 类型注解完整
    - 兼容 JSON 序列化 (to_dict / from_dict)
    - 行动记录独立存储 (绝不写入 Agent Memory)
    - 先理解行动, 再执行行动 (request 必须包含 reason / confidence)
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

class ActionType(str, Enum):
    """行动类型 (抽象行动, 非设备操作)"""
    OPEN = "open"              # 打开 (应用 / 页面 / 日志)
    NAVIGATE = "navigate"      # 导航 (跳转 / 定位)
    CHECK = "check"            # 检查 (状态 / 健康度)
    QUERY = "query"            # 查询 (数据 / 信息)
    REPORT = "report"          # 报告 (生成报告 / 总结)
    EXECUTE = "execute"        # 执行 (通用操作)
    CUSTOM = "custom"          # 自定义

    @classmethod
    def values(cls) -> List[str]:
        return [t.value for t in cls]


class ActionStatus(str, Enum):
    """行动状态"""
    PENDING = "pending"                  # 已创建, 待执行
    APPROVED = "approved"                # 已批准
    RUNNING = "running"                  # 执行中
    OK = "ok"                            # 成功
    DENIED = "denied"                    # 权限拒绝
    INVALID = "invalid"                  # 请求不合法
    AWAITING_CONFIRM = "awaiting_confirm"  # 高风险待确认
    CANCELLED = "cancelled"              # 已取消
    ERROR = "error"                      # 执行错误
    UNSUPPORTED = "unsupported"          # 执行器不支持
    TIMEOUT = "timeout"                  # 超时


class RiskLevel(str, Enum):
    """风险等级"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

    @classmethod
    def values(cls) -> List[str]:
        return [r.value for r in cls]


# ----------------------------------------------------------------------
# 行动请求
# ----------------------------------------------------------------------

@dataclass
class ActionRequest:
    """行动请求

    字段:
        action_id:   行动唯一 ID
        action_type: 行动类型 (ActionType)
        target:      行动目标 (如 'logs' / 'browser' / 'app:settings')
        parameters:  参数 (依赖执行器, 如 {'text': '...'} / {'key': 'enter'})
        reason:      行动理由 (LLM 生成, 用于审计 / 解释)
        confidence:  置信度 (0.0 ~ 1.0, 理解→行动的依据强度)
        risk_level:  声明的风险等级 (实际等级由 Permission 规则评估)
        created_at:  创建时间
    """
    action_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    action_type: str = ActionType.CUSTOM.value
    target: str = ""
    parameters: Dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    confidence: float = 0.0
    risk_level: str = RiskLevel.LOW.value
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action_id": self.action_id,
            "action_type": self.action_type,
            "target": self.target,
            "parameters": self.parameters,
            "reason": self.reason,
            "confidence": round(self.confidence, 4),
            "risk_level": self.risk_level,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ActionRequest":
        return cls(
            action_id=d.get("action_id", uuid.uuid4().hex),
            action_type=d.get("action_type", ActionType.CUSTOM.value),
            target=d.get("target", ""),
            parameters=dict(d.get("parameters", {}) or {}),
            reason=d.get("reason", ""),
            confidence=float(d.get("confidence", 0.0)),
            risk_level=d.get("risk_level", RiskLevel.LOW.value),
            created_at=float(d.get("created_at", time.time())),
        )

    @classmethod
    def create(
        cls,
        action_type: str = ActionType.CUSTOM.value,
        target: str = "",
        parameters: Optional[Dict[str, Any]] = None,
        reason: str = "",
        confidence: float = 0.0,
        risk_level: str = RiskLevel.LOW.value,
    ) -> "ActionRequest":
        """构造行动请求"""
        return cls(
            action_type=action_type,
            target=target,
            parameters=parameters or {},
            reason=reason,
            confidence=confidence,
            risk_level=risk_level,
        )


# ----------------------------------------------------------------------
# 行动结果
# ----------------------------------------------------------------------

@dataclass
class ActionResult:
    """行动结果

    字段:
        action_id:  关联行动 ID
        status:     状态 (ActionStatus)
        message:    人类可读说明
        output:     结构化输出 (依赖执行器)
        error:      错误信息 (None=无错误)
        timestamp:  完成时间
    """
    action_id: str = ""
    status: str = ActionStatus.PENDING.value
    message: str = ""
    output: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action_id": self.action_id,
            "status": self.status,
            "message": self.message,
            "output": self.output,
            "error": self.error,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ActionResult":
        return cls(
            action_id=d.get("action_id", ""),
            status=d.get("status", ActionStatus.PENDING.value),
            message=d.get("message", ""),
            output=d.get("output"),
            error=d.get("error"),
            timestamp=float(d.get("timestamp", time.time())),
        )


# ----------------------------------------------------------------------
# 检索条件
# ----------------------------------------------------------------------

@dataclass
class ActionQuery:
    """行动记录检索条件

    Attributes:
        action_type: 行动类型过滤
        status:      状态过滤
        risk_level:  风险等级过滤
        limit:       返回数量上限
        offset:      偏移量 (分页)
    """
    action_type: Optional[str] = None
    status: Optional[str] = None
    risk_level: Optional[str] = None
    limit: int = 50
    offset: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action_type": self.action_type,
            "status": self.status,
            "risk_level": self.risk_level,
            "limit": self.limit,
            "offset": self.offset,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ActionQuery":
        return cls(
            action_type=d.get("action_type"),
            status=d.get("status"),
            risk_level=d.get("risk_level"),
            limit=int(d.get("limit", 50)),
            offset=int(d.get("offset", 0)),
        )


__all__ = [
    "ActionType",
    "ActionStatus",
    "RiskLevel",
    "ActionRequest",
    "ActionResult",
    "ActionQuery",
]
