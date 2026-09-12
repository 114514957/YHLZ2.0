"""
YHLZ Embodied AI V6.0 - 长期记忆体系 (Memory Architecture)

架构:
    MemoryImportance     (记忆价值评分: Identity/Relationship/
                          Creative/Repeat → 保护规则)
    MemoryIndex          (统一记忆索引: 类型/阶段/价值查询)
    MemoryConsolidation  (记忆整合: Active → Cold → Archive → Recycle)

记忆类型:
    identity / relationship / experience / reflection / creative

规则:
    - Importance = Identity Impact + Relationship Impact
                   + Creative Impact + Repeat Value
    - 高价值记忆禁止自动删除
"""
from backend.embodied.companion.memory.memory_consolidation import (
    CONSOLIDATION_TRANSITIONS,
    ConsolidationError,
    MemoryConsolidation,
)
from backend.embodied.companion.memory.memory_importance import (
    CREATIVE_KEYWORDS,
    IDENTITY_KEYWORDS,
    ImportanceError,
    MemoryImportance,
    RELATIONSHIP_KEYWORDS,
)
from backend.embodied.companion.memory.memory_index import (
    MEMORY_STAGES,
    MEMORY_TYPES,
    IndexError,
    MemoryIndex,
)

__all__ = [
    "CONSOLIDATION_TRANSITIONS",
    "CREATIVE_KEYWORDS",
    "ConsolidationError",
    "IDENTITY_KEYWORDS",
    "ImportanceError",
    "IndexError",
    "MEMORY_STAGES",
    "MEMORY_TYPES",
    "MemoryConsolidation",
    "MemoryImportance",
    "MemoryIndex",
    "RELATIONSHIP_KEYWORDS",
]
