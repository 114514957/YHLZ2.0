"""
YHLZ Embodied AI V4.2 - 具身 Agent 工具注册 (Environment Reasoning Layer)

职责:
    - 将环境查询 / 推理能力封装为 Agent 可调用的工具 (只读)
    - 注册到 Agent ToolRegistry (不修改 Agent Core 代码)
    - 通过 register_embodied_tools() 在 main.py 启动时显式调用

工具列表:
    - query_environment_state:     查询当前环境状态 (V4.1, 只读)
    - query_environment_events:    查询环境事件历史 (V4.2, 只读)
    - predict_environment_change:  预测动作结果 (V4.2, 只预测不执行)

设计原则:
    - 工具 handler 内部调用 EmbodiedService (只读查询, 不执行动作)
    - 不直接触碰 Manager / 环境内部
    - 输出标准化字符串 (进入 LLM 上下文)
    - 只读安全: 不提供执行动作的工具
    - 预测工具只输出预期, 绝不执行 (必须经 Permission → Executor)
    - 失败返回 JSON 错误字符串 (不抛异常)
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


def _tool_query_environment_state(params: Dict[str, Any]) -> str:
    """工具: 查询当前环境状态

    参数:
        environment: 可选, 环境名 (默认: 默认环境)
        include_changes: 可选, 是否包含最近状态变化 (默认 true)
    """
    try:
        from backend.embodied.service import get_service

        svc = get_service()
        env_name = params.get("environment") or None
        include_changes = bool(params.get("include_changes", True))
        ctx = svc.build_environment_context(
            environment=env_name,
            include_history=include_changes,
        )
        return json.dumps(ctx, ensure_ascii=False)
    except Exception as e:
        logger.error(f"query_environment_state 工具异常: {e}", exc_info=True)
        return json.dumps({
            "success": False,
            "error": f"工具异常: {type(e).__name__}: {e}",
        }, ensure_ascii=False)


def _tool_query_environment_events(params: Dict[str, Any]) -> str:
    """工具: 查询环境事件历史 (时间线)

    参数:
        limit: 可选, 返回条数 (默认 20)
        event_type: 可选, 事件类型过滤 (action / object_change / move / failure / ...)
        result: 可选, 结果过滤 (success / failure / no_change / partial)
    """
    try:
        from backend.embodied.service import get_service

        svc = get_service()
        limit = int(params.get("limit", 20))
        limit = max(1, min(limit, 100))
        event_type = params.get("event_type") or None
        result = params.get("result") or None
        events = svc.event_history(
            limit=limit, event_type=event_type, result=result,
        )
        return json.dumps({
            "success": True,
            "count": len(events),
            "events": events,
            "event_stats": svc.event_stats(),
        }, ensure_ascii=False)
    except Exception as e:
        logger.error(f"query_environment_events 工具异常: {e}", exc_info=True)
        return json.dumps({
            "success": False,
            "error": f"工具异常: {type(e).__name__}: {e}",
        }, ensure_ascii=False)


def _tool_predict_environment_change(params: Dict[str, Any]) -> str:
    """工具: 预测动作序列对环境的预期影响 (只预测, 不执行)

    参数:
        actions: 动作序列 (List[Dict], 如 [{'action_type': 'move', 'parameters': {'dx': 1, 'dy': 0}}, {'action_type': 'pick', 'target': 'lamp'}])
        environment: 可选, 环境名 (默认: 默认环境)
    """
    try:
        from backend.embodied.schema import EmbodiedAction
        from backend.embodied.service import get_service

        svc = get_service()
        actions_raw = params.get("actions") or []
        if not isinstance(actions_raw, list) or not actions_raw:
            return json.dumps({
                "success": False,
                "error": "参数 actions 必须为非空动作序列",
            }, ensure_ascii=False)
        actions: List[EmbodiedAction] = []
        for a in actions_raw[:10]:
            actions.append(EmbodiedAction.create(
                action_type=a.get("action_type", "custom"),
                target=a.get("target", ""),
                parameters=a.get("parameters") or {},
                intent=a.get("intent", ""),
            ))
        pred = svc.predict_sequence(
            actions, environment=params.get("environment") or None,
        )
        if pred is None:
            return json.dumps({
                "success": False,
                "error": "预测不可用: 预测器禁用或环境无状态",
            }, ensure_ascii=False)
        return json.dumps({
            "success": True,
            "prediction": pred.to_dict(),
            "note": "只预测不执行: 实际执行必须经权限与确认流程",
        }, ensure_ascii=False)
    except Exception as e:
        logger.error(f"predict_environment_change 工具异常: {e}", exc_info=True)
        return json.dumps({
            "success": False,
            "error": f"工具异常: {type(e).__name__}: {e}",
        }, ensure_ascii=False)


# 工具元数据
EMBODIED_TOOL_NAMES = [
    "query_environment_state",
    "query_environment_events",
    "predict_environment_change",
]


def register_embodied_tools(override: bool = True) -> int:
    """注册具身工具到 Agent ToolRegistry

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
        name="query_environment_state",
        description=(
            "查询 YHLZ 具身智能环境状态 (只读)。"
            "返回当前环境状态: 对象列表 / 主体位置 / 环境条件 / 对象关系 / 最近状态变化 / "
            "事件摘要 / 失败因果分析 / 预测置信度 / 经验摘要 (失败模式与成功率趋势)。"
            "适用于 Agent 需要了解环境信息时 (如'环境里有什么' / '台灯在哪' / '上次移动结果如何')。"
            "只读工具, 不会执行任何动作。"
        ),
        handler=_tool_query_environment_state,
        parameters={
            "type": "object",
            "properties": {
                "environment": {
                    "type": "string",
                    "description": "可选, 环境名 (默认: 默认环境)",
                },
                "include_changes": {
                    "type": "boolean",
                    "description": "可选, 是否包含最近状态变化 (默认 true)",
                },
            },
        },
        category="embodied",
        override=override,
    )
    count += 1

    reg.register_function(
        name="query_environment_events",
        description=(
            "查询 YHLZ 环境事件历史时间线 (只读)。"
            "返回环境事件: 动作记录 / 结果记录 / 对象变化 / 主体位置 / 失败因果, 最新在前。"
            "适用于 Agent 需要了解'过去发生了什么 / 为什么失败'时 "
            "(如'刚才移动失败的原因' / '环境发生过什么变化')。"
            "只读工具, 不会执行任何动作。"
        ),
        handler=_tool_query_environment_events,
        parameters={
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "可选, 返回条数 (1~100, 默认 20)",
                },
                "event_type": {
                    "type": "string",
                    "description": "可选, 事件类型过滤: action / object_change / move / reset / observe / failure / system",
                },
                "result": {
                    "type": "string",
                    "description": "可选, 结果过滤: success / failure / no_change / partial",
                },
            },
        },
        category="embodied",
        override=override,
    )
    count += 1

    reg.register_function(
        name="predict_environment_change",
        description=(
            "预测 YHLZ 环境动作序列的预期影响 (只预测, 不执行)。"
            "输入动作序列 (move/pick/place/scan 等), 返回逐步预期 + 最终预期 + 状态不变式检测结果。"
            "例如 [move(dx=1), pick(lamp)] → lamp 将变为 held。"
            "适用于 Agent 在规划阶段评估动作后果 (如'如果我去拿台灯会怎样')。"
            "注意: 该工具只做预测, 实际执行必须通过权限与确认流程。"
        ),
        handler=_tool_predict_environment_change,
        parameters={
            "type": "object",
            "properties": {
                "actions": {
                    "type": "array",
                    "description": "动作序列 (最多 10 步), 每项: {'action_type': 'move'|'pick'|'place'|'scan'|'inspect', 'target': 对象名, 'parameters': {'dx': 1, 'dy': 0} / {'object': 'lamp'}}",
                    "items": {"type": "object"},
                },
                "environment": {
                    "type": "string",
                    "description": "可选, 环境名 (默认: 默认环境)",
                },
            },
            "required": ["actions"],
        },
        category="embodied",
        override=override,
    )
    count += 1

    logger.info(f"已注册 {count} 个具身工具: {EMBODIED_TOOL_NAMES}")
    return count


def unregister_embodied_tools() -> int:
    """注销具身工具 (测试用)"""
    from backend.agent.tool_registry import get_registry
    reg = get_registry()
    n = 0
    for name in EMBODIED_TOOL_NAMES:
        if reg.unregister(name) is not None:
            n += 1
    return n


__all__ = [
    "register_embodied_tools",
    "unregister_embodied_tools",
    "EMBODIED_TOOL_NAMES",
]
