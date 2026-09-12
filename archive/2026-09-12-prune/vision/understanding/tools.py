"""
YHLZ Vision Understanding V1.0 - Agent 工具注册

职责:
    - 将视觉理解能力封装为 Agent 可调用的工具
    - 注册到 Agent ToolRegistry (不修改 Agent Core 代码)
    - 通过 register_understanding_tools() 在 main.py 启动时显式调用

工具列表:
    - describe_scene: 截屏并描述屏幕场景
    - answer_visual:  截屏并回答关于屏幕画面的问题

设计原则:
    - 工具 handler 内部调用 UnderstandingService
    - 不直接调用底层 Provider / Adapter
    - 输出标准化字符串 (进入 LLM 上下文)
    - 权限由 UnderstandingService 内部 PermissionChecker 校验
    - 失败返回 JSON 错误字符串 (不抛异常)
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


def _tool_describe_scene(params: Dict[str, Any]) -> str:
    """工具: 描述当前屏幕场景

    参数:
        region: 可选, 区域 {x, y, w, h} (None=全屏)
        language: 可选, 输出语言 (默认 'zh')
    """
    try:
        from backend.vision.understanding.service import get_service
        svc = get_service()
        region = params.get("region")
        language = params.get("language", "zh")
        result = svc.capture_screen_and_understand(
            mode="describe",
            region=region,
            language=language,
        )
        if not result.is_ok:
            return json.dumps({
                "success": False,
                "error": result.error,
                "status": result.status,
            }, ensure_ascii=False)
        return json.dumps({
            "success": True,
            "scene_type": result.scene_type,
            "summary": result.summary,
            "description": result.description,
            "subjects": [s.to_dict() for s in result.subjects],
            "confidence": round(result.confidence, 4),
            "processing_time_ms": round(result.processing_time * 1000, 2),
        }, ensure_ascii=False)
    except Exception as e:
        logger.error(f"describe_scene 工具异常: {e}", exc_info=True)
        return json.dumps({
            "success": False,
            "error": f"工具异常: {type(e).__name__}: {e}",
        }, ensure_ascii=False)


def _tool_answer_visual(params: Dict[str, Any]) -> str:
    """工具: 回答关于屏幕画面的问题

    参数:
        question: 必填, 用户问题
        region: 可选, 区域 {x, y, w, h} (None=全屏)
        language: 可选, 输出语言 (默认 'zh')
    """
    try:
        from backend.vision.understanding.service import get_service
        svc = get_service()
        question = params.get("question")
        if not question:
            return json.dumps({
                "success": False,
                "error": "缺少必填参数 question",
            }, ensure_ascii=False)
        region = params.get("region")
        language = params.get("language", "zh")
        result = svc.capture_screen_and_understand(
            mode="qa",
            region=region,
            language=language,
            question=question,
        )
        if not result.is_ok:
            return json.dumps({
                "success": False,
                "error": result.error,
                "status": result.status,
            }, ensure_ascii=False)
        return json.dumps({
            "success": True,
            "answer": result.summary,
            "detail": result.description,
            "scene_type": result.scene_type,
            "subjects": [s.to_dict() for s in result.subjects],
            "processing_time_ms": round(result.processing_time * 1000, 2),
        }, ensure_ascii=False)
    except Exception as e:
        logger.error(f"answer_visual 工具异常: {e}", exc_info=True)
        return json.dumps({
            "success": False,
            "error": f"工具异常: {type(e).__name__}: {e}",
        }, ensure_ascii=False)


# 工具元数据
UNDERSTANDING_TOOL_NAMES = ["describe_scene", "answer_visual"]


def register_understanding_tools(override: bool = True) -> int:
    """注册视觉理解工具到 Agent ToolRegistry

    在 main.py 启动时调用一次即可。重复调用安全 (override=True)。

    Args:
        override: 是否覆盖同名工具 (默认 True, 便于热重载)

    Returns:
        成功注册的工具数
    """
    from backend.agent.tool_registry import get_registry

    reg = get_registry()
    count = 0

    # describe_scene
    reg.register_function(
        name="describe_scene",
        description=(
            "截取当前屏幕并理解画面内容, 返回场景描述 (场景类型、主体、环境信息)。"
            "适用于用户询问'屏幕上是什么'、'当前在做什么'等场景。"
            "需要权限: understanding_enabled + screen_enabled。"
        ),
        handler=_tool_describe_scene,
        parameters={
            "type": "object",
            "properties": {
                "region": {
                    "type": "object",
                    "description": "可选, 截屏区域 {x, y, w, h} (像素)。省略则全屏。",
                    "properties": {
                        "x": {"type": "integer", "description": "左上角 x"},
                        "y": {"type": "integer", "description": "左上角 y"},
                        "w": {"type": "integer", "description": "宽度"},
                        "h": {"type": "integer", "description": "高度"},
                    },
                },
                "language": {
                    "type": "string",
                    "description": "输出语言 (zh / en), 默认 zh",
                },
            },
            "required": [],
        },
        category="vision",
        override=override,
    )
    count += 1

    # answer_visual
    reg.register_function(
        name="answer_visual",
        description=(
            "截取当前屏幕并回答关于屏幕画面内容的问题 (视觉问答)。"
            "适用于用户询问屏幕上的具体内容, 如'屏幕上显示什么'、'看到了什么窗口'。"
            "需要权限: understanding_enabled + screen_enabled。"
        ),
        handler=_tool_answer_visual,
        parameters={
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "用户关于屏幕画面内容的问题",
                },
                "region": {
                    "type": "object",
                    "description": "可选, 截屏区域 {x, y, w, h} (像素)",
                    "properties": {
                        "x": {"type": "integer", "description": "左上角 x"},
                        "y": {"type": "integer", "description": "左上角 y"},
                        "w": {"type": "integer", "description": "宽度"},
                        "h": {"type": "integer", "description": "高度"},
                    },
                },
                "language": {
                    "type": "string",
                    "description": "输出语言 (zh / en), 默认 zh",
                },
            },
            "required": ["question"],
        },
        category="vision",
        override=override,
    )
    count += 1

    logger.info(f"已注册 {count} 个视觉理解工具: {UNDERSTANDING_TOOL_NAMES}")
    return count


def unregister_understanding_tools() -> int:
    """注销视觉理解工具 (测试用)"""
    from backend.agent.tool_registry import get_registry
    reg = get_registry()
    n = 0
    for name in UNDERSTANDING_TOOL_NAMES:
        if reg.unregister(name) is not None:
            n += 1
    return n


__all__ = [
    "register_understanding_tools",
    "unregister_understanding_tools",
    "UNDERSTANDING_TOOL_NAMES",
]
