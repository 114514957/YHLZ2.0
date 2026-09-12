"""
YHLZ Embodied AI V4.4 - 经验模式提取器 (Pattern Extractor)

职责:
    - 失败经验沉淀: (动作类型 + 失败因果) → 失败策略 (trigger + strategy)
    - 成功经验沉淀: 成功动作序列 → Successful Recipe (Action Sequence + Preconditions)
    - V4.4 成功配方泛化: move 参数归一化 (dx/dy → 方向 + 距离等级), 提高跨场景复用
    - 纯规则模板匹配: 禁止神经网络训练 / 梯度更新 / 黑盒学习
    - 输出可解释策略: 任何策略都能追溯来源 (原因 + 建议)

设计原则:
    - 规则表驱动 (FAILURE_PATTERN_RULES): 确定性输出, 可测试
    - 模板匹配: 相同失败原因 → 相同策略 (可解释)
    - 经验只用于建议与规划初始化, 不改变权限层 (Permission Layer 不可绕过)
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List, Optional

from backend.embodied.schema import CauseType, Feedback, FeedbackResult

logger = logging.getLogger(__name__)

# V4.4 配方泛化: 移动距离等级规则表 (可解释, 阈值驱动)
#   max(|dx|, |dy|) <= 1 → small; <= 3 → medium; 其他 → large
MOVE_DISTANCE_LEVEL_RULES: List[tuple] = [
    (1, "small"),
    (3, "medium"),
    (float("inf"), "large"),
]

# V4.4 配方泛化: 距离等级 → 步长 (反归一化, 场景无关的相对量)
MOVE_STEP_SIZE_BY_LEVEL: Dict[str, int] = {
    "small": 1,
    "medium": 3,
    "large": 4,
}

# V4.4 配方泛化: 主轴向符号 → 方向
#   (dx 符号, dy 符号, 是否 dx 为主轴) → 方向名
def _move_direction(dx: int, dy: int) -> str:
    """移动方向 (主轴向优先)"""
    if abs(dx) >= abs(dy):
        return "right" if dx > 0 else ("left" if dx < 0 else "down")
    return "down" if dy > 0 else "up"


def normalize_move_parameters(dx: Optional[Any], dy: Optional[Any]) -> Optional[Dict[str, Any]]:
    """移动参数归一化 (V4.4): (dx, dy) → 方向 + 距离等级

    例: dx=100, dy=50 → {'direction': 'right', 'distance_level': 'medium'}

    Args:
        dx / dy: 原始位移 (None / 非法 → None, 保持可解释)

    Returns:
        {'direction': 'right'|'left'|'up'|'down', 'distance_level': 'small'|'medium'|'large'}
        或 None (dx/dy 缺失或全 0)
    """
    try:
        dx_i, dy_i = int(dx), int(dy)
    except (TypeError, ValueError):
        return None
    if dx_i == 0 and dy_i == 0:
        return None
    dist = max(abs(dx_i), abs(dy_i))
    for threshold, level in MOVE_DISTANCE_LEVEL_RULES:
        if dist <= threshold:
            return {
                "direction": _move_direction(dx_i, dy_i),
                "distance_level": level,
            }
    return {"direction": _move_direction(dx_i, dy_i), "distance_level": "large"}


def denormalize_move_parameters(
    direction: Optional[str] = "",
    distance_level: Optional[str] = "",
) -> Dict[str, int]:
    """移动参数反归一化 (V4.4): 方向 + 距离等级 → (dx, dy)

    规则表 (场景无关的相对量):
        small → 步长 1; medium → 步长 3; large → 步长 4
        right → dx=+步长; left → dx=-步长; down → dy=+步长; up → dy=-步长

    Returns:
        {'dx': int, 'dy': int} (无法识别 → dx=0, dy=0)
    """
    step = MOVE_STEP_SIZE_BY_LEVEL.get(str(distance_level or ""), 0)
    if step <= 0:
        return {"dx": 0, "dy": 0}
    if direction == "right":
        return {"dx": step, "dy": 0}
    if direction == "left":
        return {"dx": -step, "dy": 0}
    if direction == "down":
        return {"dx": 0, "dy": step}
    if direction == "up":
        return {"dx": 0, "dy": -step}
    return {"dx": 0, "dy": 0}


class PatternExtractorError(Exception):
    """经验模式提取异常"""


# 失败模式规则表: (action_type, cause, trigger, strategy, detail, required_action)
#   - trigger: 策略触发标识 (供 PolicyTable 索引)
#   - strategy: 未来建议策略 (可解释)
#   - required_action: 采纳该策略所需执行的核心动作 (用于采纳统计)
FAILURE_PATTERN_RULES: List[tuple] = [
    (
        "pick", CauseType.POSITION_MISMATCH.value,
        "pick_failure_position", "move_to_target_before_pick",
        "拾取失败 (对象不在当前位置): 先移动到目标对象附近再拾取",
        "move",
    ),
    (
        "pick", CauseType.OBJECT_MISSING.value,
        "pick_failure_location", "scan_before_pick",
        "拾取失败 (对象位置未知): 拾取前先扫描环境确认对象位置",
        "scan",
    ),
    (
        "move", CauseType.BOUNDARY_LIMIT.value,
        "move_failure_boundary", "adjust_direction_or_shorten_step",
        "移动失败 (越界): 调整移动方向或缩短步长",
        "move",
    ),
    (
        "place", CauseType.OBJECT_NOT_HELD.value,
        "place_failure_not_held", "pick_before_place",
        "放置失败 (对象未被持有): 先拾取对象再放置",
        "pick",
    ),
    (
        "place", CauseType.OBJECT_MISSING.value,
        "place_failure_missing", "scan_before_place",
        "放置失败 (对象缺失): 放置前先扫描确认对象存在",
        "scan",
    ),
    (
        "inspect", CauseType.OBJECT_MISSING.value,
        "inspect_failure_missing", "scan_before_inspect",
        "检查失败 (对象缺失): 检查前先扫描确认对象存在",
        "scan",
    ),
]


class PatternExtractor:
    """经验模式提取器 (规则模板匹配)

    用法:
        extractor = PatternExtractor()
        policy = extractor.extract_failure_policy(action, feedback, analysis)
        recipe = extractor.extract_success_recipe(goal, plan, executed)
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._extracted_count = 0

    # ── 失败经验: (动作类型 + 因果) → 失败策略 ────────────────────
    def extract_failure_policy(
        self,
        action,
        feedback: Optional[Feedback],
        analysis=None,
    ) -> Optional[Dict[str, Any]]:
        """从一次失败提取失败策略 (无匹配 → None)

        Args:
            action:    失败动作
            feedback:  行动反馈 (result=FAILURE 才有意义)
            analysis:  反馈分析 (携带 cause)

        Returns:
            {
                'trigger': 'pick_failure_location',
                'strategy': 'scan_before_pick',
                'detail': ...,
                'kind': 'failure',
                'action_type': 'pick',
                'cause': 'object_missing',
                'required_action': 'scan',
            } 或 None
        """
        if action is None or feedback is None:
            return None
        if feedback.result != FeedbackResult.FAILURE.value:
            return None
        cause = None
        if analysis is not None:
            cause = getattr(analysis, "cause", None)
        if not cause:
            cause = (feedback.to_dict() if hasattr(feedback, "to_dict") else {}).get(
                "cause"
            )
        if not cause:
            return None

        with self._lock:
            self._extracted_count += 1
        for action_type, cause_type, trigger, strategy, detail, required in (
            FAILURE_PATTERN_RULES
        ):
            if action.action_type == action_type and cause == cause_type:
                return {
                    "trigger": trigger,
                    "strategy": strategy,
                    "detail": detail,
                    "kind": "failure",
                    "action_type": action_type,
                    "cause": cause,
                    "required_action": required,
                }
        return None

    # ── 成功经验: 成功动作序列 → Successful Recipe ────────────────
    def extract_success_recipe(
        self,
        goal,
        plan: Optional[List[Any]] = None,
        executed: Optional[List[Dict[str, Any]]] = None,
    ) -> Optional[Dict[str, Any]]:
        """从成功目标轨迹提取成功配方 (Recipe)

        Args:
            goal:      目标 (携带 target / description)
            plan:      初始计划 (可选)
            executed:  实际执行序列 (List[Dict]: action_type / parameters / success)

        Returns:
            {
                'trigger': 'recipe_pick',
                'strategy': 'move_then_pick',
                'detail': ...,
                'kind': 'success',
                'action_sequence': [{'action_type': 'move', 'parameters': {...}}, ...],
                'preconditions': [...],
            } 或 None (无成功动作时)
        """
        if executed is None or not executed:
            return None
        successful = [e for e in executed if e.get("success")]
        if not successful:
            return None

        # 归一化: 合并连续同类型动作, 关键参数归一化 (V4.4 配方泛化)
        #   move: dx/dy → direction + distance_level (跨场景可复用)
        #   其他动作: 保留原始参数
        seq: List[Dict[str, Any]] = []
        for e in successful:
            item: Dict[str, Any] = {
                "action_type": str(e.get("action_type", "")),
                "parameters": dict(e.get("parameters") or {}),
            }
            if item["action_type"] == "move":
                norm = normalize_move_parameters(
                    item["parameters"].get("dx"),
                    item["parameters"].get("dy"),
                )
                if norm is not None:
                    item["parameters"] = norm
            if not seq or seq[-1]["action_type"] != item["action_type"]:
                seq.append(item)

        first_type = seq[0]["action_type"]
        trigger = f"recipe_{first_type}"
        strategy = "_then_".join(s["action_type"] for s in seq)
        target = goal.target if goal is not None else ""

        with self._lock:
            self._extracted_count += 1
        return {
            "trigger": trigger,
            "strategy": strategy,
            "detail": (
                f"成功配方: {strategy} (对象={target or '无'}) "
                f"来源目标: {goal.goal_id if goal is not None else 'unknown'}"
            ),
            "kind": "success",
            "action_sequence": seq,
            "preconditions": self._preconditions(seq, target),
        }

    @staticmethod
    def _preconditions(
        seq: List[Dict[str, Any]], target: str
    ) -> List[str]:
        """成功配方的先决条件 (可解释, 供规划前检查)"""
        types = {s["action_type"] for s in seq}
        pre: List[str] = ["permission_required"]
        if "pick" in types or "place" in types or "inspect" in types:
            if target:
                pre.append("target_object_exists")
        if "move" in types:
            pre.append("target_location_known")
        if "place" in types:
            pre.append("pick_before_place")
        return pre

    @staticmethod
    def recipe_trigger_for_plan(plan: Optional[List[Any]]) -> str:
        """目标对应的配方触发标识 (与配方提取规则一致)

        例: plan[0]=pick → 'recipe_pick'
        """
        if not plan:
            return ""
        first = getattr(plan[0], "action_type", None) or (
            plan[0].get("action_type") if isinstance(plan[0], dict) else ""
        )
        return f"recipe_{first}" if first else ""

    # ── 状态 ──────────────────────────────────────────────────────
    def stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "extracted_count": self._extracted_count,
                "failure_rules_count": len(FAILURE_PATTERN_RULES),
                "mode": "rule_based",
            }

    def reset(self) -> None:
        with self._lock:
            self._extracted_count = 0


__all__ = [
    "PatternExtractor",
    "PatternExtractorError",
    "FAILURE_PATTERN_RULES",
    "MOVE_DISTANCE_LEVEL_RULES",
    "MOVE_STEP_SIZE_BY_LEVEL",
    "denormalize_move_parameters",
    "normalize_move_parameters",
]
