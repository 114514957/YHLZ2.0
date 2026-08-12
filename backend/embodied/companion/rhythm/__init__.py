"""
YHLZ Embodied AI V6.1.1 - 成长节律层 (Growth Rhythm Layer)

架构:
    GrowthRhythm          (节律门面: handle 联动 + 自动整理 + 自动快照 + 反思触发)
        ├── GrowthTrigger           (触发条件: 经验阈值 / 整理天数)
        ├── ConsolidationScheduler  (整理调度: 条件达成自动整理)
        └── RhythmAudit             (节律审计: 自动行为全程可追踪)

流程:
    Handle → Event Capture → Growth Track → Threshold Check
    → Memory Consolidation → Reflection Trigger → Snapshot

自主成长边界:
    - 允许: 自动记录 / 自动整理 / 自动生成报告
    - 禁止: 自动改变人格 / 目标 / 核心价值 / 高风险行为
"""
from backend.embodied.companion.rhythm.consolidation_scheduler import (
    ConsolidationScheduler,
    SchedulerError,
)
from backend.embodied.companion.rhythm.growth_rhythm import (
    GrowthRhythm,
    RhythmError,
)
from backend.embodied.companion.rhythm.growth_trigger import (
    TRIGGER_CONDITIONS,
    GrowthTrigger,
    TriggerError,
)
from backend.embodied.companion.rhythm.rhythm_audit import (
    RHYTHM_AUDIT_ACTIONS,
    RhythmAudit,
    RhythmAuditError,
)

__all__ = [
    "ConsolidationScheduler",
    "GrowthRhythm",
    "GrowthTrigger",
    "RHYTHM_AUDIT_ACTIONS",
    "RhythmAudit",
    "RhythmAuditError",
    "RhythmError",
    "SchedulerError",
    "TRIGGER_CONDITIONS",
    "TriggerError",
]
