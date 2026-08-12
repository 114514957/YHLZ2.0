"""
YHLZ Embodied AI V6.3 - Agent 管道适配器 (Agent Pipeline Adapter)

职责:
    - 感知帧 → Agent Pipeline 输入 (main_agent → reasoning → response)
    - 安全: 感知帧只作为观察输入, 不直接触发 Action

流程:
    Perception Frame → main_agent → reasoning → response

安全边界:
    - 感知不直接改变人格
    - 感知不直接调用 Action (经路由 action_allowed 判断)

设计原则:
    - 只读注入 (不修改 Agent 核心)
    - 纯规则, 无黑盒
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

from backend.embodied.companion.perception.pipeline.perception_frame import (
    PerceptionFrame,
)
from backend.embodied.companion.perception.pipeline.perception_router import (
    PerceptionRouter,
)

logger = logging.getLogger(__name__)


class PipelineAdapterError(Exception):
    """管道适配器操作异常"""


class AgentPipelineAdapter:
    """Agent 管道适配器

    用法:
        adapter = AgentPipelineAdapter(router)
        result = adapter.ingest(frame)
    """

    def __init__(
        self,
        router: Optional[PerceptionRouter] = None,
        enabled: bool = True,
    ):
        self._lock = threading.RLock()
        self._router = router or PerceptionRouter()
        self._enabled = bool(enabled)
        self._ingested: List[Dict[str, Any]] = []

    # ── 注入感知帧 ───────────────────────────────────────────────
    def ingest(
        self,
        frame: PerceptionFrame,
        now: Optional[float] = None,
    ) -> Dict[str, Any]:
        """注入感知帧到管道

        Args:
            frame: 感知帧

        Returns:
            {
                'ingest_id', 'frame', 'route', 'agent_input',
                'action_blocked', 'mode',
            }
        """
        with self._lock:
            now = now if now is not None else time.time()
            if not self._enabled:
                return {
                    "ingest_id": "ing_" + uuid.uuid4().hex[:8],
                    "frame": frame.to_dict(),
                    "route": None,
                    "agent_input": None,
                    "action_blocked": True,
                    "reason": "管道感知停用",
                    "mode": "rule_based",
                }
            route = self._router.route(frame)
            # Agent 输入 (观察上下文, 不含行动指令)
            agent_input = {
                "perception_frame": frame.to_dict(),
                "route_target": route["target"],
                "observed_at": now,
            }
            result = {
                "ingest_id": "ing_" + uuid.uuid4().hex[:8],
                "frame": frame.to_dict(),
                "route": route,
                "agent_input": agent_input,
                "action_blocked": not route["action_allowed"],
                "mode": "rule_based",
            }
            self._ingested.append(result)
            return dict(result)

    # ── 查询 ─────────────────────────────────────────────────────
    def stats(self) -> Dict[str, Any]:
        """管道统计"""
        with self._lock:
            ingested = list(self._ingested)
        verified_count = sum(
            1 for i in ingested if i["frame"]["verified"]
        )
        blocked_count = sum(
            1 for i in ingested if i["action_blocked"]
        )
        return {
            "mode": "rule_based",
            "enabled": self._enabled,
            "frame_count": len(ingested),
            "verified_count": verified_count,
            "action_blocked_count": blocked_count,
            "router": self._router.stats(),
        }

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = len(self._ingested)
            self._ingested.clear()
            return n


__all__ = [
    "AgentPipelineAdapter",
    "PipelineAdapterError",
]
