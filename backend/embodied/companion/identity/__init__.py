"""
YHLZ Embodied AI V6.5 - 身份保护层 (Identity Protection Layer)

架构:
    IdentityGuard      (身份守护: 保护 Personality/Core Values/Mission/
                        Safety Rules, 拦截记录)
    ChangeValidator    (变更验证: Before/Change/Reason/After/Verification)

原则:
    - 核心身份不可自动修改
    - 任何变化必须经过 Identity Guard
"""
from backend.embodied.companion.identity.change_validator import (
    ChangeValidator,
    ValidatorError,
)
from backend.embodied.companion.identity.identity_guard import (
    PROTECTED_FIELDS,
    GuardError,
    IdentityGuard,
)

__all__ = [
    "ChangeValidator",
    "GuardError",
    "IdentityGuard",
    "PROTECTED_FIELDS",
    "ValidatorError",
]
