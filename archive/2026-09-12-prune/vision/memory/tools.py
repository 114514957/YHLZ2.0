"""
YHLZ Vision Memory V1.0 - Agent 工具注册

职责:
    - 将视觉记忆检索能力封装为 Agent 可调用的工具
    - 注册到 Agent ToolRegistry (不修改 Agent Core 代码)
    - 通过 register_vision_memory_tools() 在 main.py 启动时显式调用

工具列表:
    - search_visual_memory: 检索历史视觉记忆 (视觉经验查询)

设计原则:
    - 工具 handler 内部调用 MemoryService
    - 不直接调用底层 Store
    - 输出标准化字符串 (进入 LLM 上下文)
    - 权限由 MemoryService 内部 PermissionChecker 校验
    - 失败返回 JSON 错误字符串 (不抛异常)
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


def _tool_search_visual_memory(params: Dict[str, Any]) -> str:
    """工具: 检索历史视觉记忆

    参数:
        keyword: 可选, 关键词 (匹配描述文本)
        scene_type: 可选, 场景类型 (desktop / document / image / web / unknown)
        tag: 可选, 标签
        importance: 可选, 重要程度 (low / medium / high)
        limit: 可选, 返回数量上限 (默认 5)
    """
    try:
        from backend.vision.memory.service import get_service
        from backend.vision.memory.schema import MemoryQuery

        svc = get_service()
        limit = int(params.get("limit", 5))
        if limit <= 0:
            limit = 5
        query = MemoryQuery(
            keyword=params.get("keyword"),
            scene_type=params.get("scene_type"),
            tag=params.get("tag"),
            importance=params.get("importance"),
            limit=limit,
        )
        result = svc.query(query)
        if not result.success:
            return json.dumps({
                "success": False,
                "error": result.error,
                "status": result.status,
            }, ensure_ascii=False)
        if result.count == 0:
            return json.dumps({
                "success": True,
                "count": 0,
                "records": [],
                "note": "没有匹配的历史视觉记忆 (记忆需要先开启并保存, 保存由 Understanding 流程自动完成)",
            }, ensure_ascii=False)
        return json.dumps({
            "success": True,
            "count": result.count,
            "records": [r.to_dict() for r in result.records],
            "latency_ms": round(result.latency_ms, 2),
        }, ensure_ascii=False)
    except Exception as e:
        logger.error(f"search_visual_memory 工具异常: {e}", exc_info=True)
        return json.dumps({
            "success": False,
            "error": f"工具异常: {type(e).__name__}: {e}",
        }, ensure_ascii=False)


# 工具元数据
VISION_MEMORY_TOOL_NAMES = ["search_visual_memory"]


def register_vision_memory_tools(override: bool = True) -> int:
    """注册视觉记忆工具到 Agent ToolRegistry

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
        name="search_visual_memory",
        description=(
            "检索历史视觉记忆 (视觉经验), 返回与条件匹配的最近记忆记录。"
            "适用于用户询问'之前看到过什么'、'刚才屏幕上是什么'、'之前那个界面/代码/窗口是什么样'等场景。"
            "需要权限: vision_memory_enabled。"
        ),
        handler=_tool_search_visual_memory,
        parameters={
            "type": "object",
            "properties": {
                "keyword": {
                    "type": "string",
                    "description": "可选, 关键词 (匹配记忆描述文本)",
                },
                "scene_type": {
                    "type": "string",
                    "description": "可选, 场景类型 (desktop / document / image / web / game / unknown)",
                },
                "tag": {
                    "type": "string",
                    "description": "可选, 标签 (如主体名 / 关键词)",
                },
                "importance": {
                    "type": "string",
                    "description": "可选, 重要程度 (low / medium / high)",
                },
                "limit": {
                    "type": "integer",
                    "description": "可选, 返回数量上限, 默认 5, 最大 100",
                },
            },
            "required": [],
        },
        category="vision",
        override=override,
    )
    count += 1

    logger.info(f"已注册 {count} 个视觉记忆工具: {VISION_MEMORY_TOOL_NAMES}")
    return count


def unregister_vision_memory_tools() -> int:
    """注销视觉记忆工具 (测试用)"""
    from backend.agent.tool_registry import get_registry
    reg = get_registry()
    n = 0
    for name in VISION_MEMORY_TOOL_NAMES:
        if reg.unregister(name) is not None:
            n += 1
    return n


__all__ = [
    "register_vision_memory_tools",
    "unregister_vision_memory_tools",
    "VISION_MEMORY_TOOL_NAMES",
]
