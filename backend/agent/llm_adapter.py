"""
YHLZ Agent Core V3.0 - LLM 适配器

职责:
    - 在 V2.3 llm_engine 基础上扩展 tool calling 支持
    - 提供 mock 模式 (TEST_MODE / 无 API key 环境)
    - 统一 OpenAI 兼容协议 (DashScope/DeepSeek)
    - 异步流式与非流式接口
    - 工具调用响应解析

设计:
    - 不修改 V2.3 llm_engine.py (保持向后兼容)
    - 复用 llm_engine 的 AsyncOpenAI 客户端
    - TEST_MODE 走 MockLLMAdapter (规则驱动, 可测试)
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

from backend.agent.schemas import Message, ToolCall

logger = logging.getLogger(__name__)


class LLMAdapterError(Exception):
    """LLM 适配器错误"""


# ----------------------------------------------------------------------
# Mock LLM Adapter (测试环境)
# ----------------------------------------------------------------------

class MockLLMAdapter:
    """Mock LLM 适配器 (规则驱动)

    用于 TEST_MODE 或无 API key 环境。
    行为规则:
        - 若消息含工具相关关键词 (时间/日期/计算/http), 返回对应 tool_call
        - 否则返回简单文本回应
        - 第二轮 (含 tool 消息) 综合工具结果生成最终回答
    """

    def __init__(self, model: str = "mock-llm"):
        self.model = model
        self._call_count = 0

    async def generate_with_tools(
        self,
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        **kwargs,
    ) -> Dict[str, Any]:
        """Mock 工具调用生成

        Returns:
            OpenAI 兼容响应 dict:
            {
                "content": Optional[str],
                "tool_calls": Optional[List[ToolCall]],
            }
        """
        self._call_count += 1
        await asyncio.sleep(0.01)  # 模拟延迟

        # 取最后一条 user 消息
        last_user = ""
        has_tool_result = False
        for m in reversed(messages):
            if m.role == "user" and last_user == "":
                last_user = m.content or ""
            if m.role == "tool":
                has_tool_result = True
                break

        last_user_lower = last_user.lower()

        # 已有工具结果 → 生成最终回答
        if has_tool_result:
            # 找最近的 tool 消息
            tool_results = [m for m in messages if m.role == "tool"]
            summary_parts = []
            for tm in tool_results[-3:]:  # 最多 3 条
                summary_parts.append(f"[{tm.name}] {tm.content}")
            summary = "; ".join(summary_parts) if summary_parts else "(无工具结果)"
            return {
                "content": f"根据工具结果: {summary}",
                "tool_calls": None,
            }

        # 触发工具调用的关键词匹配
        if tools:
            tool_names = [t["function"]["name"] for t in tools if "function" in t]
            if "get_time" in tool_names and ("时间" in last_user or "几点" in last_user or "time" in last_user_lower):
                return {
                    "content": None,
                    "tool_calls": [ToolCall(
                        id=f"call_{uuid.uuid4().hex[:8]}",
                        name="get_time",
                        arguments={"format": "%Y-%m-%d %H:%M:%S"},
                        raw_arguments=json.dumps({"format": "%Y-%m-%d %H:%M:%S"}),
                    )],
                }
            if "get_date" in tool_names and ("日期" in last_user or "几号" in last_user or "date" in last_user_lower):
                return {
                    "content": None,
                    "tool_calls": [ToolCall(
                        id=f"call_{uuid.uuid4().hex[:8]}",
                        name="get_date",
                        arguments={},
                        raw_arguments="{}",
                    )],
                }
            if "calculator" in tool_names and any(c in last_user for c in ["+", "-", "*", "/", "计算", "等于", "多少"]):
                # 简单提取表达式
                expr = last_user.replace("计算", "").replace("等于多少", "").replace("=", "").strip()
                if not expr:
                    expr = "1+1"
                return {
                    "content": None,
                    "tool_calls": [ToolCall(
                        id=f"call_{uuid.uuid4().hex[:8]}",
                        name="calculator",
                        arguments={"expression": expr},
                        raw_arguments=json.dumps({"expression": expr}),
                    )],
                }
            if "http_get" in tool_names and ("http" in last_user_lower or "网页" in last_user or "url" in last_user_lower):
                return {
                    "content": None,
                    "tool_calls": [ToolCall(
                        id=f"call_{uuid.uuid4().hex[:8]}",
                        name="http_get",
                        arguments={"url": "https://example.com", "timeout": 5.0},
                        raw_arguments=json.dumps({"url": "https://example.com", "timeout": 5.0}),
                    )],
                }

        # 普通文本回应
        if not last_user:
            return {"content": "(mock) 你好, 我是元亨", "tool_calls": None}
        return {
            "content": f"(mock) 收到哥们, 你说: {last_user}",
            "tool_calls": None,
        }

    async def generate(
        self,
        messages: List[Message],
        temperature: float = 0.7,
        max_tokens: int = 1024,
        **kwargs,
    ) -> str:
        """Mock 普通生成"""
        r = await self.generate_with_tools(messages, tools=None, temperature=temperature, max_tokens=max_tokens)
        return r["content"] or ""

    async def stream_generate(
        self,
        messages: List[Message],
        temperature: float = 0.7,
        max_tokens: int = 1024,
        **kwargs,
    ):
        """Mock 流式生成 (按字符切片)"""
        text = await self.generate(messages, temperature, max_tokens)
        for ch in text:
            yield ch
            await asyncio.sleep(0.001)


# ----------------------------------------------------------------------
# Real LLM Adapter (OpenAI 兼容)
# ----------------------------------------------------------------------

class LLMAdapter:
    """真实 LLM 适配器 (OpenAI 兼容协议)

    复用 V2.3 llm_engine 的 AsyncOpenAI 客户端, 扩展 tool calling。

    用法:
        adapter = LLMAdapter()
        resp = await adapter.generate_with_tools(messages, tools)
    """

    def __init__(
        self,
        client: Any = None,
        model: Optional[str] = None,
        provider: Optional[str] = None,
    ):
        self._client = client
        self._model = model
        self._provider = provider

    def _ensure_client(self) -> Any:
        """惰性获取 AsyncOpenAI 客户端"""
        if self._client is not None:
            return self._client
        # 复用 V2.3 llm_engine 的客户端
        try:
            from backend.llm_engine import llm_engine
            client = getattr(llm_engine, "client", None)
            if client is None:
                raise LLMAdapterError("llm_engine.client 为 None (API key 未配置?)")
            self._client = client
            return client
        except ImportError as e:
            raise LLMAdapterError(f"无法导入 llm_engine: {e}")

    def _get_model(self) -> str:
        """获取模型名"""
        if self._model is not None:
            return self._model
        try:
            from backend.config import config
            if config.api_provider == "dashscope":
                return config.dashscope_model
            return config.deepseek_model
        except Exception:
            return "qwen-turbo"

    async def generate_with_tools(
        self,
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        tool_choice: str = "auto",
        **kwargs,
    ) -> Dict[str, Any]:
        """带工具调用支持的生成

        Args:
            messages: 消息列表
            tools: OpenAI tools 参数 (来自 ToolRegistry.export_openai_tools)
            temperature: 采样温度
            max_tokens: 最大 token
            tool_choice: auto / none / required / {type:function,function:{name:...}}

        Returns:
            {"content": Optional[str], "tool_calls": Optional[List[ToolCall]]}
        """
        client = self._ensure_client()
        model = self._get_model()

        # 转换消息
        msg_dicts = [m.to_openai_dict() for m in messages]

        # 构造请求参数
        req_kwargs: Dict[str, Any] = {
            "model": model,
            "messages": msg_dicts,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            req_kwargs["tools"] = tools
            req_kwargs["tool_choice"] = tool_choice

        try:
            resp = await client.chat.completions.create(**req_kwargs)
        except Exception as e:
            logger.error(f"LLM 调用失败: {e}")
            raise LLMAdapterError(f"LLM 调用失败: {e}") from e

        choice = resp.choices[0]
        msg = choice.message
        content = msg.content

        # 解析 tool_calls
        tool_calls: Optional[List[ToolCall]] = None
        raw_tc = getattr(msg, "tool_calls", None)
        if raw_tc:
            tool_calls = [ToolCall.from_openai_dict(tc.model_dump() if hasattr(tc, "model_dump") else tc) for tc in raw_tc]

        return {
            "content": content,
            "tool_calls": tool_calls,
        }

    async def generate(
        self,
        messages: List[Message],
        temperature: float = 0.7,
        max_tokens: int = 1024,
        **kwargs,
    ) -> str:
        """普通生成 (无工具)"""
        r = await self.generate_with_tools(
            messages, tools=None, temperature=temperature, max_tokens=max_tokens
        )
        return r["content"] or ""

    async def stream_generate(
        self,
        messages: List[Message],
        temperature: float = 0.7,
        max_tokens: int = 1024,
        **kwargs,
    ):
        """流式生成 (无工具, 按字符 yield)"""
        client = self._ensure_client()
        model = self._get_model()
        msg_dicts = [m.to_openai_dict() for m in messages]

        try:
            stream = await client.chat.completions.create(
                model=model,
                messages=msg_dicts,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
            )
            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except Exception as e:
            logger.error(f"LLM 流式调用失败: {e}")
            raise LLMAdapterError(f"LLM 流式调用失败: {e}") from e


# ----------------------------------------------------------------------
# 全局适配器工厂
# ----------------------------------------------------------------------

_adapter_instance: Any = None
_adapter_lock = threading.Lock()


def _is_test_mode() -> bool:
    """检测是否为测试模式"""
    return (
        os.environ.get("YHLZ_TEST_MODE", "false").lower() == "true"
        or os.environ.get("YHLZ_AGENT_TEST_MODE", "false").lower() == "true"
    )


def _has_api_key() -> bool:
    """检测是否配置了 API key"""
    try:
        from backend.config import config
        if config.api_provider == "dashscope":
            return bool(config.dashscope_api_key)
        return bool(config.deepseek_api_key)
    except Exception:
        return False


def get_adapter() -> Any:
    """获取全局 LLM 适配器

    策略:
        - TEST_MODE=true 或 无 API key → MockLLMAdapter
        - 否则 → LLMAdapter (真实)
    """
    global _adapter_instance
    if _adapter_instance is not None:
        return _adapter_instance
    with _adapter_lock:
        if _adapter_instance is not None:
            return _adapter_instance
        if _is_test_mode() or not _has_api_key():
            logger.info("Agent LLM 适配器: 使用 Mock 模式 (TEST_MODE 或无 API key)")
            _adapter_instance = MockLLMAdapter()
        else:
            logger.info("Agent LLM 适配器: 使用真实模式")
            _adapter_instance = LLMAdapter()
        return _adapter_instance


def set_adapter(adapter: Any) -> None:
    """显式设置适配器 (测试用)"""
    global _adapter_instance
    with _adapter_lock:
        _adapter_instance = adapter


def reset_adapter() -> None:
    """重置全局适配器 (测试用)"""
    global _adapter_instance
    with _adapter_lock:
        _adapter_instance = None


__all__ = [
    "LLMAdapter", "LLMAdapterError", "MockLLMAdapter",
    "get_adapter", "set_adapter", "reset_adapter",
]
