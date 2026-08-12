"""
YHLZ Agent Core V3.0 - 工具执行器

职责:
    - 执行 ToolCall, 隔离异常 (单工具失败不影响 Agent 主流程)
    - 参数 schema 校验 (必填字段/类型检查)
    - 执行超时控制 (基于线程, 避免 LLM 卡死)
    - 输出标准化 (字符串化, 截断超长输出)
    - 延迟统计
"""
from __future__ import annotations

import json
import logging
import threading
import time
import traceback
from typing import Any, Dict, List, Optional

from backend.agent.schemas import Tool, ToolCall, ToolResult
from backend.agent.tool_registry import ToolRegistry, get_registry

logger = logging.getLogger(__name__)


class ToolExecutorError(Exception):
    """工具执行器错误"""


def _validate_arguments(tool: Tool, arguments: Dict[str, Any]) -> Optional[str]:
    """校验参数 (轻量, 仅检查 required 和基本类型)

    Returns:
        None 表示通过, 否则返回错误描述
    """
    schema = tool.parameters
    # 必填字段
    for req in schema.required:
        if req not in arguments:
            return f"缺少必填参数: {req}"
    # 基本类型检查
    type_map = {
        "string": str, "number": (int, float), "integer": int,
        "boolean": bool, "object": dict, "array": list,
    }
    for name, value in arguments.items():
        spec = schema.properties.get(name)
        if spec is None:
            continue  # 未声明的参数, 放行
        expected = spec.get("type")
        if expected and expected in type_map:
            py_type = type_map[expected]
            # number 兼容 int/float
            if expected == "number" and isinstance(value, bool):
                return f"参数 {name} 应为 number, 实际 bool"
            if expected == "integer" and isinstance(value, bool):
                return f"参数 {name} 应为 integer, 实际 bool"
            if not isinstance(value, py_type):
                return f"参数 {name} 应为 {expected}, 实际 {type(value).__name__}"
    return None


def _stringify_output(value: Any, max_len: int = 4000) -> str:
    """将工具输出标准化为字符串"""
    if value is None:
        return ""
    if isinstance(value, str):
        text = value
    elif isinstance(value, (dict, list)):
        try:
            text = json.dumps(value, ensure_ascii=False, default=str)
        except Exception:
            text = str(value)
    else:
        text = str(value)
    if len(text) > max_len:
        text = text[:max_len] + f"\n...(已截断, 原始长度 {len(text)})"
    return text


class ToolExecutor:
    """工具执行器

    用法:
        executor = ToolExecutor(registry)
        result = executor.execute(tool_call)
    """

    def __init__(
        self,
        registry: Optional[ToolRegistry] = None,
        default_timeout: float = 10.0,
        max_output_len: int = 4000,
    ):
        self._registry = registry or get_registry()
        self._default_timeout = default_timeout
        self._max_output_len = max_output_len

    def execute(
        self,
        tool_call: ToolCall,
        timeout: Optional[float] = None,
    ) -> ToolResult:
        """执行单个工具调用

        Args:
            tool_call: 工具调用
            timeout: 超时秒数 (None 用默认值)
        """
        start = time.perf_counter()
        ts = timeout or self._default_timeout

        # 查找工具
        tool = self._registry.get(tool_call.name)
        if tool is None:
            return ToolResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                output=f"工具不存在: {tool_call.name}",
                is_error=True,
                latency_ms=0.0,
            )
        if tool.handler is None:
            return ToolResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                output=f"工具无 handler: {tool_call.name}",
                is_error=True,
                latency_ms=0.0,
            )

        # 参数校验
        err = _validate_arguments(tool, tool_call.arguments)
        if err is not None:
            return ToolResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                output=f"参数校验失败: {err}",
                is_error=True,
                latency_ms=(time.perf_counter() - start) * 1000,
            )

        # 执行 (带超时)
        result_holder: Dict[str, Any] = {}

        def _run():
            try:
                ret = tool.handler(tool_call.arguments)  # type: ignore
                result_holder["ok"] = ret
            except Exception as e:
                result_holder["err"] = f"{type(e).__name__}: {e}"
                result_holder["traceback"] = traceback.format_exc()

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        t.join(timeout=ts)

        latency_ms = (time.perf_counter() - start) * 1000

        if t.is_alive():
            # 超时
            logger.warning(f"工具执行超时 ({ts}s): {tool_call.name}")
            return ToolResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                output=f"工具执行超时 ({ts}s)",
                is_error=True,
                latency_ms=latency_ms,
            )

        if "err" in result_holder:
            logger.error(f"工具执行异常 {tool_call.name}: {result_holder['err']}")
            return ToolResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                output=f"执行异常: {result_holder['err']}",
                is_error=True,
                latency_ms=latency_ms,
            )

        output = _stringify_output(result_holder.get("ok"), self._max_output_len)
        return ToolResult(
            tool_call_id=tool_call.id,
            name=tool_call.name,
            output=output,
            is_error=False,
            latency_ms=latency_ms,
        )

    def execute_batch(self, tool_calls: List[ToolCall]) -> List[ToolResult]:
        """批量执行 (顺序执行, 不并行, 避免 LLM 工具间依赖问题)"""
        return [self.execute(tc) for tc in tool_calls]


# 全局执行器单例
_executor_instance: Optional[ToolExecutor] = None
_executor_lock = threading.Lock()


def get_executor() -> ToolExecutor:
    """获取全局工具执行器"""
    global _executor_instance
    if _executor_instance is None:
        with _executor_lock:
            if _executor_instance is None:
                _executor_instance = ToolExecutor()
    return _executor_instance


def execute_tool(tool_call: ToolCall, timeout: Optional[float] = None) -> ToolResult:
    """便捷函数: 执行单个工具调用"""
    return get_executor().execute(tool_call, timeout=timeout)


def reset_executor() -> None:
    """重置全局执行器 (测试用)"""
    global _executor_instance
    with _executor_lock:
        _executor_instance = None


__all__ = [
    "ToolExecutor", "ToolExecutorError",
    "execute_tool", "get_executor", "reset_executor",
]
