"""
YHLZ Embodied AI V6.8 - API 网关 (API Gateway)

职责:
    - 统一管理模型端点 (OpenAI/Claude/Gemini/本地/自定义)
    - request() / response() 统一接口
    - 所有调用必须记录 (审计 + 成本)

设计原则:
    - 模型动态注册 (禁止硬编码)
    - Mock 优先 (未配置真实端点 → Mock 响应)
    - 所有调用记录 (可追踪/可回放)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)


class GatewayError(Exception):
    """API 网关操作异常"""


# 模型家族 (可解释)
MODEL_FAMILIES: list = [
    "openai",     # OpenAI
    "claude",     # Anthropic Claude
    "gemini",     # Google Gemini
    "local",      # 本地模型
    "custom",     # 自定义模型
]


class ModelEndpoint:
    """模型端点 (动态注册)"""

    def __init__(
        self,
        model: str,
        family: str = "openai",
        cost_per_1k_tokens: float = 0.0,
        max_tokens: int = 4096,
        handler: Optional[Callable[[Dict[str, Any]],
                                   Dict[str, Any]]] = None,
    ):
        if family not in MODEL_FAMILIES:
            raise GatewayError(
                f"非法模型家族: {family} "
                f"(可选: {MODEL_FAMILIES})"
            )
        if not model:
            raise GatewayError("模型名不能为空")
        self.model = str(model)
        self.family = str(family)
        self.cost_per_1k_tokens = float(cost_per_1k_tokens)
        self.max_tokens = int(max_tokens)
        self._handler = handler

    def call(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """调用模型 (无 handler → Mock 响应)"""
        if self._handler is not None:
            return self._handler(payload)
        return self._mock_response(payload)

    def _mock_response(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Mock 响应 (纯规则, 测试与离线可用)"""
        prompt = str(payload.get("prompt", ""))[:50]
        tokens = max(
            1, len(str(payload.get("prompt", ""))) // 4,
        )
        return {
            "mode": "mock",
            "model": self.model,
            "family": self.family,
            "content": f"[{self.family} mock] {prompt}",
            "usage": {"prompt_tokens": tokens,
                      "completion_tokens": tokens,
                      "total_tokens": tokens * 2},
        }

    def to_dict(self) -> Dict[str, Any]:
        """端点字典"""
        return {
            "model": self.model,
            "family": self.family,
            "cost_per_1k_tokens": self.cost_per_1k_tokens,
            "max_tokens": self.max_tokens,
        }


