"""
YHLZ Vision Action V1.0 - 行动请求校验

职责:
    - 行动请求字段级校验 (创建前)
    - 白名单: 行动类型 / 风险等级
    - 参数边界: 文本长度 / 坐标范围 / 频率
    - 不依赖执行器 (纯静态规则, 可独立测试)

设计原则:
    - 纯函数 (ActionValidator.validate)
    - 返回 (ok, errors) 不抛异常
    - 先校验后执行: Service 层在权限检查前调用
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Tuple

from backend.action.schema import ActionRequest, ActionType, RiskLevel

# 参数边界 (配置驱动前先内置安全默认值)
MAX_TEXT_LENGTH = 200          # 文本类参数最大长度
MAX_REASON_LENGTH = 500        # 理由最大长度
MAX_COORDINATE = 10000         # 坐标绝对值上限
MAX_PARAMETERS = 20            # 参数键数量上限


class ActionValidator:
    """行动请求校验器"""

    @staticmethod
    def validate(request: ActionRequest) -> Tuple[bool, List[str]]:
        """校验行动请求

        Returns:
            (True, []) 通过
            (False, errors) 不通过, errors 为错误描述列表
        """
        errors: List[str] = []

        # 1. 行动类型白名单
        if request.action_type not in ActionType.values():
            errors.append(f"action_type 不合法: {request.action_type} (可选: {ActionType.values()})")

        # 2. 目标非空 (打开 / 导航 / 执行 / 报告 必须指定)
        if not request.target or not request.target.strip():
            if request.action_type in (ActionType.OPEN.value, ActionType.NAVIGATE.value,
                                       ActionType.EXECUTE.value, ActionType.REPORT.value):
                errors.append(f"action_type={request.action_type} 必须指定 target")

        # 3. 置信度范围
        if not (0.0 <= request.confidence <= 1.0):
            errors.append(f"confidence 超出范围: {request.confidence} (应为 0.0~1.0)")

        # 4. 风险等级白名单
        if request.risk_level not in RiskLevel.values():
            errors.append(f"risk_level 不合法: {request.risk_level} (可选: {RiskLevel.values()})")

        # 5. 参数边界
        if not isinstance(request.parameters, dict):
            errors.append("parameters 必须是 dict")
        else:
            if len(request.parameters) > MAX_PARAMETERS:
                errors.append(f"parameters 键数量超出上限: {len(request.parameters)} > {MAX_PARAMETERS}")
            for key, value in request.parameters.items():
                if value is None:
                    continue
                if isinstance(value, str):
                    if len(value) > MAX_TEXT_LENGTH:
                        errors.append(f"参数 {key} 文本长度超出上限 ({MAX_TEXT_LENGTH})")
                    if "text" == key and not value.strip():
                        errors.append("参数 text 不能为空")
                elif isinstance(value, (int, float)):
                    if key in ("x", "y") and abs(float(value)) > MAX_COORDINATE:
                        errors.append(f"参数 {key} 坐标超出范围 (±{MAX_COORDINATE})")
                elif isinstance(value, (list, dict)):
                    # 不允许嵌套引用敏感数据; 仅检查序列化长度
                    try:
                        if len(json.dumps(value, ensure_ascii=False)) > MAX_TEXT_LENGTH * 4:
                            errors.append(f"参数 {key} 序列化体积过大")
                    except (TypeError, ValueError):
                        errors.append(f"参数 {key} 无法序列化")

        # 6. 理由长度
        if len(request.reason) > MAX_REASON_LENGTH:
            errors.append(f"reason 长度超出上限 ({MAX_REASON_LENGTH})")

        return (len(errors) == 0, errors)


__all__ = ["ActionValidator", "MAX_TEXT_LENGTH", "MAX_REASON_LENGTH"]
