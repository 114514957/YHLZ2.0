"""
YHLZ Vision Action V1.0 - 行动规划器

职责:
    - 理解结果 → 行动建议 (Vision Understanding → Action Suggestion)
    - 规则驱动: 依据 scene_type / description / subjects 生成建议行动
    - 供 Agent / API 使用 (P1: Vision Action Integration)

设计原则:
    - 只生成建议 (ActionRequest 模板), 不执行
    - 权限判定由 Service 层负责 (规划器不触碰权限)
    - 鸭子类型: 接收含 scene_type / description 字段的对象或 dict
    - 不依赖 vision.understanding 具体实现 (自包含)
"""
from __future__ import annotations

from typing import Any, Dict, List

from backend.action.schema import ActionRequest, ActionType, RiskLevel

# 错误 / 异常场景关键词 → 建议检查日志
ERROR_SIGNAL_KEYWORDS = [
    "error", "failed", "fail", "exception", "timeout", "crash", "异常",
    "错误", "失败", "报错", "超时", "崩溃", "连接失败",
]

# 登录 / 权限场景关键词
LOGIN_SIGNAL_KEYWORDS = [
    "login", "sign in", "auth", "登录", "登陆", "验证码", "授权",
]

# 任务 / 文档场景关键词
TASK_SIGNAL_KEYWORDS = [
    "task", "report", "document", "总结", "报告", "任务", "文档", "计划",
]


def _attr(obj: Any, name: str, default: Any = "") -> Any:
    """兼容对象 / dict 的属性读取"""
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def suggest_actions(understanding_result: Any) -> List[ActionRequest]:
    """从理解结果生成行动建议

    Args:
        understanding_result: UnderstandingResult 对象或 dict
            (需含 scene_type / description / subjects / summary 字段)

    Returns:
        建议行动列表 (不执行, 由调用方决定是否请求授权)
    """
    scene_type = str(_attr(understanding_result, "scene_type", "")).lower()
    description = str(_attr(understanding_result, "description", ""))
    summary = str(_attr(understanding_result, "summary", ""))
    subjects = list(_attr(understanding_result, "subjects", []) or [])
    if isinstance(subjects, str):
        subjects = [subjects]

    text = " ".join([description, summary, " ".join(subjects)]).lower()
    suggestions: List[ActionRequest] = []

    # 1. 错误 / 异常场景 → 检查日志 (中风险, 需确认前先检查)
    if scene_type in ("error", "warning", "crash") or any(
        kw in text for kw in ERROR_SIGNAL_KEYWORDS
    ):
        suggestions.append(ActionRequest.create(
            action_type=ActionType.CHECK.value,
            target="logs",
            parameters={"scope": "recent"},
            reason="检测到错误/异常信号, 建议检查最近日志定位问题",
            confidence=0.8,
            risk_level=RiskLevel.LOW.value,
        ))
        suggestions.append(ActionRequest.create(
            action_type=ActionType.REPORT.value,
            target="diagnosis",
            parameters={"type": "error_summary"},
            reason="基于异常信号生成诊断报告, 便于用户决策",
            confidence=0.6,
            risk_level=RiskLevel.LOW.value,
        ))

    # 2. 登录 / 授权场景 → 检查账户状态
    elif any(kw in text for kw in LOGIN_SIGNAL_KEYWORDS):
        suggestions.append(ActionRequest.create(
            action_type=ActionType.CHECK.value,
            target="account",
            parameters={"scope": "auth_status"},
            reason="检测到登录/授权场景, 建议检查账户状态",
            confidence=0.7,
            risk_level=RiskLevel.MEDIUM.value,
        ))

    # 3. 任务 / 文档场景 → 生成报告
    elif any(kw in text for kw in TASK_SIGNAL_KEYWORDS):
        suggestions.append(ActionRequest.create(
            action_type=ActionType.REPORT.value,
            target="task_summary",
            parameters={"source": scene_type},
            reason="检测到任务/文档场景, 建议生成任务总结报告",
            confidence=0.6,
            risk_level=RiskLevel.LOW.value,
        ))

    # 4. 网页场景 → 保持观察 (无默认行动)
    # (scene_type == "web" 且无异常信号时不给建议, 避免干扰)

    return suggestions


__all__ = ["suggest_actions"]
