"""
YHLZ Embodied AI V4.2 - 因果分析器 (Causal Analyzer)

职责:
    - 从"Action Failed"升级为"Action Failed → 为什么失败"
    - 输入: Feedback + Action + 状态差异 → 输出 CausalAnalysis (cause / mechanism / remedy)
    - 规则驱动因果推断, 禁止 AI 猜测 / 训练式归因

支持因果 (CauseType):
    - position_mismatch:  位置不匹配 (拾取时对象不在当前位置)
    - boundary_limit:     边界限制 (移动目标超出环境网格)
    - object_missing:     对象缺失 (目标对象不存在)
    - object_not_held:    对象未持有 (放置前未拾取)
    - invalid_parameter:  参数不合法 (dx/dy 非数值)
    - unsupported_action: 动作类型不支持
    - env_unavailable:    环境不可用
    - permission_denied:  权限拒绝 (总开关关闭 / 风险评估拒绝)
    - invariant_violation: 状态不变式违反
    - unknown:            未识别原因

设计原则:
    - 纯规则 (静态规则表 + 状态对照), 确定性输出
    - 因果只用于解释与建议, 不直接驱动执行 (必须经 Permission → Executor)
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List, Optional, Tuple

from backend.embodied.schema import (
    CauseType,
    CausalAnalysis,
    EmbodiedAction,
    EmbodiedActionType,
    EnvironmentState,
    Feedback,
    FeedbackResult,
)

logger = logging.getLogger(__name__)


class CausalAnalyzerError(Exception):
    """因果分析器操作异常"""


# 失败原因 → 因果类型 (规则表, 按顺序匹配; 用于 error / 文本)
CAUSE_RULES: List[Tuple[str, str]] = [
    ("越界", CauseType.BOUNDARY_LIMIT.value),
    ("out_of_bounds", CauseType.BOUNDARY_LIMIT.value),
    ("边界", CauseType.BOUNDARY_LIMIT.value),
    ("不在当前", CauseType.POSITION_MISMATCH.value),
    ("不在位置", CauseType.POSITION_MISMATCH.value),
    ("not_in_reach", CauseType.POSITION_MISMATCH.value),
    ("位置不匹配", CauseType.POSITION_MISMATCH.value),
    ("未被持有", CauseType.OBJECT_NOT_HELD.value),
    ("not_held", CauseType.OBJECT_NOT_HELD.value),
    ("未拾取", CauseType.OBJECT_NOT_HELD.value),
    ("对象不存在", CauseType.OBJECT_MISSING.value),
    ("不存在", CauseType.OBJECT_MISSING.value),
    ("missing", CauseType.OBJECT_MISSING.value),
    ("不支持", CauseType.UNSUPPORTED_ACTION.value),
    ("不可用", CauseType.ENV_UNAVAILABLE.value),
    ("无可用环境", CauseType.ENV_UNAVAILABLE.value),
    ("权限", CauseType.PERMISSION_DENIED.value),
    ("开关未开启", CauseType.PERMISSION_DENIED.value),
    ("dx/dy", CauseType.INVALID_PARAMETER.value),
    ("不合法", CauseType.INVALID_PARAMETER.value),
]

# 因果类型 → 补救措施 (规则表)
CAUSE_REMEDY_RULES: Dict[str, str] = {
    CauseType.POSITION_MISMATCH.value: "先移动到目标对象附近, 再执行拾取",
    CauseType.BOUNDARY_LIMIT.value: "调整移动方向: 目标超出边界, 尝试反方向或缩短步长",
    CauseType.OBJECT_MISSING.value: "确认目标对象是否存在, 或检查对象名称是否正确",
    CauseType.OBJECT_NOT_HELD.value: "先执行拾取动作, 再执行放置",
    CauseType.INVALID_PARAMETER.value: "检查动作参数: dx/dy 必须为数值, object 必须为对象名",
    CauseType.UNSUPPORTED_ACTION.value: "当前动作类型不被环境支持, 更换为支持的动作类型",
    CauseType.ENV_UNAVAILABLE.value: "当前环境不可用, 切换默认环境或检查环境注册",
    CauseType.PERMISSION_DENIED.value: "动作被权限层拒绝, 需先授权或降低风险",
    CauseType.INVARIANT_VIOLATION.value: "预测违反状态不变式, 调整动作序列后重新规划",
    CauseType.UNKNOWN.value: "未识别失败原因, 检查环境日志后重新规划",
}


class CausalAnalyzer:
    """因果分析器 (规则驱动)

    用法:
        analyzer = CausalAnalyzer()
        causal = analyzer.analyze(feedback, action=action)
        cause = causal.cause  # 'position_mismatch'
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._analyzed_count = 0

    # ── 主入口 ────────────────────────────────────────────────────
    def analyze(
        self,
        feedback: Feedback,
        action: Optional[EmbodiedAction] = None,
        state: Optional[EnvironmentState] = None,
        previous_state: Optional[EnvironmentState] = None,
    ) -> CausalAnalysis:
        """分析行动反馈, 输出因果 (cause / mechanism / remedy / confidence)

        Args:
            feedback:        行动反馈 (必填)
            action:          对应动作 (可选)
            state:           动作后状态 (可选)
            previous_state:  动作前状态 (可选, 用于状态对照)

        Returns:
            CausalAnalysis
        """
        if feedback is None:
            raise CausalAnalyzerError("反馈不能为 None")

        with self._lock:
            self._analyzed_count += 1

        # 成功 / 无变化(无错误) / 部分成功 → 无因果
        if feedback.result == FeedbackResult.SUCCESS.value:
            return CausalAnalysis.create(
                action_id=feedback.action_id, cause="",
                mechanism="行动成功, 无需因果分析",
                remedy="按计划继续下一步",
                confidence=0.95,
                evidence={"result": feedback.result},
            )
        if feedback.result == FeedbackResult.NO_CHANGE.value and not feedback.error:
            return CausalAnalysis.create(
                action_id=feedback.action_id, cause="",
                mechanism="无状态变化且无错误信息",
                remedy="尝试其他动作类型或调整参数",
                confidence=0.6,
                evidence={"result": feedback.result},
            )
        if feedback.result == FeedbackResult.PARTIAL.value:
            return CausalAnalysis.create(
                action_id=feedback.action_id, cause="",
                mechanism="行动部分完成",
                remedy="检查环境状态后继续",
                confidence=0.8,
                evidence={"result": feedback.result},
            )

        text = self._evidence_text(feedback, action)
        cause = self._match_cause(text)
        if cause == CauseType.UNKNOWN.value:
            cause = self._infer_from_state(action, state, previous_state)
        confidence = self._confidence_for(cause)
        mechanism = self._build_mechanism(cause, feedback, action)
        return CausalAnalysis.create(
            action_id=feedback.action_id, cause=cause,
            mechanism=mechanism,
            remedy=CAUSE_REMEDY_RULES.get(cause, ""),
            confidence=confidence,
            evidence={
                "result": feedback.result,
                "error": feedback.error,
                "change": feedback.environment_change,
                "action_type": action.action_type if action else "",
            },
        )

    # ── 因果匹配 ──────────────────────────────────────────────────
    @staticmethod
    def _evidence_text(feedback: Feedback, action: Optional[EmbodiedAction]) -> str:
        """拼接因果判定文本 (error + change + action)"""
        change = feedback.environment_change or {}
        parts = [
            feedback.error or "",
            change.get("event", ""),
            str(change),
            action.action_type if action else "",
            action.target if action else "",
        ]
        return " ".join(parts)

    def _match_cause(self, text: str) -> str:
        """按规则表匹配因果类型"""
        low = text.lower()
        for keyword, cause in CAUSE_RULES:
            if keyword.lower() in low:
                return cause
        return CauseType.UNKNOWN.value

    def _infer_from_state(
        self,
        action: Optional[EmbodiedAction],
        state: Optional[EnvironmentState],
        previous_state: Optional[EnvironmentState],
    ) -> str:
        """状态级推断: 文本无法匹配时, 用状态差异推断 (无状态 → unknown)"""
        if action is None or state is None or previous_state is None:
            return CauseType.UNKNOWN.value
        if action.action_type == EmbodiedActionType.PICK.value:
            return self._infer_pick(action, state, previous_state)
        if action.action_type == EmbodiedActionType.PLACE.value:
            return self._infer_place(action, state, previous_state)
        if action.action_type == EmbodiedActionType.MOVE.value:
            return self._infer_move(action, state, previous_state)
        return CauseType.UNKNOWN.value

    @staticmethod
    def _find_object_in_state(
        state: EnvironmentState, action: EmbodiedAction
    ) -> Optional[Any]:
        name = str(action.parameters.get("object") or action.target)
        if not name:
            return None
        for o in state.objects:
            if o.name == name:
                return o
        return None

    def _infer_pick(
        self, action: EmbodiedAction, state: EnvironmentState,
        previous_state: EnvironmentState,
    ) -> str:
        obj = self._find_object_in_state(state, action)
        if obj is None:
            prev = self._find_object_in_state(previous_state, action)
            if prev is None:
                return CauseType.OBJECT_MISSING.value
            return CauseType.OBJECT_MISSING.value
        # 对象存在但未被持有 → 位置不匹配 (拾取条件不满足)
        if obj.state != "held":
            return CauseType.POSITION_MISMATCH.value
        return CauseType.UNKNOWN.value

    def _infer_place(
        self, action: EmbodiedAction, state: EnvironmentState,
        previous_state: EnvironmentState,
    ) -> str:
        obj = self._find_object_in_state(state, action)
        if obj is None:
            return CauseType.OBJECT_MISSING.value
        # 对象仍在 held → 放置条件不满足
        if obj.state == "held":
            return CauseType.OBJECT_NOT_HELD.value
        return CauseType.UNKNOWN.value

    @staticmethod
    def _infer_move(
        action: EmbodiedAction, state: EnvironmentState,
        previous_state: EnvironmentState,
    ) -> str:
        if previous_state.location == state.location:
            return CauseType.BOUNDARY_LIMIT.value
        return CauseType.UNKNOWN.value

    @staticmethod
    def _confidence_for(cause: str) -> float:
        """因果置信度 (文本匹配高, 状态推断中, 未知低)"""
        if cause in (
            CauseType.POSITION_MISMATCH.value,
            CauseType.BOUNDARY_LIMIT.value,
            CauseType.OBJECT_MISSING.value,
            CauseType.OBJECT_NOT_HELD.value,
        ):
            return 0.9
        if cause in (
            CauseType.UNSUPPORTED_ACTION.value,
            CauseType.ENV_UNAVAILABLE.value,
            CauseType.PERMISSION_DENIED.value,
            CauseType.INVALID_PARAMETER.value,
        ):
            return 0.85
        if cause == CauseType.INVARIANT_VIOLATION.value:
            return 0.8
        return 0.3

    @staticmethod
    def _build_mechanism(
        cause: str, feedback: Feedback, action: Optional[EmbodiedAction]
    ) -> str:
        """构造机制描述 (为什么失败)"""
        a_type = action.action_type if action else "unknown"
        target = action.target if action and action.target else ""
        if cause == CauseType.POSITION_MISMATCH.value:
            return f"{a_type} 失败: 目标对象 {target or '(未指定)'} 不在当前位置"
        if cause == CauseType.BOUNDARY_LIMIT.value:
            return f"{a_type} 失败: 目标位置超出环境边界"
        if cause == CauseType.OBJECT_MISSING.value:
            return f"{a_type} 失败: 目标对象 {target or '(未指定)'} 不存在于环境"
        if cause == CauseType.OBJECT_NOT_HELD.value:
            return f"{a_type} 失败: 目标对象 {target or '(未指定)'} 未被持有"
        if cause == CauseType.INVALID_PARAMETER.value:
            return f"{a_type} 失败: 动作参数不合法"
        if cause == CauseType.UNSUPPORTED_ACTION.value:
            return f"{a_type} 失败: 环境不支持该动作类型"
        if cause == CauseType.ENV_UNAVAILABLE.value:
            return f"{a_type} 失败: 环境不可用"
        if cause == CauseType.PERMISSION_DENIED.value:
            return f"{a_type} 失败: 权限层拒绝"
        return f"{a_type} 失败: 原因未识别 (error={feedback.error or '无'})"

    # ── 批量分析 ──────────────────────────────────────────────────
    def analyze_many(
        self,
        feedbacks: List[Feedback],
    ) -> List[CausalAnalysis]:
        """批量分析反馈列表"""
        return [self.analyze(fb) for fb in feedbacks]

    # ── 状态 ──────────────────────────────────────────────────────
    def stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "analyzed_count": self._analyzed_count,
                "cause_rules_count": len(CAUSE_RULES),
                "supported_causes": CauseType.values(),
                "mode": "rule_based",
            }

    def reset(self) -> None:
        with self._lock:
            self._analyzed_count = 0


__all__ = ["CausalAnalyzer", "CausalAnalyzerError", "CAUSE_RULES", "CAUSE_REMEDY_RULES"]
