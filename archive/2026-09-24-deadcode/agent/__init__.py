"""
YHLZ Agent Core V3.0
建立 AI 大脑, 实现推理、规划、工具调用

模块结构:
    agent/
    ├── __init__.py          ← 本文件: 统一导出
    ├── schemas.py           ← 数据模型 (Message/Tool/ToolCall/Plan/AgentResult)
    ├── plugin_sdk.py        ← 插件 SDK (NekoPluginBase/neko_plugin/plugin_entry)
    ├── tool_registry.py     ← 工具注册中心 + 内置工具
    ├── tool_executor.py     ← 工具执行器 (参数校验/超时/异常隔离)
    ├── llm_adapter.py       ← LLM tool calling 适配器 (mock + real)
    ├── planner.py           ← 任务规划器
    ├── agent_brain.py       ← Agent 主循环 (ReAct)
    ├── service.py           ← AgentService 统一入口
    ├── memory/
    │   ├── __init__.py      ← 记忆系统统一导出
    │   ├── base.py          ← 抽象接口
    │   ├── sqlite_store.py  ← SQLite 持久化
    │   └── manager.py       ← 记忆管理器
    └── tests/               ← 测试套件

设计要点:
    - 不破坏 V2.3 已有接口, 新增 /agent/* 端点
    - TEST_MODE 兼容: LLMAdapter 支持 mock 模式
    - 配置驱动: agent 行为可通过 config.py 调整
    - 可插拔: ToolRegistry 支持运行时注册新工具
"""
from __future__ import annotations

from backend.agent.schemas import (
    AgentResult,
    AgentStep,
    Message,
    Plan,
    PlanStep,
    Tool,
    ToolCall,
    ToolResult,
    ToolSchema,
)
from backend.agent.plugin_sdk import (
    NekoPluginBase,
    Ok,
    Err,
    neko_plugin,
    plugin_entry,
)
from backend.agent.tool_registry import (
    BUILTIN_TOOLS,
    ToolRegistry,
    ToolRegistryError,
    get_registry,
    register_tool,
)
from backend.agent.tool_executor import (
    ToolExecutor,
    ToolExecutorError,
    execute_tool,
)
from backend.agent.llm_adapter import (
    LLMAdapter,
    LLMAdapterError,
    MockLLMAdapter,
    get_adapter,
)
from backend.agent.planner import (
    Planner,
    PlannerError,
)
from backend.agent.agent_brain import (
    AgentBrain,
    AgentBrainError,
)
from backend.agent.memory import (
    MemoryEntry,
    MemoryManager,
    MemoryManagerError,
    MemoryStore,
    SQLiteMemoryStore,
    get_memory_manager,
)
from backend.agent.service import (
    AgentService,
    AgentServiceError,
    get_service,
)

__all__ = [
    # schemas
    "Message", "Tool", "ToolCall", "ToolResult", "ToolSchema",
    "Plan", "PlanStep", "AgentStep", "AgentResult",
    # sdk
    "NekoPluginBase", "Ok", "Err", "neko_plugin", "plugin_entry",
    # registry
    "ToolRegistry", "ToolRegistryError", "BUILTIN_TOOLS",
    "get_registry", "register_tool",
    # executor
    "ToolExecutor", "ToolExecutorError", "execute_tool",
    # llm
    "LLMAdapter", "LLMAdapterError", "MockLLMAdapter", "get_adapter",
    # planner
    "Planner", "PlannerError",
    # brain
    "AgentBrain", "AgentBrainError",
    # memory
    "MemoryStore", "SQLiteMemoryStore", "MemoryManager", "MemoryManagerError",
    "MemoryEntry", "get_memory_manager",
    # service
    "AgentService", "AgentServiceError", "get_service",
]

__version__ = "3.0.0"
