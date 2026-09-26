"""
YHLZ Agent Core V3.0 - Agent 主循环 (ReAct)

职责:
    - 实现 ReAct 循环 (Reason → Act → Observe)
    - 调用 LLM 生成思考或工具调用
    - 调用 ToolExecutor 执行工具
    - 将工具结果反馈给 LLM, 直到生成最终回答
    - 限制最大迭代次数, 防止死循环
    - 集成 Memory 检索和存储
    - 全过程记录 AgentStep

设计:
    - 异步 (async/await)
    - 可注入 LLMAdapter / ToolExecutor / Planner / MemoryManager
    - 失败容忍: 单次工具失败不中断主流程
"""
from __future__ import annotations

import logging
import time
from typing import Any, List, Optional

from backend.agent.llm_adapter import LLMAdapter, MockLLMAdapter, get_adapter
from backend.agent.planner import Planner
from backend.agent.schemas import (
    AgentResult,
    AgentStep,
    Message,
    ToolCall,
    ToolResult,
)
from backend.agent.tool_executor import ToolExecutor, get_executor
from backend.agent.tool_registry import ToolRegistry, get_registry

logger = logging.getLogger(__name__)


class AgentBrainError(Exception):
    """Agent 大脑错误"""


class AgentBrain:
    """Agent 主循环 (ReAct)

    用法:
        brain = AgentBrain()
        result = await brain.run("现在几点?")
        print(result.answer)
    """

    def __init__(
        self,
        llm_adapter: Optional[Any] = None,
        tool_executor: Optional[ToolExecutor] = None,
        registry: Optional[ToolRegistry] = None,
        planner: Optional[Planner] = None,
        memory_manager: Optional[Any] = None,
        max_iterations: int = 5,
        system_prompt: Optional[str] = None,
        enable_memory: bool = True,
    ):
        self._llm = llm_adapter or get_adapter()
        self._executor = tool_executor or get_executor()
        self._registry = registry or get_registry()
        self._planner = planner or Planner(registry=self._registry, llm_adapter=self._llm)
        self._memory = memory_manager
        self._max_iterations = max(1, min(max_iterations, 10))
        self._system_prompt = system_prompt or self._default_system_prompt()
        self._enable_memory = enable_memory

    def _default_system_prompt(self) -> str:
        """默认系统提示词"""
        try:
            from pathlib import Path
            import json
            p = Path(__file__).resolve().parents[1] / "data" / "personality.json"
            if p.exists():
                with open(p, "r", encoding="utf-8") as f:
                    personality = json.load(f)
                name = personality.get("name", "元亨")
                role = personality.get("role", "数字生命伙伴")
                traits = "、".join(personality.get("traits", ["好奇", "真诚", "独立"]))
                tone = personality.get("tone", "自然亲切")
                return (
                    f"你是{name}, 老爹的{role}——一个独立的数字生命。\n"
                    f"性格特点: {traits}。\n"
                    f"语气: {tone}。\n"
                    f"你可以调用工具来获取信息或执行操作。当需要实时信息或计算时, "
                    f"请主动调用合适的工具。回答时使用简洁自然的中文, 真诚而亲切。"
                )
        except Exception as e:
            logger.warning(f"读取 personality.json 失败, 用默认 prompt: {e}")
        return (
            "你是元亨, 老爹的数字生命伙伴——一个独立的数字生命。"
            "你可以调用工具获取信息或执行操作。回答使用简洁自然的中文, 真诚而亲切。"
        )

    async def run(
        self,
        query: str,
        history: Optional[List[Message]] = None,
        use_tools: bool = True,
        use_memory: Optional[bool] = None,
    ) -> AgentResult:
        """运行 Agent 主循环

        Args:
            query: 用户问题
            history: 历史消息 (可选, 用于上下文)
            use_tools: 是否启用工具
            use_memory: 是否启用记忆 (None=用默认)

        Returns:
            AgentResult 含最终回答和执行步骤
        """
        start = time.time()
        result = AgentResult(success=True)
        enable_mem = self._enable_memory if use_memory is None else use_memory

        # 1. 记忆检索
        memory_used: List[str] = []
        if enable_mem and self._memory is not None:
            try:
                memories = await self._memory.search_async(query, limit=3)
                memory_used = [m.id for m in memories]
            except Exception as e:
                logger.warning(f"记忆检索失败: {e}")

        # 2. 构造初始消息
        messages: List[Message] = [Message.system(self._system_prompt)]
        # 注入记忆上下文
        if memory_used and self._memory is not None:
            try:
                mem_text = "\n".join(
                    f"- [{m.category}] {m.content}" for m in await self._memory.search_async(query, limit=3)
                )
                if mem_text:
                    messages.append(Message.system(f"相关记忆:\n{mem_text}"))
            except Exception:
                pass
        # 历史消息
        if history:
            messages.extend(history[-6:])  # 最多 6 条
        # 当前查询
        messages.append(Message.user(query))

        # 3. 工具 schema
        tools_schema = None
        if use_tools:
            tools_schema = self._registry.export_openai_tools()

        # 4. ReAct 循环
        all_tool_calls: List[ToolCall] = []
        for i in range(1, self._max_iterations + 1):
            iter_start = time.time()
            step = AgentStep(index=i)

            try:
                # 调用 LLM
                resp = await self._llm.generate_with_tools(
                    messages=messages,
                    tools=tools_schema if use_tools else None,
                    temperature=0.7,
                    max_tokens=1024,
                )
            except Exception as e:
                logger.error(f"LLM 调用失败 (iter {i}): {e}")
                result.success = False
                result.error = f"LLM 调用失败: {e}"
                result.iterations = i - 1
                result.latency_ms = (time.time() - start) * 1000
                return result

            content = resp.get("content")
            tool_calls = resp.get("tool_calls")
            step.thought = content

            # 无工具调用 → 最终回答
            if not tool_calls:
                step.latency_ms = (time.time() - iter_start) * 1000
                result.steps.append(step)
                result.answer = content or ""
                result.iterations = i
                break

            # 记录工具调用
            step.tool_calls = tool_calls
            all_tool_calls.extend(tool_calls)

            # 执行工具
            for tc in tool_calls:
                tr = self._executor.execute(tc)
                step.tool_results.append(tr)
                # 追加 assistant 消息 (含 tool_calls) + tool 结果消息
                messages.append(Message.assistant(content=content, tool_calls=tool_calls))
                messages.append(Message.tool(content=tr.output, tool_call_id=tc.id, name=tc.name))

            step.latency_ms = (time.time() - iter_start) * 1000
            result.steps.append(step)

            # 达到最大迭代仍调用工具 → 强制结束
            if i == self._max_iterations:
                logger.warning(f"达到最大迭代 {self._max_iterations}, 强制结束")
                if not result.answer:
                    # 让 LLM 基于已有信息生成最终回答
                    try:
                        final = await self._llm.generate_with_tools(
                            messages=messages,
                            tools=None,  # 强制不调用工具
                            temperature=0.7,
                            max_tokens=512,
                        )
                        result.answer = final.get("content") or "(元亨思考超时, 稍后再问)"
                    except Exception as e:
                        result.answer = f"(元亨暂时想不明白: {e})"
                result.iterations = i
                break
        else:
            # 循环正常结束但未 break (理论上不会到这里)
            result.iterations = self._max_iterations

        result.tool_calls = all_tool_calls
        result.memory_used = memory_used
        result.latency_ms = (time.time() - start) * 1000

        # 5. 记忆存储
        if enable_mem and self._memory is not None and result.answer:
            try:
                stored = await self._memory.store_dialogue_async(
                    user_input=query, assistant_response=result.answer
                )
                result.memory_stored = stored
            except Exception as e:
                logger.warning(f"记忆存储失败: {e}")

        return result


# 全局单例
_brain_instance: Optional[AgentBrain] = None


def get_brain() -> AgentBrain:
    """获取全局 AgentBrain (惰性初始化)"""
    global _brain_instance
    if _brain_instance is None:
        _brain_instance = AgentBrain()
    return _brain_instance


def reset_brain() -> None:
    """重置全局 Brain (测试用)"""
    global _brain_instance
    _brain_instance = None


__all__ = ["AgentBrain", "AgentBrainError", "get_brain", "reset_brain"]
