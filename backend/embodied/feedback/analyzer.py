"""
YHLZ Embodied AI V4.1 - 反馈分析器 (Feedback Analyzer)

职责:
    - 分析: Action Result + Environment Change → FeedbackAnalysis
    - 输出: success / failure_reason / suggestion
    - 建议供自适应规划使用 (Service 根据 suggestion 调整下一步动作)

设计原则:
    - 纯规则分析 (无 LLM / 无训练)
    - 确定性: 相同输入 → 相同建议
    - 规则表驱动 (SUGGESTION_RULES), 可扩展
    - 不直接调用 Executor / Environment (仅做分析)
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List, Optional

from backend.embodied.schema import (
    EmbodiedAction,
    EnvironmentState,
    Feedback,
    FeedbackAnalysis,
    FeedbackResult,
)

logger = logging.getLogger(__name__)


class FeedbackAnalyzerError(Exception):
    """反馈分析器操作异常"""


# 失败关键词 → 建议 (规则表, 按顺序匹配)
SUGGESTION_RULES: List[tuple] = [
    ("pick_not_in_reach", "移动到目标对象附近后再尝试拾取"),
    ("不在当前位置", "移动到目标对象附近后再尝试拾取"),
    ("move_out_of_bounds", "调整移动方向: 目标位置超出环境边界, 尝试反方向或更短距离"),
    ("越界", "调整移动方向: 目标位置超出环境边界, 尝试反方向或更短距离"),
    ("pick_missing", "确认目标对象是否存在, 或检查对象名称是否正确"),
    ("place_missing", "确认目标对象是否存在, 或检查对象名称是否正确"),
    ("不存在", "确认目标对象是否存在, 或检查对象名称是否正确"),
    ("place_not_held", "先执行拾取动作, 再执行放置"),
    ("未被持有", "先执行拾取动作, 再执行放置"),
    ("不支持", "当前动作类型不被环境支持, 更换为支持的动作类型"),
    ("不可用", "当前环境不可用, 切换默认环境或检查环境注册"),
    ("无可用", "检查环境注册: 当前没有可用环境"),
]


class FeedbackAnalyzer:
    """反馈分析器 (规则驱动)

    用法:
        analyzer = FeedbackAnalyzer()
        analysis = analyzer.analyze(feedback, action=action)
        suggestion = analysis.suggestion
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._analyzed_count = 0

    # ── 分析 ──────────────────────────────────────────────────────
    def analyze(
        self,
        feedback: Feedback,
        action: Optional[EmbodiedAction] = None,
        state: Optional[EnvironmentState] = None,
    ) -> FeedbackAnalysis:
        """分析行动反馈

        Args:
            feedback: 行动反馈 (来自 Environment.feedback)
            action:   对应的动作 (可选, 用于补充上下文)
            state:    动作后状态 (可选)

        Returns:
            FeedbackAnalysis (success / failure_reason / suggestion)
        """
        if feedback is None:
            raise FeedbackAnalyzerError("反馈不能为 None")

        with self._lock:
            self._analyzed_count += 1

        result = feedback.result
        change = feedback.environment_change or {}
        error = feedback.error or ""
        text = f"{result} {error} {change.get('event', '')}"

        # 1. 成功 (含无变化 / 部分成功)
        if result == FeedbackResult.SUCCESS.value:
            return FeedbackAnalysis.create(
                action_id=feedback.action_id, success=True,
                suggestion="行动成功, 按计划继续下一步或结束任务",
                environment_change=change,
            )
        if result == FeedbackResult.NO_CHANGE.value:
            reason = error or f"无状态变化 (event={change.get('event', 'unknown')})"
            return FeedbackAnalysis.create(
                action_id=feedback.action_id, success=False,
                failure_reason=reason,
                suggestion=self._suggest(text, default="尝试其他动作类型或调整参数"),
                environment_change=change,
            )
        if result == FeedbackResult.PARTIAL.value:
            return FeedbackAnalysis.create(
                action_id=feedback.action_id, success=True,
                failure_reason="部分完成",
                suggestion="行动部分完成, 检查环境状态后继续",
                environment_change=change,
            )

        # 2. 失败 → 规则匹配建议
        suggestion = self._suggest(text, default="行动失败: 重新规划下一步动作")
        return FeedbackAnalysis.create(
            action_id=feedback.action_id, success=False,
            failure_reason=error or "行动失败 (未提供具体原因)",
            suggestion=suggestion,
            environment_change=change,
        )

    def _suggest(self, text: str, default: str) -> str:
        """按规则表匹配建议"""
        for keyword, suggestion in SUGGESTION_RULES:
            if keyword.lower() in text.lower():
                return suggestion
        return default

    # ── 批量分析历史 ──────────────────────────────────────────────
    def analyze_many(
        self,
        feedbacks: List[Feedback],
    ) -> List[FeedbackAnalysis]:
        """批量分析反馈列表"""
        return [self.analyze(fb) for fb in feedbacks]

    # ── 状态 ──────────────────────────────────────────────────────
    def stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "analyzed_count": self._analyzed_count,
                "rules_count": len(SUGGESTION_RULES),
                "mode": "rule_based",
            }

    def reset(self) -> None:
        with self._lock:
            self._analyzed_count = 0


__all__ = ["FeedbackAnalyzer", "FeedbackAnalyzerError", "SUGGESTION_RULES"]
