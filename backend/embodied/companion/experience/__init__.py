"""
YHLZ Embodied AI V5.7 - 经历记忆层 (Experience Memory Layer)

架构:
    ExperienceManager (门面, Service 唯一接入点)
        ├── ExperienceStore      (存储: store/retrieve/update/decay/forget)
        ├── ExperienceExtractor  (抽取: 事件 → 经验, 规则驱动)
        ├── ExperienceQuery      (查询: 类型/关键词/相关检索)
        └── ExperienceAudit      (审计: 每次操作追踪)

经历 → 记录 → 总结 → 学习 → 改进 (成长闭环)

经验类型 (5 种):
    interaction / engineering / decision / failure / improvement

约束:
    - 只记录经历与经验 (不记录完整聊天, 不写 Agent Memory)
    - 经验仅供参考, 不替代核心 Agent 决策
    - 禁止无限记忆 (上限 + 低价值衰减遗忘)
    - 纯规则抽取 (禁止黑盒学习)
"""
from backend.embodied.companion.experience.experience_audit import (
    AUDIT_ACTIONS_EXP,
    AuditError,
    ExperienceAudit,
)
from backend.embodied.companion.experience.experience_extractor import (
    ExperienceExtractor,
    ExtractorError,
)
from backend.embodied.companion.experience.experience_manager import (
    ExperienceManager,
    ExperienceManagerError,
)
from backend.embodied.companion.experience.experience_query import (
    ExperienceQuery,
    ExperienceQueryError,
)
from backend.embodied.companion.experience.experience_record import (
    EXPERIENCE_TYPES,
    ExperienceError,
    ExperienceRecord,
    VALUE_HIGH,
    VALUE_LOW,
    VALUE_MEDIUM,
)
from backend.embodied.companion.experience.experience_store import (
    ExperienceStore,
    ExperienceStoreError,
)
from backend.embodied.companion.experience.experience_schema import (
    APPROVERS,
    EXPERIENCE_SOURCES,
    MODALITIES,
    MultimodalError,
    MultimodalExperience,
    Provenance,
    ProvenanceError,
)

__all__ = [
    "AUDIT_ACTIONS_EXP",
    "AuditError",
    "EXPERIENCE_TYPES",
    "ExperienceAudit",
    "ExperienceError",
    "ExperienceExtractor",
    "ExperienceManager",
    "ExperienceManagerError",
    "ExperienceQuery",
    "ExperienceQueryError",
    "ExperienceRecord",
    "ExperienceStore",
    "ExperienceStoreError",
    "ExtractorError",
    "VALUE_HIGH",
    "VALUE_LOW",
    "VALUE_MEDIUM",
    "APPROVERS",
    "EXPERIENCE_SOURCES",
    "MODALITIES",
    "MultimodalError",
    "MultimodalExperience",
    "Provenance",
    "ProvenanceError",
]
