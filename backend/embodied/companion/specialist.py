"""
YHLZ Embodied AI V5.0 - 专业 Agent 注册中心 (Specialist Agent Registry)

职责:
    - 能力域注册: 专业 Agent 按能力域注册 (perception / reasoning /
      experience / planning / long_horizon / governance)
    - 能力查询: 按能力域 / 全部 / 状态查询
    - 生命周期: 注册 / 注销 / 启用 / 停用

设计原则:
    - 每个专业 Agent 是一个可调用处理器 (handle 方法), 只处理能力域任务
    - 专业 Agent 不拥有独立人格 (人格由 Main Companion Agent 统一保持)
    - 纯规则分派 (确定性), 禁止自由协商
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class SpecialistError(Exception):
    """专业 Agent 注册中心操作异常"""


# 能力域白名单 (可解释)
SPECIALIST_CAPABILITIES: List[str] = [
    "perception",    # 感知: World Model / Observe / Scene
    "reasoning",     # 推理: Causal / Prediction / Events
    "experience",    # 经验: Policy Table / Strategy Selection
    "planning",      # 规划: Cross Goal Planner / Budget
    "long_horizon",  # 长期任务: Long Horizon Planner / Milestone
    "governance",    # 治理: Strategy Governance / Health
    "execution",     # 执行: Goal Execution (V5.3, 经 Permission)
]


class SpecialistAgent:
    """专业 Agent (能力域处理器)

    Attributes:
        name:        Agent 名称 (如 'perception_agent')
        capability:  能力域 (SPECIALIST_CAPABILITIES 之一)
        handler:     处理函数 (request: Dict → Dict)
        description: 能力描述
        enabled:     是否启用
        created_at:  注册时间
    """

    def __init__(
        self,
        name: str,
        capability: str,
        handler: Callable[[Dict[str, Any]], Dict[str, Any]],
        description: str = "",
    ):
        if capability not in SPECIALIST_CAPABILITIES:
            raise SpecialistError(
                f"非法能力域: {capability} (可选: {SPECIALIST_CAPABILITIES})"
            )
        if handler is None or not callable(handler):
            raise SpecialistError(f"专业 Agent 处理器必须可调用: {name}")
        self.name = name
        self.capability = capability
        self.handler = handler
        self.description = description
        self.enabled = True
        self.created_at = time.time()
        self.invocations = 0
        self.last_error: Optional[str] = None

    def invoke(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """调用处理器 (带调用计数 + 错误捕获)"""
        try:
            result = self.handler(request) or {}
            self.invocations += 1
            self.last_error = None
            return result
        except Exception as e:
            self.last_error = str(e)
            self.invocations += 1
            logger.error(f"[Specialist] {self.name} 处理失败: {e}")
            return {
                "error": str(e),
                "agent": self.name,
                "capability": self.capability,
            }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "capability": self.capability,
            "description": self.description,
            "enabled": self.enabled,
            "invocations": self.invocations,
            "last_error": self.last_error,
            "created_at": self.created_at,
        }


class SpecialistRegistry:
    """专业 Agent 注册中心

    用法:
        registry = SpecialistRegistry()
        registry.register(SpecialistAgent("perception_agent", "perception", handler))
        agent = registry.get("perception_agent")
        agents = registry.by_capability("perception")
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._agents: Dict[str, SpecialistAgent] = {}

    # ── 注册 ──────────────────────────────────────────────────────
    def register(self, agent: SpecialistAgent) -> SpecialistAgent:
        """注册专业 Agent (同能力域只保留一个, 可覆盖)"""
        with self._lock:
            if agent.name in self._agents:
                logger.info(f"[Specialist] 覆盖注册: {agent.name}")
            self._agents[agent.name] = agent
            logger.info(
                f"[Specialist] 注册: {agent.name} "
                f"(capability={agent.capability})"
            )
            return agent

    def register_simple(
        self,
        name: str,
        capability: str,
        handler: Callable[[Dict[str, Any]], Dict[str, Any]],
        description: str = "",
    ) -> SpecialistAgent:
        """快捷注册 (构造 + 注册)"""
        agent = SpecialistAgent(
            name=name, capability=capability,
            handler=handler, description=description,
        )
        return self.register(agent)

    def unregister(self, name: str) -> bool:
        """注销专业 Agent"""
        with self._lock:
            return self._agents.pop(name, None) is not None

    def clear(self) -> int:
        """清空注册表 (测试隔离)"""
        with self._lock:
            n = len(self._agents)
            self._agents.clear()
            return n

    # ── 查询 ──────────────────────────────────────────────────────
    def get(self, name: str) -> Optional[SpecialistAgent]:
        with self._lock:
            return self._agents.get(name)

    def all(self) -> List[SpecialistAgent]:
        with self._lock:
            return list(self._agents.values())

    def enabled_agents(self) -> List[SpecialistAgent]:
        """已启用的专业 Agent"""
        with self._lock:
            return [a for a in self._agents.values() if a.enabled]

    def by_capability(self, capability: str) -> List[SpecialistAgent]:
        """按能力域查询"""
        with self._lock:
            return [
                a for a in self._agents.values()
                if a.capability == capability and a.enabled
            ]

    def set_enabled(self, name: str, enabled: bool) -> Optional[SpecialistAgent]:
        """启用 / 停用"""
        with self._lock:
            agent = self._agents.get(name)
            if agent is None:
                return None
            agent.enabled = enabled
            return agent

    def count(self) -> int:
        with self._lock:
            return len(self._agents)

    def snapshot(self) -> Dict[str, Any]:
        """注册中心快照 (Agent 清单)"""
        with self._lock:
            return {
                "mode": "rule_based",
                "total": len(self._agents),
                "agents": [a.to_dict() for a in self._agents.values()],
            }


__all__ = [
    "SPECIALIST_CAPABILITIES",
    "SpecialistAgent",
    "SpecialistError",
    "SpecialistRegistry",
]
