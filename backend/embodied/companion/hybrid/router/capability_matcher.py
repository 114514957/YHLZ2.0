"""
YHLZ Embodied AI V6.8 - 能力注册与匹配 (Capability Matcher)

职责:
    - 动态注册能力 (本地/云端)
    - 任务类型 → 能力需求 → 候选能力匹配

能力注册表示例:
    local:  identity / memory / vision / embedding / basic_reasoning
    cloud:  deep_reasoning / creative / analysis

设计原则:
    - 动态注册 (禁止硬编码)
    - 匹配可解释
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class MatcherError(Exception):
    """能力匹配操作异常"""


# 能力来源 (可解释)
CAPABILITY_SOURCES: list = ["local", "cloud"]

# 任务类型 → 能力需求 (可解释)
TASK_CAPABILITIES: Dict[str, list] = {
    "identity_query": ["identity"],
    "memory_retrieval": ["memory"],
    "permission_check": ["identity"],
    "vision_detection": ["vision"],
    "basic_reasoning": ["basic_reasoning"],
    "deep_reasoning": ["deep_reasoning", "basic_reasoning"],
    "creative_exploration": ["creative", "deep_reasoning"],
    "analysis": ["analysis", "deep_reasoning"],
    "research": ["analysis", "deep_reasoning"],
    "architecture_design": ["deep_reasoning", "analysis"],
    "document_understanding": ["deep_reasoning", "analysis"],
}


class Capability:
    """能力描述 (动态注册)"""

    def __init__(
        self,
        name: str,
        source: str = "local",
        available: bool = True,
        latency_ms: int = 10,
        cost_per_call: float = 0.0,
        description: str = "",
    ):
        if source not in CAPABILITY_SOURCES:
            raise MatcherError(
                f"非法能力来源: {source} "
                f"(可选: {CAPABILITY_SOURCES})"
            )
        if not name:
            raise MatcherError("能力名称不能为空")
        self.id = "cap_" + uuid.uuid4().hex[:8]
        self.name = str(name)
        self.source = str(source)
        self.available = bool(available)
        self.latency_ms = int(latency_ms)
        self.cost_per_call = float(cost_per_call)
        self.description = str(description)

    def to_dict(self) -> Dict[str, Any]:
        """能力字典"""
        return {
            "id": self.id,
            "name": self.name,
            "source": self.source,
            "available": self.available,
            "latency_ms": self.latency_ms,
            "cost_per_call": self.cost_per_call,
            "description": self.description,
        }


class CapabilityMatcher:
    """能力匹配器 (注册 + 匹配)

    用法:
        matcher = CapabilityMatcher()
        matcher.register(Capability("identity", "local"))
        result = matcher.match("identity_query")
    """

    def __init__(self, enabled: bool = True):
        self._lock = threading.RLock()
        self._enabled = bool(enabled)
        self._capabilities: Dict[str, Capability] = {}
        self._match_count = 0

    # ── 注册 ─────────────────────────────────────────────────────
    def register(self, capability: Capability) -> Capability:
        """注册能力 (同名覆盖)"""
        with self._lock:
            self._capabilities[capability.name] = capability
            return capability

    def unregister(self, name: str) -> bool:
        """注销能力"""
        with self._lock:
            return self._capabilities.pop(name, None) is not None

    def get(self, name: str) -> Optional[Capability]:
        """查询能力"""
        with self._lock:
            cap = self._capabilities.get(name)
            return cap.to_dict() if cap is not None else None

    # ── 匹配 ─────────────────────────────────────────────────────
    def match(
        self,
        task_type: str,
    ) -> Dict[str, Any]:
        """任务类型 → 候选能力 (本地优先排序)

        Args:
            task_type: 任务类型

        Returns:
            {
                'matched': [...], 'local': [...], 'cloud': [...],
                'missing': [...], 'reason', 'mode',
            }
        """
        with self._lock:
            if not self._enabled:
                return {"mode": "rule_based", "matched": [],
                        "local": [], "cloud": [],
                        "missing": [], "reason": "能力匹配停用"}
            needs = TASK_CAPABILITIES.get(task_type, [])
            matched: List[Dict[str, Any]] = []
            missing: List[str] = []
            for need in needs:
                cap = self._capabilities.get(need)
                if cap is not None and cap.available:
                    matched.append(cap.to_dict())
                else:
                    missing.append(need)
            local = [m for m in matched
                     if m["source"] == "local"]
            cloud = [m for m in matched
                     if m["source"] == "cloud"]
            self._match_count += 1
            return {
                "mode": "rule_based",
                "matched": matched,
                "local": local,
                "cloud": cloud,
                "missing": missing,
                "reason": (
                    f"任务 '{task_type}' 需求 {needs}, "
                    f"匹配 {len(matched)}, 缺失 {missing}"
                ),
            }

    # ── 默认注册表 ──────────────────────────────────────────────
    def register_defaults(self) -> int:
        """注册默认能力集 (local 5 + cloud 3)"""
        defaults = [
            Capability("identity", "local", latency_ms=2,
                       description="身份查询"),
            Capability("memory", "local", latency_ms=5,
                       description="记忆检索"),
            Capability("vision", "local", latency_ms=30,
                       description="视觉检测"),
            Capability("embedding", "local", latency_ms=20,
                       description="本地嵌入"),
            Capability("basic_reasoning", "local",
                       latency_ms=10,
                       description="基础推理"),
            Capability("deep_reasoning", "cloud",
                       latency_ms=500,
                       cost_per_call=0.02,
                       description="深度推理"),
            Capability("creative", "cloud", latency_ms=800,
                       cost_per_call=0.05,
                       description="创造探索"),
            Capability("analysis", "cloud", latency_ms=600,
                       cost_per_call=0.03,
                       description="专业分析"),
        ]
        with self._lock:
            for cap in defaults:
                self._capabilities[cap.name] = cap
            return len(defaults)

    # ── 查询 ─────────────────────────────────────────────────────
    def list_all(self) -> Dict[str, Any]:
        """全部能力 (按来源分组)"""
        with self._lock:
            local = [
                c.to_dict()
                for c in self._capabilities.values()
                if c.source == "local"
            ]
            cloud = [
                c.to_dict()
                for c in self._capabilities.values()
                if c.source == "cloud"
            ]
            return {
                "mode": "rule_based",
                "local": local,
                "cloud": cloud,
                "total": len(local) + len(cloud),
            }

    def stats(self) -> Dict[str, Any]:
        """匹配统计"""
        with self._lock:
            return {
                "mode": "rule_based",
                "enabled": self._enabled,
                "match_count": self._match_count,
                "capability_count": len(self._capabilities),
                "sources": list(CAPABILITY_SOURCES),
            }

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = len(self._capabilities)
            self._capabilities.clear()
            self._match_count = 0
            return n


__all__ = [
    "CAPABILITY_SOURCES",
    "Capability",
    "CapabilityMatcher",
    "MatcherError",
    "TASK_CAPABILITIES",
]
