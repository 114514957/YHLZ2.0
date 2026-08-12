"""
YHLZ Embodied AI V5.8 - 认知完整性层 (Cognitive Integrity Layer)

架构:
    ExperienceVerifier     (经验验证状态机: UNKNOWN→PENDING→PROBABLE→CONFIRMED/REJECTED)
    ConfidenceEngine       (置信度引擎: 来源/重复/一致/反例/稳定 加权)
    EvidenceManager        (证据管理: 来源事件/时间/结果/证据)
    ContradictionDetector  (矛盾检测: 冲突 → Context-dependent Experience)
    RealityCheck           (现实检查: 5 问验证)

目标:
    防止错误经验进入长期记忆 / 幻觉形成事实 / 错误循环强化 / 自我欺骗式成长

规则:
    只有 CONFIRMED 经验才能进入长期成长参考
"""
from backend.embodied.companion.verification.confidence_engine import (
    ConfidenceEngine,
    ConfidenceError,
)
from backend.embodied.companion.verification.contradiction_detector import (
    ContradictionDetector,
    ContradictionError,
)
from backend.embodied.companion.verification.evidence_manager import (
    EvidenceError,
    EvidenceManager,
)
from backend.embodied.companion.verification.experience_verifier import (
    VERIFICATION_STATUSES,
    VERIFICATION_TRANSITIONS,
    ExperienceVerifier,
    VerificationState,
    VerifierError,
)
from backend.embodied.companion.verification.reality_check import (
    RealityCheck,
    RealityError,
)

__all__ = [
    "ConfidenceEngine",
    "ConfidenceError",
    "ContradictionDetector",
    "ContradictionError",
    "EvidenceError",
    "EvidenceManager",
    "ExperienceVerifier",
    "RealityCheck",
    "RealityError",
    "VERIFICATION_STATUSES",
    "VERIFICATION_TRANSITIONS",
    "VerificationState",
    "VerifierError",
]
