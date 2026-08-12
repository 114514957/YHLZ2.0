"""
YHLZ Embodied AI V4.3 - 经验学习系统 (Rule-based Experience Learning)

架构:
    Experience → Analysis → Pattern Extraction → Policy Table → Future Suggestion

约束 (必须保持):
    - 禁止神经网络训练 / 梯度更新 / 黑盒学习
    - 纯规则表 + 模板匹配, 策略全部可解释
    - 策略建议不绕过 Permission Layer
"""
from backend.embodied.experience.learner import (
    ExperienceLearner,
    ExperienceLearnerError,
)
from backend.embodied.experience.patterns import (
    FAILURE_PATTERN_RULES,
    PatternExtractor,
    PatternExtractorError,
)
from backend.embodied.experience.policy import (
    ExperiencePolicy,
    PolicyTable,
    PolicyTableError,
    POLICY_STATUS_ACTIVE,
    POLICY_STATUS_ARCHIVED,
    POLICY_STATUS_DEGRADED,
    POLICY_STATUS_STALE,
    POLICY_STATUSES,
)

__all__ = [
    "ExperienceLearner",
    "ExperienceLearnerError",
    "ExperiencePolicy",
    "FAILURE_PATTERN_RULES",
    "PatternExtractor",
    "PatternExtractorError",
    "PolicyTable",
    "PolicyTableError",
    "POLICY_STATUS_ACTIVE",
    "POLICY_STATUS_ARCHIVED",
    "POLICY_STATUS_DEGRADED",
    "POLICY_STATUS_STALE",
    "POLICY_STATUSES",
]
