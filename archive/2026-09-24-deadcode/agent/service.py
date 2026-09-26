"""
YHLZ Agent Core V3.0 - AgentService 统一入口

职责:
    - 对外暴露统一 API
    - 组装 AgentBrain / ToolExecutor / Planner / MemoryManager
    - 同步与异步接口并存
    - 供 main.py 的 /agent/* 端点调用

设计:
    - 单例 (get_service)
    - 可注入所有依赖 (测试用)
    - 不直接操作 FastAPI / HTTP, 保持纯净
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

from backend.agent.agent_brain import AgentBrain, get_brain
from backend.agent.llm_adapter import LLMAdapter, MockLLMAdapter, get_adapter
from backend.agent.memory import MemoryEntry, MemoryManager, get_memory_manager
from backend.agent.planner import Planner
from backend.agent.schemas import AgentResult, Message, Plan
from backend.agent.tool_executor import ToolExecutor, get_executor
from backend.agent.tool_registry import ToolRegistry, get_registry

logger = logging.getLogger(__name__)


class AgentServiceError(Exception):
    """Agent 服务错误"""


class AgentService:
    """Agent 统一服务

    用法:
        svc = get_service()
        result = await svc.chat("现在几点?")
        plan = svc.plan("写一首诗")
        tools = svc.list_tools()
    """

    def __init__(
        self,
        brain: Optional[AgentBrain] = None,
        registry: Optional[ToolRegistry] = None,
        executor: Optional[ToolExecutor] = None,
        planner: Optional[Planner] = None,
        memory: Optional[MemoryManager] = None,
        llm_adapter: Optional[Any] = None,
    ):
        self._registry = registry or get_registry()
        self._executor = executor or get_executor()
        self._memory = memory or get_memory_manager()
        self._llm = llm_adapter or get_adapter()
        self._planner = planner or Planner(registry=self._registry, llm_adapter=self._llm)
        self._brain = brain or AgentBrain(
            llm_adapter=self._llm,
            tool_executor=self._executor,
            registry=self._registry,
            planner=self._planner,
            memory_manager=self._memory,
        )

    # ------------------------------------------------------------------
    # Agent 对话
    # ------------------------------------------------------------------

    async def chat(
        self,
        query: str,
        history: Optional[List[Message]] = None,
        use_tools: bool = True,
        use_memory: Optional[bool] = None,
    ) -> AgentResult:
        """Agent 对话主入口"""
        if not query or not query.strip():
            return AgentResult(success=False, error="查询为空", answer="")
        try:
            return await self._brain.run(
                query=query,
                history=history,
                use_tools=use_tools,
                use_memory=use_memory,
            )
        except Exception as e:
            logger.error(f"Agent 对话失败: {e}", exc_info=True)
            return AgentResult(success=False, error=str(e), answer="")

    async def chat_stream(
        self,
        query: str,
        history: Optional[List[Message]] = None,
    ):
        """流式 Agent 对话 (yield 字符串)

        注意: V3.0 流式不支持工具调用, 工具调用走 chat() 同步返回。
        """
        if not query or not query.strip():
            yield "(查询为空)"
            return
        # 简单流式: 直接走 LLM 流式, 不走 ReAct
        from backend.agent.schemas import Message as Msg
        messages: List[Msg] = [Msg.system(self._brain._system_prompt)]
        if history:
            messages.extend(history[-6:])
        messages.append(Msg.user(query))
        try:
            async for ch in self._llm.stream_generate(messages, temperature=0.7, max_tokens=1024):
                yield ch
        except Exception as e:
            logger.error(f"流式对话失败: {e}")
            yield f"(出错: {e})"

    # ------------------------------------------------------------------
    # 规划
    # ------------------------------------------------------------------

    def plan(self, goal: str, available_tools: Optional[List[str]] = None) -> Plan:
        """生成执行计划 (同步)"""
        return self._planner.plan(goal, available_tools)

    async def plan_async(self, goal: str, available_tools: Optional[List[str]] = None) -> Plan:
        """生成执行计划 (异步, 可走 LLM)"""
        return await self._planner.plan_async(goal, available_tools)

    # ------------------------------------------------------------------
    # 工具管理
    # ------------------------------------------------------------------

    def list_tools(self, category: Optional[str] = None) -> List[Dict[str, Any]]:
        """列出工具"""
        tools = self._registry.list_tools(category=category)
        return [
            {
                "name": t.name,
                "description": t.description,
                "category": t.category,
                "parameters": t.parameters.to_dict(),
            }
            for t in tools
        ]

    def get_tool(self, name: str) -> Optional[Dict[str, Any]]:
        """获取工具详情"""
        t = self._registry.get(name)
        if t is None:
            return None
        return {
            "name": t.name,
            "description": t.description,
            "category": t.category,
            "parameters": t.parameters.to_dict(),
        }

    def export_openai_tools(self, names: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """导出 OpenAI tools 参数"""
        return self._registry.export_openai_tools(names=names)

    # ------------------------------------------------------------------
    # 记忆管理
    # ------------------------------------------------------------------

    async def memory_add(self, content: str, category: str = "fact",
                          source: str = "system", metadata: Optional[Dict] = None) -> str:
        return await self._memory.add_async(content, category, source, metadata)

    async def memory_get(self, memory_id: str) -> Optional[MemoryEntry]:
        return await self._memory.get_async(memory_id)

    async def memory_update(self, memory_id: str, **fields) -> bool:
        return await self._memory.update_async(memory_id, **fields)

    async def memory_delete(self, memory_id: str) -> bool:
        return await self._memory.delete_async(memory_id)

    async def memory_list(self, category: Optional[str] = None, limit: int = 100, offset: int = 0) -> List[MemoryEntry]:
        return await self._memory.list_async(category, limit, offset)

    async def memory_search(self, query: str, limit: int = 5, category: Optional[str] = None) -> List[MemoryEntry]:
        return await self._memory.search_async(query, limit, category)

    async def memory_count(self, category: Optional[str] = None) -> int:
        return await self._memory.count_async(category)

    async def memory_clear(self) -> int:
        return await self._memory.clear_async()

    def memory_short_term(self, limit: int = 10) -> List[Dict[str, Any]]:
        """获取短期记忆"""
        return self._memory.get_short_term(limit=limit)

    # ------------------------------------------------------------------
    # 状态
    # ------------------------------------------------------------------

    def status(self) -> Dict[str, Any]:
        """获取 Agent 系统状态"""
        return {
            "version": "3.0.0",
            "llm_mode": "mock" if isinstance(self._llm, MockLLMAdapter) else "real",
            "tools_count": len(self._registry),
            "builtin_tools": self._registry.list_names("builtin"),
            "custom_tools": self._registry.list_names("custom"),
            "plugin_tools": self._registry.list_names("plugin"),
            "memory_enabled": self._memory is not None,
        }


# ----------------------------------------------------------------------
# 全局单例
# ----------------------------------------------------------------------

_service_instance: Optional[AgentService] = None
_service_lock = None


def _get_service_lock():
    import threading
    global _service_lock
    if _service_lock is None:
        _service_lock = threading.Lock()
    return _service_lock


def get_service() -> AgentService:
    """获取全局 AgentService"""
    global _service_instance
    if _service_instance is not None:
        return _service_instance
    with _get_service_lock():
        if _service_instance is not None:
            return _service_instance
        _service_instance = AgentService()
        return _service_instance


def reset_service() -> None:
    """重置全局服务 (测试用)"""
    global _service_instance
    with _get_service_lock():
        _service_instance = None


def reset_all() -> None:
    """重置所有 Agent 全局状态 (测试用)"""
    from backend.agent.agent_brain import reset_brain
    from backend.agent.llm_adapter import reset_adapter
    from backend.agent.memory import reset_memory_manager
    from backend.agent.tool_executor import reset_executor
    from backend.agent.tool_registry import reset_registry
    reset_service()
    reset_brain()
    reset_adapter()
    reset_memory_manager()
    reset_executor()
    reset_registry()


__all__ = [
    "AgentService", "AgentServiceError",
    "get_service", "reset_service", "reset_all",
]
