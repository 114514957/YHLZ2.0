"""
YHLZ Embodied AI V8.0 - 宪法核心子包 (Constitution Core)
"""
from backend.embodied.companion.constitution.core.principles import (
    GOVERNANCE_PRIORITIES,
    PRINCIPLE_DEFINITIONS,
    Principles,
    PrinciplesError,
)
from backend.embodied.companion.constitution.core.identity_rules import (
    IDENTITY_CHANGE_SIGNALS,
    IDENTITY_PROTECTED_FIELDS,
    IdentityRules,
    IdentityRulesError,
)

__all__ = [
    "GOVERNANCE_PRIORITIES",
    "IDENTITY_CHANGE_SIGNALS",
    "IDENTITY_PROTECTED_FIELDS",
    "PRINCIPLE_DEFINITIONS",
    "IdentityRules",
    "IdentityRulesError",
    "Principles",
    "PrinciplesError",
]
