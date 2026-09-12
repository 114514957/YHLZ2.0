"""
YHLZ Personality Engine V3.4 - Agent 工具注册

职责:
    - 将人格风格能力封装为 Agent 可调用的工具
    - 注册到 Agent ToolRegistry (不修改 Agent Core 代码)
    - 通过 register_personality_tools() 在 main.py 启动时显式调用

工具列表:
    - get_personality_style: 获取当前人格的风格指令 (供 LLM 调整语气 / 用词)

设计原则:
    - 工具 handler 内部调用 PersonalityService
    - 不直接调用底层 Store
    - 输出标准化字符串 (进入 LLM 上下文)
    - 权限由 PersonalityService 内部 PermissionChecker 校验
    - 失败返回 JSON 错误字符串 (不抛异常)
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


def _tool_get_personality_style(params: Dict[str, Any]) -> str:
    """工具: 获取当前人格风格指令

    参数:
        include_context: 可选, 是否包含人格档案上下文 (默认 False, 仅返回风格指令)
    """
    try:
        from backend.personality.service import get_service

        svc = get_service()
        include_context = bool(params.get("include_context", False))
        if include_context:
            context = svc.build_persona_context()
            if not context:
                return json.dumps({
                    "success": False,
                    "error": "人格功能未开启或无可用人格 (personality_enabled=False)",
                    "status": "denied",
                }, ensure_ascii=False)
            return json.dumps({
                "success": True,
                "context": context,
            }, ensure_ascii=False)

        result = svc.personality_style()
        if not result.success:
            return json.dumps({
                "success": False,
                "error": result.error,
                "status": result.status,
            }, ensure_ascii=False)
        return json.dumps({
            "success": True,
            "profile_id": result.profile_id,
            "profile_name": result.profile_name,
            "style": result.style,
            "latency_ms": round(result.latency_ms, 2),
        }, ensure_ascii=False)
    except Exception as e:
        logger.error(f"get_personality_style 工具异常: {e}", exc_info=True)
        return json.dumps({
            "success": False,
            "error": f"工具异常: {type(e).__name__}: {e}",
        }, ensure_ascii=False)


# 工具元数据
PERSONALITY_TOOL_NAMES = ["get_personality_style"]


def register_personality_tools(override: bool = True) -> int:
    """注册人格工具到 Agent ToolRegistry

    在 main.py 启动时调用一次即可。重复调用安全 (override=True)。

    Args:
        override: 是否覆盖同名工具 (默认 True, 便于热重载)

    Returns:
        成功注册的工具数
    """
    from backend.agent.tool_registry import get_registry

    reg = get_registry()
    count = 0

    reg.register_function(
        name="get_personality_style",
        description=(
            "获取当前 YHLZ 人格的风格指令 (语气 / 用词 / 行为准则)。"
            "适用于需要了解自身人设、调整回答风格、或检查人格是否启用时。"
            "需要权限: personality_enabled。"
        ),
        handler=_tool_get_personality_style,
        parameters={
            "type": "object",
            "properties": {
                "include_context": {
                    "type": "boolean",
                    "description": "可选, 是否包含完整人格档案上下文 (名称/描述/风格指令), 默认 False",
                },
            },
            "required": [],
        },
        category="personality",
        override=override,
    )
    count += 1

    logger.info(f"已注册 {count} 个人格工具: {PERSONALITY_TOOL_NAMES}")
    return count


def unregister_personality_tools() -> int:
    """注销人格工具 (测试用)"""
    from backend.agent.tool_registry import get_registry
    reg = get_registry()
    n = 0
    for name in PERSONALITY_TOOL_NAMES:
        if reg.unregister(name) is not None:
            n += 1
    return n


__all__ = [
    "register_personality_tools",
    "unregister_personality_tools",
    "PERSONALITY_TOOL_NAMES",
]
