"""
YHLZ Agent Core V3.0 - 数据模型

定义 Agent 系统的全部数据结构, 使用 dataclass + 类型注解,
避免 pydantic 依赖, 保持轻量。
"""
from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


# ----------------------------------------------------------------------
# 消息
# ----------------------------------------------------------------------

@dataclass
class Message:
    """对话消息 (OpenAI 兼容格式)

    Attributes:
        role: system | user | assistant | tool
        content: 文本内容 (tool 角色时为工具结果 JSON 字符串)
        tool_calls: assistant 触发的工具调用列表
        tool_call_id: tool 角色消息对应的 tool_call_id
        name: 工具名称 (tool 角色)
    """
    role: str
    content: Optional[str] = None
    tool_calls: Optional[List["ToolCall"]] = None
    tool_call_id: Optional[str] = None
    name: Optional[str] = None

    def to_openai_dict(self) -> Dict[str, Any]:
        """转为 OpenAI API 兼容 dict"""
        d: Dict[str, Any] = {"role": self.role}
        if self.content is not None:
            d["content"] = self.content
        if self.tool_calls:
            d["tool_calls"] = [tc.to_openai_dict() for tc in self.tool_calls]
        if self.tool_call_id is not None:
            d["tool_call_id"] = self.tool_call_id
        if self.name is not None:
            d["name"] = self.name
        return d

    @classmethod
    def system(cls, content: str) -> "Message":
        return cls(role="system", content=content)

    @classmethod
    def user(cls, content: str) -> "Message":
        return cls(role="user", content=content)

    @classmethod
    def assistant(cls, content: Optional[str] = None,
                  tool_calls: Optional[List["ToolCall"]] = None) -> "Message":
        return cls(role="assistant", content=content, tool_calls=tool_calls)

    @classmethod
    def tool(cls, content: str, tool_call_id: str, name: str) -> "Message":
        return cls(role="tool", content=content, tool_call_id=tool_call_id, name=name)


# ----------------------------------------------------------------------
# 工具
# ----------------------------------------------------------------------

@dataclass
class ToolSchema:
    """工具参数 schema (JSON Schema 子集, OpenAI function 兼容)

    Attributes:
        type: 固定 "object"
        properties: 参数属性 {name: {type, description, ...}}
        required: 必填参数名列表
    """
    type: str = "object"
    properties: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    required: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type,
            "properties": dict(self.properties),
            "required": list(self.required),
        }


@dataclass
class Tool:
    """工具定义

    Attributes:
        name: 工具唯一名 (snake_case)
        description: 工具描述 (LLM 据此决定是否调用)
        parameters: 参数 schema
        handler: 可调用对象 (运行时注入, 不参与序列化)
        category: 工具分类 (builtin/plugin/custom)
        metadata: 额外元数据
    """
    name: str
    description: str
    parameters: ToolSchema
    handler: Optional[Any] = None  # Callable[[Dict], Any]
    category: str = "custom"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_openai_dict(self) -> Dict[str, Any]:
        """转为 OpenAI tools 参数格式"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters.to_dict(),
            },
        }


@dataclass
class ToolCall:
    """LLM 触发的工具调用

    Attributes:
        id: 调用 ID (LLM 返回, 用于关联 tool 消息)
        name: 工具名
        arguments: 调用参数 (dict, 已解析)
        raw_arguments: 原始参数 JSON 字符串 (兜底)
    """
    id: str
    name: str
    arguments: Dict[str, Any] = field(default_factory=dict)
    raw_arguments: str = ""

    def to_openai_dict(self) -> Dict[str, Any]:
        import json
        return {
            "id": self.id,
            "type": "function",
            "function": {
                "name": self.name,
                "arguments": self.raw_arguments or json.dumps(self.arguments, ensure_ascii=False),
            },
        }

    @classmethod
    def from_openai_dict(cls, d: Dict[str, Any]) -> "ToolCall":
        import json
        func = d.get("function", {})
        raw = func.get("arguments", "{}")
        try:
            args = json.loads(raw) if raw else {}
        except Exception:
            args = {}
        return cls(
            id=d.get("id", ""),
            name=func.get("name", ""),
            arguments=args,
            raw_arguments=raw,
        )


@dataclass
class ToolResult:
    """工具执行结果

    Attributes:
        tool_call_id: 关联的 ToolCall.id
        name: 工具名
        output: 执行输出 (字符串, 进入 LLM 上下文)
        is_error: 是否执行出错
        latency_ms: 执行耗时
    """
    tool_call_id: str
    name: str
    output: str
    is_error: bool = False
    latency_ms: float = 0.0


# ----------------------------------------------------------------------
# 规划
# ----------------------------------------------------------------------

@dataclass
class PlanStep:
    """规划步骤

    Attributes:
        id: 步骤 ID
        description: 步骤描述
        tool: 预期使用的工具名 (可选)
        status: pending | running | done | failed | skipped
        result: 步骤结果
    """
    id: str
    description: str
    tool: Optional[str] = None
    status: str = "pending"
    result: Optional[str] = None


@dataclass
class Plan:
    """执行计划

    Attributes:
        id: 计划 ID
        goal: 目标
        steps: 步骤列表
        created_at: 创建时间戳
    """
    id: str
    goal: str
    steps: List[PlanStep] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    @classmethod
    def create(cls, goal: str, step_descs: List[str]) -> "Plan":
        pid = f"plan_{uuid.uuid4().hex[:8]}"
        steps = [
            PlanStep(id=f"step_{i+1}", description=desc)
            for i, desc in enumerate(step_descs)
        ]
        return cls(id=pid, goal=goal, steps=steps)


# ----------------------------------------------------------------------
# Agent 执行
# ----------------------------------------------------------------------

@dataclass
class AgentStep:
    """Agent 一次推理-行动-观察循环

    Attributes:
        index: 步骤序号 (从 1 开始)
        thought: LLM 思考内容 (assistant 消息)
        tool_calls: 触发的工具调用
        tool_results: 工具执行结果
        latency_ms: 本步耗时
    """
    index: int
    thought: Optional[str] = None
    tool_calls: List[ToolCall] = field(default_factory=list)
    tool_results: List[ToolResult] = field(default_factory=list)
    latency_ms: float = 0.0


@dataclass
class AgentResult:
    """Agent 执行最终结果

    Attributes:
        answer: 最终回答
        steps: 执行步骤记录
        tool_calls: 全部工具调用
        memory_used: 使用的记忆条目 ID 列表
        memory_stored: 本次存储的记忆条目数
        latency_ms: 总耗时
        iterations: 循环次数
        success: 是否成功
        error: 失败原因
    """
    answer: str = ""
    steps: List[AgentStep] = field(default_factory=list)
    tool_calls: List[ToolCall] = field(default_factory=list)
    memory_used: List[str] = field(default_factory=list)
    memory_stored: int = 0
    latency_ms: float = 0.0
    iterations: int = 0
    success: bool = True
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        # tool_calls 转为可序列化形式
        d["tool_calls"] = [tc.to_openai_dict() for tc in self.tool_calls]
        return d


__all__ = [
    "Message", "Tool", "ToolSchema", "ToolCall", "ToolResult",
    "Plan", "PlanStep", "AgentStep", "AgentResult",
]
