"""
YHLZ Vision Action V1.0 - Agent 工具注册

职责:
    - 将行动请求能力封装为 Agent 可调用的工具
    - 注册到 Agent ToolRegistry (不修改 Agent Core 代码)
    - 通过 register_action_tools() 在 main.py 启动时显式调用

工具列表:
    - request_action: 提交行动请求 (需权限, 高风险需确认)

设计原则:
    - 工具 handler 内部调用 ActionService
    - 不直接触碰 Executor / 系统接口
    - 输出标准化字符串 (进入 LLM 上下文)
    - 权限由 ActionService 内部 PermissionChecker 校验
    - 失败返回 JSON 错误字符串 (不抛异常)
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


def _tool_request_action(params: Dict[str, Any]) -> str:
    """工具: 提交行动请求

    参数:
        action_type: 行动类型 (open / navigate / check / query / report / execute / custom)
        target: 行动目标 (如 'logs' / 'account' / 'app:settings')
        parameters: 可选, 参数 dict
        reason: 行动理由 (必须说明为什么执行该行动)
        confidence: 可选, 置信度 (0.0 ~ 1.0)
        risk_level: 可选, 声明的风险等级 (low / medium / high)
        confirmed: 可选, 是否已确认 (高风险行动默认需确认)
    """
    try:
        from backend.action.schema import ActionRequest
        from backend.action.service import get_service

        svc = get_service()
        request = ActionRequest.create(
            action_type=params.get("action_type", "custom"),
            target=params.get("target", ""),
            parameters=params.get("parameters") or {},
            reason=params.get("reason", ""),
            confidence=float(params.get("confidence", 0.0)),
            risk_level=params.get("risk_level", "low"),
        )
        confirmed = bool(params.get("confirmed", False))
        op = svc.execute(request, confirmed=confirmed)
        return json.dumps(op.to_dict(), ensure_ascii=False)
    except Exception as e:
        logger.error(f"request_action 工具异常: {e}", exc_info=True)
        return json.dumps({
            "success": False,
            "error": f"工具异常: {type(e).__name__}: {e}",
        }, ensure_ascii=False)


# 工具元数据
ACTION_TOOL_NAMES = ["request_action"]


def register_action_tools(override: bool = True) -> int:
    """注册行动工具到 Agent ToolRegistry

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
        name="request_action",
        description=(
            "提交一个 YHLZ 行动请求 (如检查日志 / 生成报告 / 检查账户状态)。"
            "适用于用户请求 YHLZ 执行某个动作时, 先提交行动请求并获取权限评估结果。"
            "需要权限: action_enabled。高风险行动返回 awaiting_confirm, 需用户确认后携带 confirmed=true 重试。"
            "行动类型白名单: open / navigate / check / query / report / execute / custom。"
        ),
        handler=_tool_request_action,
        parameters={
            "type": "object",
            "properties": {
                "action_type": {
                    "type": "string",
                    "description": "行动类型: open / navigate / check / query / report / execute / custom",
                },
                "target": {
                    "type": "string",
                    "description": "行动目标 (如 'logs' / 'account' / 'app:settings')",
                },
                "parameters": {
                    "type": "object",
                    "description": "可选, 行动参数 dict",
                },
                "reason": {
                    "type": "string",
                    "description": "行动理由 (必须说明为什么执行该行动)",
                },
                "confidence": {
                    "type": "number",
                    "description": "可选, 置信度 (0.0 ~ 1.0)",
                },
                "risk_level": {
                    "type": "string",
                    "description": "可选, 声明的风险等级 (low / medium / high)",
                },
                "confirmed": {
                    "type": "boolean",
                    "description": "可选, 是否已获用户确认 (高风险行动默认需确认)",
                },
            },
            "required": ["action_type"],
        },
        category="action",
        override=override,
    )
    count += 1

    logger.info(f"已注册 {count} 个行动工具: {ACTION_TOOL_NAMES}")
    return count


def unregister_action_tools() -> int:
    """注销行动工具 (测试用)"""
    from backend.agent.tool_registry import get_registry
    reg = get_registry()
    n = 0
    for name in ACTION_TOOL_NAMES:
        if reg.unregister(name) is not None:
            n += 1
    return n


__all__ = [
    "register_action_tools",
    "unregister_action_tools",
    "ACTION_TOOL_NAMES",
]
