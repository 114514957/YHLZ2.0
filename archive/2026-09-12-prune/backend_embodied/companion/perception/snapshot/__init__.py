"""
YHLZ Embodied AI V6.4 - 感知快照层 (Perception Snapshot Layer)

架构:
    PerceptionStatsSnapshot  (感知统计快照: 收集/恢复/兼容)

作用:
    - SNAPSHOT_DOMAIN: perception_stats
    - 保存: 输入/验证/拒绝/批准/反思统计
    - 兼容旧快照 (无该域 → 跳过)
"""
from backend.embodied.companion.perception.snapshot.perception_stats_snapshot import (
    PerceptionStatsSnapshot,
    SnapshotError,
)

__all__ = [
    "PerceptionStatsSnapshot",
    "SnapshotError",
]
