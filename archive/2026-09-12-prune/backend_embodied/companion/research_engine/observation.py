"""
YHLZ Embodied AI V9.0 - 观察层 (Observation Layer)

职责:
    - 从环境/经验/知识缺口/用户需求/长期目标收集观察
    - 为问题发现提供输入

观察类型 (可解释):
    - knowledge_gap    知识缺口
    - user_need        用户需求
    - long_term_goal   长期目标
    - unresolved       未解决问题

设计原则:
    - 纯规则观察 (无黑盒)
    - 观察带来源 (可追溯)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ObservationError(Exception):
    """观察层操作异常"""


# 观察类型 (可解释)
OBSERVATION_TYPES: list = [
    "knowledge_gap",    # 知识缺口
    "user_need",        # 用户需求
    "long_term_goal",   # 长期目标
    "unresolved",       # 未解决问题
]


class ObservationLayer:
    """观察层 (输入采集)

    用法:
        layer = ObservationLayer()
        layer.observe("user_need", "提升伙伴体验",
                      source="user")
        observations = layer.observations()
    """

    def __init__(self, enabled: bool = True,
                 max_records: int = 1000):
        if max_records <= 0:
            raise ObservationError(
                f"max_records 必须 > 0, 当前: {max_records}"
            )
        self._lock = threading.RLock()
        self._enabled = bool(enabled)
        self._max_records = int(max_records)
        self._observations: list = []

    # ── 观察 ─────────────────────────────────────────────────────
    def observe(
        self,
        obs_type: str,
        content: str,
        source: str = "system",
        now: Optional[float] = None,
    ) -> Dict[str, Any]:
        """采集一条观察"""
        if obs_type not in OBSERVATION_TYPES:
            raise ObservationError(
                f"非法观察类型: {obs_type} "
                f"(可选: {OBSERVATION_TYPES})"
            )
        with self._lock:
            now = now if now is not None else time.time()
            if not self._enabled:
                return {
                    "mode": "error_frame",
                    "ok": False,
                    "reason": "观察层停用",
                }
            obs = {
                "observation_id": "ob_" +
                uuid.uuid4().hex[:8],
                "type": obs_type,
                "content": str(content or ""),
                "source": str(source or ""),
                "timestamp": now,
            }
            self._observations.append(obs)
            if len(self._observations) > self._max_records:
                self._observations = \
                    self._observations[-self._max_records:]
            return dict(obs)

    def from_knowledge_gaps(
        self,
        gaps: List[str],
        source: str = "knowledge_graph",
    ) -> int:
        """从知识缺口批量观察"""
        n = 0
        for gap in gaps or []:
            if gap:
                self.observe(
                    "knowledge_gap", str(gap), source,
                )
                n += 1
        return n

    # ── 查询 ─────────────────────────────────────────────────────
    def observations(
        self, obs_type: Optional[str] = None,
        limit: int = 50,
    ) -> list:
        """观察列表"""
        with self._lock:
            items = [
                dict(o) for o in self._observations
                if obs_type is None or o["type"] == obs_type
            ]
            recent = list(reversed(items))
            if limit > 0:
                recent = recent[:limit]
            return recent

    def stats(self) -> Dict[str, Any]:
        """观察统计"""
        with self._lock:
            by_type: Dict[str, int] = {}
            for o in self._observations:
                by_type[o["type"]] = by_type.get(
                    o["type"], 0,
                ) + 1
            return {
                "mode": "rule_based",
                "enabled": self._enabled,
                "observation_count": len(self._observations),
                "by_type": by_type,
            }

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = len(self._observations)
            self._observations.clear()
            return n


__all__ = [
    "OBSERVATION_TYPES",
    "ObservationError",
    "ObservationLayer",
]
