"""
YHLZ Embodied AI V6.3 - 感知管道 (Perception Pipeline)

架构:
    AgentPipelineAdapter  (管道适配器: 感知帧 → Agent 输入)
        ├── PerceptionFrame    (感知帧: {type, content, verified, meaning, timestamp})
        └── PerceptionRouter   (感知路由: 类型 → 目标, 行动安全)

流程:
    Perception Frame → main_agent → reasoning → response

安全:
    - 未验证帧禁止行动
    - 行动敏感类型需额外确认
"""
from backend.embodied.companion.perception.pipeline.agent_pipeline_adapter import (
    AgentPipelineAdapter,
    PipelineAdapterError,
)
from backend.embodied.companion.perception.pipeline.perception_frame import (
    FRAME_TYPES,
    FrameError,
    PerceptionFrame,
)
from backend.embodied.companion.perception.pipeline.perception_router import (
    ACTION_SENSITIVE,
    ROUTE_TABLE,
    PerceptionRouter,
    RouterError,
)

__all__ = [
    "ACTION_SENSITIVE",
    "AgentPipelineAdapter",
    "FRAME_TYPES",
    "FrameError",
    "PerceptionFrame",
    "PerceptionRouter",
    "PipelineAdapterError",
    "ROUTE_TABLE",
    "RouterError",
]
