"""
YHLZ Embodied AI V4.1 - 反馈包

架构:
    FeedbackStore (反馈记录 + 指标)
        ↓
    FeedbackAnalyzer (反馈分析: success / failure / suggestion)
        ↓
    FeedbackProcessor (处理链路编排: 存储 → 分析 → 记忆 → 对照)
"""

from backend.embodied.feedback.analyzer import (
    FeedbackAnalyzer,
    FeedbackAnalyzerError,
    SUGGESTION_RULES,
)
from backend.embodied.feedback.processor import (
    FeedbackProcessor,
    FeedbackStore,
    FeedbackStoreError,
)

__all__ = [
    "FeedbackAnalyzer",
    "FeedbackAnalyzerError",
    "FeedbackProcessor",
    "FeedbackStore",
    "FeedbackStoreError",
    "SUGGESTION_RULES",
]
