"""
YHLZ Embodied AI V6.3 - 感知路由 (Perception Router)

职责:
    - 感知帧路由: 帧类型 → 目标管道/Agent
    - 安全: 未验证帧禁止路由到行动

路由规则 (可解释):
    - verified=False → 仅可进入观察 (不可行动)
    - vision/ocr → perception_agent
    - audio → audio_agent (预留)
    - text → reasoning_agent

设计原则:
    - 纯规则 (无黑盒)
    - 未验证帧不能触发行动
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List, Optional

from backend.embodied.companion.perception.pipeline.perception_frame import (
    PerceptionFrame,
)

logger = logging.getLogger(__name__)


class RouterError(Exception):
    """感知路由操作异常"""


# 类型 → 目标 Agent (可解释)
ROUTE_TABLE: Dict[str, str] = {
    "vision": "perception_agent",
    "ocr": "perception_agent",
    "object": "perception_agent",
    "audio": "audio_agent",
    "text": "reasoning_agent",
}

# 行动敏感类型 (未验证禁止路由) (可解释)
ACTION_SENSITIVE: List[str] = ["object"]


class PerceptionRouter:
    """感知路由

    用法:
        router = PerceptionRouter()
        route = router.route(frame)
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._routes: List[Dict[str, Any]] = []

    # ── 路由 ─────────────────────────────────────────────────────
    def route(self, frame: PerceptionFrame) -> Dict[str, Any]:
        """路由感知帧

        Args:
            frame: 感知帧

        Returns:
            {
                'route_id', 'frame_id', 'target',
                'action_allowed', 'reason', 'mode',
            }
        """
        with self._lock:
            ok, reason = frame.validate()
            if not ok:
                return {
                    "route_id": "rt_" + __import__(
                        "uuid").uuid4().hex[:8],
                    "frame_id": frame.frame_id,
                    "target": "invalid",
                    "action_allowed": False,
                    "reason": f"帧非法: {reason}",
                    "mode": "rule_based",
                }
            kind = str(frame.content.get("kind", frame.type))
            target = ROUTE_TABLE.get(kind, ROUTE_TABLE.get(
                frame.type, "perception_agent"))
            # 行动安全: 未验证帧 + 行动敏感类型 → 禁止行动
            action_allowed = True
            action_reason = "帧已验证"
            if not frame.verified:
                action_allowed = False
                action_reason = "帧未验证, 禁止行动"
            elif kind in ACTION_SENSITIVE:
                action_allowed = False
                action_reason = f"行动敏感类型 '{kind}', 需额外确认"
            route = {
                "route_id": "rt_" + __import__(
                    "uuid").uuid4().hex[:8],
                "frame_id": frame.frame_id,
                "target": target,
                "action_allowed": action_allowed,
                "reason": (
                    f"路由到 {target}; {action_reason}"
                ),
                "mode": "rule_based",
            }
            self._routes.append(route)
            return dict(route)

    # ── 查询 ─────────────────────────────────────────────────────
    def stats(self) -> Dict[str, Any]:
        """路由统计"""
        with self._lock:
            routes = list(self._routes)
        by_target: Dict[str, int] = {}
        for r in routes:
            by_target[r["target"]] = by_target.get(
                r["target"], 0,
            ) + 1
        return {
            "mode": "rule_based",
            "route_count": len(routes),
            "by_target": by_target,
            "route_table": dict(ROUTE_TABLE),
        }

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = len(self._routes)
            self._routes.clear()
            return n


__all__ = [
    "ACTION_SENSITIVE",
    "ROUTE_TABLE",
    "PerceptionRouter",
    "RouterError",
]
