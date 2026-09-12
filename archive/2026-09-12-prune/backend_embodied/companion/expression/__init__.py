"""
YHLZ Embodied AI V6.2 - 表达层 (Expression Layer)

架构:
    ExpressionEngine  (表达引擎: 状态 → 表达建议)
        ├── ExpressionRules    (规则表: 高积极/低能量/高温度/高信任/任务失败)
        ├── ExpressionContext  (上下文聚合: Emotion/Relationship/Task/Conversation)
        └── ExpressionAudit    (表达审计)

安全协议:
    - 表达 ≠ 人格修改: 只影响回复风格, 不触碰 Personality/
      Core Value / Mission / Identity
"""
from backend.embodied.companion.expression.expression_audit import (
    AuditError,
    EXPRESSION_AUDIT_ACTIONS,
    ExpressionAudit,
)
from backend.embodied.companion.expression.expression_context import (
    ContextError,
    ExpressionContext,
)
from backend.embodied.companion.expression.expression_engine import (
    ExpressionEngine,
    ExpressionEngineError,
)
from backend.embodied.companion.expression.expression_rules import (
    EXPRESSION_RULES,
    EXPRESSION_STYLES,
    EXPRESSION_TONES,
    ExpressionRules,
    RulesError,
)

__all__ = [
    "AuditError",
    "ContextError",
    "EXPRESSION_AUDIT_ACTIONS",
    "EXPRESSION_RULES",
    "EXPRESSION_STYLES",
    "EXPRESSION_TONES",
    "ExpressionAudit",
    "ExpressionContext",
    "ExpressionEngine",
    "ExpressionEngineError",
    "ExpressionRules",
    "RulesError",
]
