"""
YHLZ Vision Memory V1.0

视觉记忆层:
    保存 / 检索 / 管理视觉理解结果, 建立长期视觉上下文。

模块:
    - schema:     VisualMemoryRecord / MemoryQuery / 枚举
    - interface:  MemoryStore 抽象接口
    - manager:    Store 注册表 + 路由 + 单例
    - permission: 权限控制 (默认拒绝)
    - logger:     日志 + 性能指标 (save/query_latency, hit_rate)
    - service:    统一入口 (保存 UnderstandingResult / 检索 / 上下文)
    - tools:      Agent 工具注册
    - stores:     存储实现 (SQLite / 内存)
"""
from backend.vision.memory.schema import (
    MemoryImportance,
    MemoryQuery,
    MemoryStatus,
    MemoryType,
    VisualMemoryRecord,
)

__version__ = "1.0.0"

__all__ = [
    "VisualMemoryRecord",
    "MemoryQuery",
    "MemoryType",
    "MemoryImportance",
    "MemoryStatus",
]
