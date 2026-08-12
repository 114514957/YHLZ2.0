"""
YHLZ Vision Perception V1.0 - Agent 工具注册

职责:
    - 将感知能力封装为 Agent 可调用的工具
    - 注册到 Agent ToolRegistry (不修改 Agent Core 代码)
    - 通过 register_vision_tools() 在 main.py 启动时显式调用

工具列表:
    - read_screen_text: 截屏并 OCR 识别屏幕文字
    - detect_objects:    截屏并检测屏幕上的对象

设计原则:
    - 工具 handler 内部调用 PerceptionService
    - 不直接调用底层 Provider / Adapter
    - 输出标准化字符串 (进入 LLM 上下文)
    - 权限由 PerceptionService 内部 PermissionChecker 校验
    - 失败返回 JSON 错误字符串 (不抛异常)
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def _tool_read_screen_text(params: Dict[str, Any]) -> str:
    """工具: 读取屏幕文字

    参数:
        region: 可选, 区域 {x, y, w, h} (None=全屏)
        language: 可选, OCR 期望语言 (默认 'zh')
    """
    try:
        from backend.vision.perception.service import get_service
        svc = get_service()
        region = params.get("region")
        language = params.get("language", "zh")
        result = svc.capture_screen_and_perceive(
            mode="ocr",
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
            "text_count": len(result.text),
            "text": result.text_content,
            "items": [t.to_dict() for t in result.text],
            "confidence": round(result.confidence, 4),
            "processing_time_ms": round(result.processing_time * 1000, 2),
        }, ensure_ascii=False)
    except Exception as e:
        logger.error(f"read_screen_text 工具异常: {e}", exc_info=True)
        return json.dumps({
            "success": False,
            "error": f"工具异常: {type(e).__name__}: {e}",
        }, ensure_ascii=False)


def _tool_detect_objects(params: Dict[str, Any]) -> str:
    """工具: 检测屏幕上的对象

    参数:
        region: 可选, 区域 {x, y, w, h} (None=全屏)
        min_confidence: 可选, 最小置信度 (默认 0.3)
        max_objects: 可选, 最大返回数 (默认 20)
    """
    try:
        from backend.vision.perception.service import get_service
        svc = get_service()
        region = params.get("region")
        min_conf = float(params.get("min_confidence", 0.3))
        max_objects = int(params.get("max_objects", 20))
        result = svc.capture_screen_and_perceive(
            mode="detection",
            region=region,
        )
        if not result.is_ok:
            return json.dumps({
                "success": False,
                "error": result.error,
                "status": result.status,
            }, ensure_ascii=False)
        # 应用 min_confidence 过滤
        objects = [o for o in result.objects if o.confidence >= min_conf]
        objects = objects[:max_objects]
        return json.dumps({
            "success": True,
            "object_count": len(objects),
            "objects": [o.to_dict() for o in objects],
            "processing_time_ms": round(result.processing_time * 1000, 2),
        }, ensure_ascii=False)
    except Exception as e:
        logger.error(f"detect_objects 工具异常: {e}", exc_info=True)
        return json.dumps({
            "success": False,
            "error": f"工具异常: {type(e).__name__}: {e}",
        }, ensure_ascii=False)


# 工具元数据
VISION_TOOL_NAMES = ["read_screen_text", "detect_objects"]


def register_vision_tools(override: bool = True) -> int:
    """注册视觉感知工具到 Agent ToolRegistry

    在 main.py 启动时调用一次即可。重复调用安全 (override=True)。

    Args:
        override: 是否覆盖同名工具 (默认 True, 便于热重载)

    Returns:
        成功注册的工具数
    """
    from backend.agent.tool_registry import get_registry

    reg = get_registry()
    count = 0

    # read_screen_text
    reg.register_function(
        name="read_screen_text",
        description=(
            "截取当前屏幕并使用 OCR 识别屏幕上的文字。"
            "适用于读取屏幕显示的文本内容 (如窗口标题、菜单、按钮文字等)。"
            "需要权限: perception_enabled + ocr_enabled + screen_enabled。"
        ),
        handler=_tool_read_screen_text,
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
                    "description": "期望语言 (zh / en / mixed), 默认 zh",
                },
            },
            "required": [],
        },
        category="vision",
        override=override,
    )
    count += 1

    # detect_objects
    reg.register_function(
        name="detect_objects",
        description=(
            "截取当前屏幕并检测屏幕上的对象 (人物、物品、窗口元素等)。"
            "返回对象名、类别、位置和置信度。"
            "需要权限: perception_enabled + detection_enabled + screen_enabled。"
        ),
        handler=_tool_detect_objects,
        parameters={
            "type": "object",
            "properties": {
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
                "min_confidence": {
                    "type": "number",
                    "description": "最小置信度阈值 (0.0~1.0), 默认 0.3",
                },
                "max_objects": {
                    "type": "integer",
                    "description": "最大返回对象数, 默认 20",
                },
            },
            "required": [],
        },
        category="vision",
        override=override,
    )
    count += 1

    logger.info(f"已注册 {count} 个视觉感知工具: {VISION_TOOL_NAMES}")
    return count


def unregister_vision_tools() -> int:
    """注销视觉感知工具 (测试用)"""
    from backend.agent.tool_registry import get_registry
    reg = get_registry()
    n = 0
    for name in VISION_TOOL_NAMES:
        if reg.unregister(name) is not None:
            n += 1
    return n


__all__ = [
    "register_vision_tools",
    "unregister_vision_tools",
    "VISION_TOOL_NAMES",
]
