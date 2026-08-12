"""
YHLZ Embodied AI V6.4 - 经验数据模型 (Experience Schema)

职责:
    - 经验数据模型扩展:
      - Provenance (来源链)
      - MultimodalExperience (多模态统一对象)
      - 感知经验创建辅助 (experience_create)

设计原则:
    - 经验必须具有来源 (Provenance)
    - 多模态统一经验对象
    - 纯规则 (无黑盒)
"""
from backend.embodied.companion.experience.multimodal_experience import (
    EXPERIENCE_SOURCES,
    MODALITIES,
    MultimodalError,
    MultimodalExperience,
)
from backend.embodied.companion.experience.provenance import (
    APPROVERS,
    Provenance,
    ProvenanceError,
)

__all__ = [
    "APPROVERS",
    "EXPERIENCE_SOURCES",
    "MODALITIES",
    "MultimodalError",
    "MultimodalExperience",
    "Provenance",
    "ProvenanceError",
]
