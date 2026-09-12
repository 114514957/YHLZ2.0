"""
YHLZ Embodied AI V6.2 - 感知层 (Perception Layer)

架构:
    PerceptionService  (感知服务: 权限 → 采集 → 验证 → 记忆候选)
        ├── PerceptionManager     (适配器注册/路由/异常隔离)
        ├── PerceptionPermission  (权限: 默认拒绝, 显式授权)
        ├── PerceptionVerifier    (验证网关: Schema → Source → Confidence)
        └── PerceptionAudit       (感知审计)

安全协议:
    - 感知 ≠ 理解: Raw Input → Perception → Verification → Memory Candidate
    - 多模态输入隔离: 视觉不能直接进入人格/长期记忆/行动系统
    - 摄像头/OCR/检测默认关闭 (显式授权)
"""
from backend.embodied.companion.perception.adapters import (
    CameraAdapter,
    DetectionMockAdapter,
    OCRMockAdapter,
    TemplateDetectorAdapter,
    TesseractOCRAdapter,
    VisionMockAdapter,
)
from backend.embodied.companion.perception.audit import (
    AuditError,
    PERCEPTION_AUDIT_ACTIONS,
    PerceptionAudit,
)
from backend.embodied.companion.perception.interface import (
    PerceptionAdapter,
    PerceptionAdapterError,
)
from backend.embodied.companion.perception.manager import (
    ManagerError,
    PerceptionManager,
)
from backend.embodied.companion.perception.memory_gate import (
    ApprovalRule,
    ApprovalRuleError,
    CandidateValidator,
    IDENTITY_KEYWORDS,
    MemoryGate,
    MemoryGateError,
    REQUIRED_CANDIDATE_FIELDS,
    RISK_KEYWORDS,
    TRUSTED_SOURCES,
    VALUE_KEYWORDS,
    ValidatorError,
)
from backend.embodied.companion.perception.memory_gate.reflection import (
    CONTRADICTION_KEYWORDS,
    CounterfactualCheck,
    CounterfactualError,
    EvaluatorError,
    HIGH_STAKE_KEYWORDS,
    REFLECTION_AUDIT_ACTIONS,
    ReflectionAudit,
    ReflectionEvaluator,
    ReflectionRules,
    ReflectionRulesError,
)
from backend.embodied.companion.perception.pipeline import (
    ACTION_SENSITIVE,
    AgentPipelineAdapter,
    FRAME_TYPES,
    FrameError,
    PerceptionFrame,
    PerceptionRouter,
    PipelineAdapterError,
    ROUTE_TABLE,
    RouterError,
)
from backend.embodied.companion.perception.snapshot import (
    PerceptionStatsSnapshot,
)
from backend.embodied.companion.perception.permission import (
    PerceptionPermission,
    PermissionError,
)
from backend.embodied.companion.perception.schema import (
    DetectionResult,
    OCRResult,
    PERCEPTION_KINDS,
    PERCEPTION_SOURCES,
    PERCEPTION_TYPES,
    PerceptionEvent,
    SchemaError,
)
from backend.embodied.companion.perception.service import (
    PerceptionService,
    PerceptionServiceError,
)
from backend.embodied.companion.perception.verification import (
    PerceptionVerifier,
    VerificationError,
)

__all__ = [
    "ACTION_SENSITIVE",
    "AgentPipelineAdapter",
    "ApprovalRule",
    "ApprovalRuleError",
    "AuditError",
    "CameraAdapter",
    "CandidateValidator",
    "DetectionMockAdapter",
    "DetectionResult",
    "FRAME_TYPES",
    "FrameError",
    "IDENTITY_KEYWORDS",
    "ManagerError",
    "MemoryGate",
    "MemoryGateError",
    "OCRMockAdapter",
    "OCRResult",
    "PERCEPTION_AUDIT_ACTIONS",
    "PERCEPTION_KINDS",
    "PERCEPTION_SOURCES",
    "PERCEPTION_TYPES",
    "PerceptionAdapter",
    "PerceptionAdapterError",
    "PerceptionAudit",
    "PerceptionEvent",
    "PerceptionFrame",
    "PerceptionManager",
    "PerceptionPermission",
    "PerceptionRouter",
    "PerceptionService",
    "PerceptionServiceError",
    "PerceptionVerifier",
    "PermissionError",
    "PipelineAdapterError",
    "REQUIRED_CANDIDATE_FIELDS",
    "RISK_KEYWORDS",
    "ROUTE_TABLE",
    "RouterError",
    "SchemaError",
    "TRUSTED_SOURCES",
    "ReflectionAudit",
    "ReflectionEvaluator",
    "ReflectionRules",
    "ReflectionRulesError",
    "PerceptionStatsSnapshot",
    "CounterfactualCheck",
    "CounterfactualError",
    "EvaluatorError",
    "HIGH_STAKE_KEYWORDS",
    "CONTRADICTION_KEYWORDS",
    "REFLECTION_AUDIT_ACTIONS",
    "TemplateDetectorAdapter",
    "TesseractOCRAdapter",
    "VALUE_KEYWORDS",
    "ValidatorError",
    "VerificationError",
    "VisionMockAdapter",
]