class ApiGateway:
    """API 网关 (模型统一管理 + 全量记录)

    用法:
        gateway = ApiGateway()
        gateway.register_model(ModelEndpoint(
            "deepseek-r1", "openai", cost_per_1k_tokens=0.002))
        result = gateway.request("deepseek-r1", {"prompt": "..."})
    """

    def __init__(self, enabled: bool = True,
                 max_records: int = 2000):
        if max_records <= 0:
            raise GatewayError(
                f"max_records 必须 > 0, 当前: {max_records}"
            )
        self._lock = threading.RLock()
        self._enabled = bool(enabled)
        self._max_records = int(max_records)
        self._models: Dict[str, ModelEndpoint] = {}
        self._records: list = []
        self._request_count = 0

    # ── 注册 ─────────────────────────────────────────────────────
    def register_model(self, endpoint: ModelEndpoint) -> str:
        """注册模型端点 (同名覆盖)"""
        with self._lock:
            self._models[endpoint.model] = endpoint
            return endpoint.model

    def unregister_model(self, model: str) -> bool:
        """注销模型"""
        with self._lock:
            return self._models.pop(model, None) is not None

    def register_defaults(self) -> int:
        """注册默认模型集 (4 家 + 本地)"""
        defaults = [
            ModelEndpoint(
                "openai-gpt4o", "openai",
                cost_per_1k_tokens=0.01),
            ModelEndpoint(
                "claude-sonnet", "claude",
                cost_per_1k_tokens=0.008),
            ModelEndpoint(
                "gemini-pro", "gemini",
                cost_per_1k_tokens=0.005),
            ModelEndpoint(
                "local-qwen", "local",
                cost_per_1k_tokens=0.0),
            ModelEndpoint(
                "custom-r1", "custom",
                cost_per_1k_tokens=0.002),
        ]
        with self._lock:
            for ep in defaults:
                self._models[ep.model] = ep
            return len(defaults)

    # ── 请求 / 响应 ─────────────────────────────────────────────
    def request(
        self,
        model: str,
        payload: Optional[Dict[str, Any]] = None,
        now: Optional[float] = None,
    ) -> Dict[str, Any]:
        """发起模型调用 (必须记录)

        Args:
            model: 模型名 (已注册)
            payload: 请求载荷 (prompt 等)

        Returns:
            响应 + usage + record_id
        """
        with self._lock:
            now = now if now is not None else time.time()
            if not self._enabled:
                return {
                    "ok": False,
                    "reason": "API 网关停用",
                    "mode": "error_frame",
                }
            ep = self._models.get(model)
            if ep is None:
                return {
                    "ok": False,
                    "reason": f"模型未注册: {model}",
                    "mode": "error_frame",
                }
            try:
                payload = dict(payload or {})
                start = time.time()
                resp = ep.call(payload)
                latency = round(
                    (time.time() - start) * 1000, 3,
                )
                resp.setdefault("usage", {})
                tokens = int(resp["usage"].get(
                    "total_tokens", 0,
                ))
                cost = round(
                    tokens / 1000.0 * ep.cost_per_1k_tokens, 6,
                )
                record = {
                    "record_id": "gw_" + uuid.uuid4().hex[:8],
                    "time": now,
                    "model": model,
                    "family": ep.family,
                    "payload_keys": list(payload.keys()),
                    "tokens": tokens,
                    "cost": cost,
                    "latency_ms": latency,
                }
                self._records.append(record)
                if len(self._records) > self._max_records:
                    self._records = \
                        self._records[-self._max_records:]
                self._request_count += 1
                resp["record_id"] = record["record_id"]
                resp["cost"] = cost
                resp["latency_ms"] = latency
                return resp
            except Exception as e:
                logger.warning(f"[Hybrid] 网关调用异常: {e}")
                return {
                    "ok": False,
                    "reason": f"网关调用失败: {e}",
                    "model": model,
                    "mode": "error_frame",
                }

    def response(self, request_result: Dict[str, Any],
                 content: str) -> Dict[str, Any]:
        """规范化响应 (供上层消费)"""
        return {
            "record_id": request_result.get("record_id", ""),
            "content": str(content),
            "mode": "rule_based",
        }

    # ── 查询 ─────────────────────────────────────────────────────
    def models(self) -> Dict[str, Any]:
        """已注册模型"""
        with self._lock:
            return {
                "mode": "rule_based",
                "models": [
                    m.to_dict()
                    for m in self._models.values()
                ],
                "total": len(self._models),
            }

    def records(self, limit: int = 100) -> list:
        """调用记录 (可回放)"""
        with self._lock:
            recent = list(reversed(self._records))
            if limit > 0:
                recent = recent[:limit]
            return [dict(r) for r in recent]

    def stats(self) -> Dict[str, Any]:
        """网关统计"""
        with self._lock:
            total_cost = sum(r["cost"] for r in self._records)
            total_tokens = sum(r["tokens"]
                               for r in self._records)
            return {
                "mode": "rule_based",
                "enabled": self._enabled,
                "request_count": self._request_count,
                "record_count": len(self._records),
                "total_tokens": total_tokens,
                "total_cost": round(total_cost, 6),
                "model_count": len(self._models),
            }

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = len(self._records)
            self._records.clear()
            self._request_count = 0
            return n


__all__ = [
    "ApiGateway",
    "GatewayError",
    "MODEL_FAMILIES",
    "ModelEndpoint",
]
