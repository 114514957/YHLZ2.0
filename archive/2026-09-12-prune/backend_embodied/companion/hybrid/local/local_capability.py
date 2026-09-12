"""
YHLZ Embodied AI V6.8 - 本地能力 (Local Capability)

职责:
    - 本地能力执行器注册 (identity/memory/vision/embedding/
      basic_reasoning)
    - 每个本地能力: 名称/来源/可用性/延迟/成本/执行函数

设计原则:
    - 动态注册 (禁止硬编码)
    - 执行函数可注入 (Mock/真实)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)


class LocalCapabilityError(Exception):
    """本地能力操作异常"""


# 本地能力名 (可解释)
LOCAL_CAPABILITY_NAMES: list = [
    "identity",          # 身份查询
    "memory",            # 记忆检索
    "vision",            # 视觉检测
    "embedding",         # 本地嵌入
    "basic_reasoning",   # 基础推理
]


class LocalCapability:
    """本地能力描述 + 执行器"""

    def __init__(
        self,
        name: str,
        handler: Optional[Callable[[Dict[str, Any]],
                                   Dict[str, Any]]] = None,
        available: bool = True,
        latency_ms: int = 10,
        description: str = "",
    ):
        if name not in LOCAL_CAPABILITY_NAMES:
            raise LocalCapabilityError(
                f"非法本地能力名: {name} "
                f"(可选: {LOCAL_CAPABILITY_NAMES})"
            )
        self.id = "lcap_" + uuid.uuid4().hex[:8]
        self.name = str(name)
        self._handler = handler
        self.available = bool(available)
        self.latency_ms = int(latency_ms)
        self.description = str(description)
        self.call_count = 0

    def execute(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """执行本地能力 (无 handler → 规则默认结果)"""
        self.call_count += 1
        if self._handler is not None:
            return self._handler(request)
        return self._default_result(request)

    def _default_result(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """默认规则结果 (纯规则, 可解释)"""
        q = str(request.get("query", ""))
        return {
            "mode": "rule_based",
            "capability": self.name,
            "result": f"本地规则结果: {self.name} "
                      f"(query={q[:30]})",
            "processed_locally": True,
        }

    def to_dict(self) -> Dict[str, Any]:
        """能力字典"""
        return {
            "id": self.id,
            "name": self.name,
            "source": "local",
            "available": self.available,
            "latency_ms": self.latency_ms,
            "call_count": self.call_count,
            "description": self.description,
        }


def default_local_handlers() -> Dict[str, Callable]:
    """默认本地能力执行器集 (纯规则 Mock)"""
    def _identity(req):
        return {
            "mode": "rule_based",
            "capability": "identity",
            "result": "身份信息本地保存, 不对外传输",
            "privacy_safe": True,
        }

    def _memory(req):
        q = str(req.get("query", ""))
        return {
            "mode": "rule_based",
            "capability": "memory",
            "result": f"本地记忆检索: {q[:30]}",
            "records": [],
        }

    def _vision(req):
        return {
            "mode": "rule_based",
            "capability": "vision",
            "result": "本地视觉检测完成",
            "detections": [],
        }

    def _embedding(req):
        text = str(req.get("text", ""))
        return {
            "mode": "rule_based",
            "capability": "embedding",
            "result": f"本地嵌入生成 ({len(text)} 字符)",
            "dimension": 128,
        }

    def _basic(req):
        q = str(req.get("query", ""))
        return {
            "mode": "rule_based",
            "capability": "basic_reasoning",
            "result": f"本地基础推理: {q[:30]}",
            "answer": "本地规则推断",
        }

    return {
        "identity": _identity,
        "memory": _memory,
        "vision": _vision,
        "embedding": _embedding,
        "basic_reasoning": _basic,
    }


class LocalCapabilityRegistry:
    """本地能力注册表"""

    def __init__(self, enabled: bool = True):
        self._lock = threading.RLock()
        self._enabled = bool(enabled)
        self._caps: Dict[str, LocalCapability] = {}

    def register(self, cap: LocalCapability) -> LocalCapability:
        """注册本地能力 (同名覆盖)"""
        with self._lock:
            self._caps[cap.name] = cap
            return cap

    def register_defaults(self) -> int:
        """注册默认 5 项本地能力"""
        handlers = default_local_handlers()
        with self._lock:
            for name, handler in handlers.items():
                self._caps[name] = LocalCapability(
                    name=name, handler=handler,
                )
            return len(handlers)

    def get(self, name: str) -> Optional[Dict[str, Any]]:
        """查询能力"""
        with self._lock:
            cap = self._caps.get(name)
            return cap.to_dict() if cap is not None else None

    def execute(
        self, name: str, request: Dict[str, Any],
    ) -> Dict[str, Any]:
        """执行本地能力"""
        with self._lock:
            cap = self._caps.get(name)
            if cap is None:
                raise LocalCapabilityError(
                    f"本地能力未注册: {name}"
                )
            if not cap.available:
                raise LocalCapabilityError(
                    f"本地能力不可用: {name}"
                )
            start = time.time()
            result = cap.execute(request)
            result["capability_id"] = cap.id
            result["latency_ms"] = round(
                (time.time() - start) * 1000, 3,
            )
            return result

    def list_all(self) -> Dict[str, Any]:
        """全部本地能力"""
        with self._lock:
            return {
                "mode": "rule_based",
                "capabilities": [
                    c.to_dict()
                    for c in self._caps.values()
                ],
                "total": len(self._caps),
            }

    def stats(self) -> Dict[str, Any]:
        """本地能力统计"""
        with self._lock:
            return {
                "mode": "rule_based",
                "enabled": self._enabled,
                "capability_count": len(self._caps),
                "call_count": sum(
                    c.call_count for c in self._caps.values()
                ),
            }

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = len(self._caps)
            self._caps.clear()
            return n


__all__ = [
    "LOCAL_CAPABILITY_NAMES",
    "LocalCapability",
    "LocalCapabilityError",
    "LocalCapabilityRegistry",
    "default_local_handlers",
]
