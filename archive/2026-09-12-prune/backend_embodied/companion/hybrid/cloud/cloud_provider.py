"""
YHLZ Embodied AI V6.8 - 云端智能提供器 (Cloud Provider)

职责:
    - 云端能力执行门面 (负责扩展: 深度推理/创造/专业分析)
    - 通过 ApiGateway 统一调用模型

原则 (云端不是核心):
    - 任何云端结果不能直接改变身份/核心价值/权限/记忆
    - 必须经过验证 (ResultValidator)
    - 云端结果默认临时信息

设计原则:
    - Mock 优先 (未配置真实端点 → Mock 响应)
    - 异常不外抛 (结构化错误帧)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Dict, Optional

from backend.embodied.companion.hybrid.cloud.api_gateway import (
    ApiGateway,
)

logger = logging.getLogger(__name__)


class CloudProviderError(Exception):
    """云端智能提供器操作异常"""


# 云端能力 → 默认模型 (可解释)
CLOUD_CAPABILITY_MODELS: Dict[str, str] = {
    "deep_reasoning": "custom-r1",
    "creative": "openai-gpt4o",
    "analysis": "claude-sonnet",
}


class CloudProvider:
    """云端智能提供器

    用法:
        provider = CloudProvider(gateway=gateway)
        result = provider.execute("deep_reasoning",
                                  {"prompt": "..."})
    """

    def __init__(
        self,
        gateway: Optional[ApiGateway] = None,
        enabled: bool = True,
    ):
        self._lock = threading.RLock()
        self._enabled = bool(enabled)
        self._gateway = gateway or ApiGateway()
        self._execute_count = 0
        self._capability_distribution: Dict[str, int] = {}

    # ── 执行 ─────────────────────────────────────────────────────
    def execute(
        self,
        capability: str,
        request: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """执行云端能力 (经 API 网关, 全量记录)

        Args:
            capability: 能力名 (deep_reasoning/creative/analysis)
            request: 请求 (prompt 等)

        Returns:
            响应 + record_id + cost (云端结果默认临时)
        """
        with self._lock:
            if not self._enabled:
                return {
                    "provider": "cloud",
                    "capability": capability,
                    "ok": False,
                    "reason": "云端智能提供器停用",
                    "mode": "error_frame",
                }
            model = CLOUD_CAPABILITY_MODELS.get(capability)
            if model is None:
                return {
                    "provider": "cloud",
                    "capability": capability,
                    "ok": False,
                    "reason": f"未知云端能力: {capability}",
                    "mode": "error_frame",
                }
            resp = self._gateway.request(
                model, request or {},
            )
            self._execute_count += 1
            self._capability_distribution[capability] = \
                self._capability_distribution.get(
                    capability, 0,
                ) + 1
            resp["provider"] = "cloud"
            resp["capability"] = capability
            resp["temporary"] = True  # 云端结果默认临时
            return resp

    # ── 查询 ─────────────────────────────────────────────────────
    def stats(self) -> Dict[str, Any]:
        """云端提供器统计"""
        with self._lock:
            return {
                "mode": "rule_based",
                "enabled": self._enabled,
                "provider": "cloud",
                "execute_count": self._execute_count,
                "capability_distribution": dict(
                    self._capability_distribution,
                ),
                "capabilities": list(
                    CLOUD_CAPABILITY_MODELS.keys(),
                ),
                "gateway": self._gateway.stats(),
            }

    def records(self, limit: int = 100) -> list:
        """云端调用记录"""
        return self._gateway.records(limit=limit)

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = self._gateway.clear()
            self._execute_count = 0
            self._capability_distribution = {}
            return n


__all__ = [
    "CLOUD_CAPABILITY_MODELS",
    "CloudProvider",
    "CloudProviderError",
]
