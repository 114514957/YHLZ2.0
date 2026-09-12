"""
YHLZ Embodied AI V6.8 - 混合智能层 (Hybrid Intelligence Layer)

职责:
    - 智能资源调度门面 (本地 + 云端 + 混合)
    - 流程:
      Task Context → Classify → Route → Execute (Local/Cloud/
      Hybrid) → Validate → Audit

原则:
    - 本地负责存在 (身份/记忆/安全/用户数据/实时感知)
    - 云端负责扩展 (深度推理/大规模知识/创造/专业分析)
    - 云端不是核心 (结果必须验证, 不能直接改变身份/记忆)
    - 所有调用必须审计 (可查询/可追踪/可回放)

禁止:
    - 云端成为核心人格
    - API 结果直接进入身份
    - 绕过 Identity Guard
    - 隐藏调用成本
    - 黑盒路由

设计原则:
    - 纯规则调度 (可解释)
    - Mock 优先 (外部能力可注入真实 Adapter)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import uuid
from typing import Any, Dict, Optional

from backend.embodied.companion.hybrid.router.capability_matcher import (
    CapabilityMatcher,
)
from backend.embodied.companion.hybrid.router.routing_engine import (
    RoutingEngine,
)
from backend.embodied.companion.hybrid.router.task_classifier import (
    TaskClassifier,
)
from backend.embodied.companion.hybrid.local.local_capability import (
    LocalCapability,
)
from backend.embodied.companion.hybrid.local.local_provider import (
    LocalProvider,
)
from backend.embodied.companion.hybrid.cloud.cloud_provider import (
    CloudProvider,
)
from backend.embodied.companion.hybrid.cloud.api_gateway import (
    ApiGateway,
    ModelEndpoint,
)
from backend.embodied.companion.hybrid.policy.privacy_policy import (
    PrivacyPolicy,
)
from backend.embodied.companion.hybrid.policy.cost_policy import (
    CostPolicy,
)
from backend.embodied.companion.hybrid.policy.routing_policy import (
    RoutingPolicy,
)
from backend.embodied.companion.hybrid.validation.result_validator import (
    ResultValidator,
)
from backend.embodied.companion.hybrid.audit.inference_audit import (
    InferenceAudit,
)
from backend.embodied.companion.hybrid.router.capability_matcher import (
    Capability,
)

logger = logging.getLogger(__name__)


class HybridError(Exception):
    """混合智能层操作异常"""


class HybridIntelligenceLayer:
    """混合智能层 (智能资源调度门面)

    用法:
        hil = HybridIntelligenceLayer()
        hil.initialize_defaults()
        decision = hil.route(task_context)
        result = hil.execute(task_context, request)
    """

    def __init__(
        self,
        classifier: Optional[TaskClassifier] = None,
        matcher: Optional[CapabilityMatcher] = None,
        routing: Optional[RoutingEngine] = None,
        local: Optional[LocalProvider] = None,
        cloud: Optional[CloudProvider] = None,
        gateway: Optional[ApiGateway] = None,
        privacy: Optional[PrivacyPolicy] = None,
        cost: Optional[CostPolicy] = None,
        routing_policy: Optional[RoutingPolicy] = None,
        validator: Optional[ResultValidator] = None,
        audit: Optional[InferenceAudit] = None,
        enabled: bool = True,
    ):
        self._lock = threading.RLock()
        self._enabled = bool(enabled)
        self._classifier = classifier or TaskClassifier()
        self._matcher = matcher or CapabilityMatcher()
        self._privacy = privacy or PrivacyPolicy()
        self._cost = cost or CostPolicy()
        self._gateway = gateway or ApiGateway()
        self._local = local or LocalProvider()
        self._cloud = cloud or CloudProvider(
            gateway=self._gateway,
        )
        self._routing = routing or RoutingEngine(
            privacy=self._privacy,
            cost=self._cost,
            matcher=self._matcher,
        )
        self._routing_policy = routing_policy or RoutingPolicy(
            privacy=self._privacy,
            cost=self._cost,
        )
        self._validator = validator or ResultValidator()
        self._audit = audit or InferenceAudit()
        self._executed_count = 0
        self._blocked_count = 0
        self._route_distribution: Dict[str, int] = {}

    # ── 初始化 ───────────────────────────────────────────────────
    def initialize_defaults(self) -> Dict[str, Any]:
        """注册默认能力集 (本地 5 + 云端 8 能力)"""
        with self._lock:
            n_matcher = self._matcher.register_defaults()
            n_local = self._local.register_defaults()
            n_gateway = self._gateway.register_defaults()
            return {
                "mode": "rule_based",
                "matcher_capabilities": n_matcher,
                "local_capabilities": n_local,
                "gateway_models": n_gateway,
            }

    # ── 路由 ─────────────────────────────────────────────────────
    def route(
        self,
        task_context: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """任务 → 路由决策 (分类 → 规则路由 → 策略修正)"""
        with self._lock:
            ctx = self._classifier.classify(task_context)
            decision = self._routing.route(ctx)
            # 路由策略修正 (隐私/成本/实时)
            try:
                adj = self._routing_policy.evaluate(
                    ctx, decision["route"],
                )
                if adj["final_route"] != decision["route"]:
                    decision["route"] = adj["final_route"]
                    decision["reason"] = (
                        f"{decision['reason']} | 策略修正: "
                        f"{adj['reasons']}"
                    )
                    decision["confidence"] = round(
                        decision["confidence"] * 0.9, 4,
                    )
                    decision["policy_adjusted"] = True
            except Exception as e:
                logger.warning(
                    f"[Hybrid] 路由策略修正失败: {e}",
                )
            decision["classified"] = ctx
            # 云端停用 → 降级本地 (可解释)
            cloud_ok = getattr(
                self._cloud, "_enabled", True,
            )
            if decision["route"] != "LOCAL" and not cloud_ok:
                decision["route"] = "LOCAL"
                decision["reason"] = (
                    f"{decision['reason']} | 云端停用, "
                    f"降级本地"
                )
                decision["confidence"] = round(
                    decision["confidence"] * 0.85, 4,
                )
            return decision

    # ── 执行 (完整流程) ─────────────────────────────────────────
    def execute(
        self,
        task_context: Optional[Dict[str, Any]],
        request: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """执行智能调用 (路由 → 执行 → 验证 → 审计)

        Args:
            task_context: 任务上下文
            request: 请求载荷 (query/prompt)

        Returns:
            执行结果 (含 validation 与 audit_id)
        """
        with self._lock:
            if not self._enabled:
                return {
                    "ok": False,
                    "reason": "混合智能层停用",
                    "mode": "error_frame",
                }
            decision = self.route(task_context)
            route = decision["route"]
            ttype = decision["classified"]["type"]
            # 1. 本地执行
            if route == "LOCAL":
                result = self._execute_local(ttype, request)
                provider = "local"
                validation = self._validator.validate(
                    result, decision["classified"],
                )
            # 2. 云端执行 (结果必须验证)
            elif route == "CLOUD":
                result = self._execute_cloud(ttype, request)
                provider = "cloud"
                validation = self._validator.validate(
                    result, decision["classified"],
                )
                if not validation["ok"]:
                    self._blocked_count += 1
                    result = self._blocked_result(
                        result, validation,
                    )
            # 3. 混合执行 (本地上下文 + 云端推理 + 本地验证)
            else:
                result, provider, validation = \
                    self._execute_hybrid(ttype, request)
                if not validation["ok"]:
                    self._blocked_count += 1
                    result = self._blocked_result(
                        result, validation,
                    )
            self._executed_count += 1
            self._route_distribution[route] = \
                self._route_distribution.get(route, 0) + 1
            # 审计 (所有调用必须记录)
            entry = self._audit.record(
                task=ttype,
                route=route,
                provider=provider,
                reason=decision["reason"],
                result=result,
                validation=validation,
            )
            result["audit_id"] = entry.get("audit_id", "")
            result["validation"] = validation
            result["route"] = route
            return result

    # ── 执行子流程 (可解释) ─────────────────────────────────────
    def _execute_local(self, ttype: str,
                       request: Dict[str, Any]) -> Dict[str, Any]:
        """本地执行 (能力匹配优先)"""
        m = self._matcher.match(ttype)
        for cap in m["local"]:
            result = self._local.execute(
                cap["name"], request,
            )
            if result.get("ok") is not False:
                return result
        return self._local.execute(
            "basic_reasoning", request,
        )

    def _execute_cloud(self, ttype: str,
                       request: Dict[str, Any]) -> Dict[str, Any]:
        """云端执行 (能力匹配优先)"""
        m = self._matcher.match(ttype)
        for cap in m["cloud"]:
            result = self._cloud.execute(
                cap["name"], request,
            )
            if result.get("ok") is not False:
                return result
        return self._cloud.execute(
            "deep_reasoning", request,
        )

    def _execute_hybrid(self, ttype: str,
                        request: Dict[str, Any]) -> tuple:
        """混合执行: 本地上下文 → 云端推理 → 本地验证"""
        local_ctx = self._local.execute(
            "basic_reasoning",
            {"query": "本地上下文采集", **request},
        )
        cloud_result = self._execute_cloud(ttype, request)
        cloud_result["local_context"] = local_ctx.get(
            "result", "",
        )
        validation = self._validator.validate(
            cloud_result, {"type": ttype},
        )
        return cloud_result, "hybrid", validation

    def _blocked_result(
        self, result: Dict[str, Any],
        validation: Dict[str, Any],
    ) -> Dict[str, Any]:
        """验证拦截结果 (禁止应用)"""
        return {
            "ok": False,
            "provider": result.get("provider", ""),
            "blocked": True,
            "reason": f"验证拦截: {validation['reason']}",
            "temporary": True,
            "mode": "error_frame",
        }

    # ── 网关直调 (成本受控) ─────────────────────────────────────
    def gateway_request(
        self,
        model: str,
        payload: Optional[Dict[str, Any]] = None,
        value_score: float = 0.0,
    ) -> Dict[str, Any]:
        """网关直调 (低价值任务禁止高成本模型)"""
        with self._lock:
            if not self._enabled:
                return {
                    "ok": False,
                    "reason": "混合智能层停用",
                    "mode": "error_frame",
                }
            # 成本前置检查
            cp = self._cost.evaluate(
                value_score=value_score,
                model=model,
            )
            if not cp["allowed"]:
                return {
                    "ok": False,
                    "reason": f"成本拦截: {cp['reason']}",
                    "mode": "error_frame",
                }
            resp = self._gateway.request(model, payload)
            # 成本记录
            self._cost.record(
                model=model,
                tokens=resp.get("usage", {}).get(
                    "total_tokens", 0,
                ),
                cost=resp.get("cost", 0.0),
                value_score=value_score,
            )
            return resp

    # ── 查询 ─────────────────────────────────────────────────────
    def stats(self) -> Dict[str, Any]:
        """混合智能层统计"""
        with self._lock:
            return {
                "mode": "rule_based",
                "enabled": self._enabled,
                "executed_count": self._executed_count,
                "blocked_count": self._blocked_count,
                "route_distribution": dict(
                    self._route_distribution,
                ),
                "classifier": self._classifier.stats(),
                "matcher": self._matcher.stats(),
                "routing": self._routing.stats(),
                "local": self._local.stats(),
                "cloud": self._cloud.stats(),
                "gateway": self._gateway.stats(),
                "privacy": self._privacy.stats(),
                "cost": self._cost.stats(),
                "validator": self._validator.stats(),
                "audit": self._audit.stats(),
            }

    def audit_report(self, limit: int = 100) -> Dict[str, Any]:
        """智能调用审计报告"""
        return self._audit.report(limit=limit)

    def audit_replay(self, limit: int = 100) -> Dict[str, Any]:
        """智能调用回放"""
        return self._audit.replay(limit=limit)

    def cost_optimization(self) -> Dict[str, Any]:
        """成本优化建议"""
        return self._cost.optimization()

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = 0
            n += self._classifier.clear()
            n += self._matcher.clear()
            n += self._routing.clear()
            n += self._local.clear()
            n += self._cloud.clear()
            n += self._gateway.clear()
            n += self._privacy.clear()
            n += self._cost.clear()
            n += self._validator.clear()
            n += self._audit.clear()
            self._executed_count = 0
            self._blocked_count = 0
            self._route_distribution = {}
            return n


__all__ = [
    "HybridError",
    "HybridIntelligenceLayer",
    "ApiGateway",
    "Capability",
    "CapabilityMatcher",
    "CloudProvider",
    "CostPolicy",
    "InferenceAudit",
    "LocalCapability",
    "LocalProvider",
    "ModelEndpoint",
    "PrivacyPolicy",
    "ResultValidator",
    "RoutingEngine",
    "RoutingPolicy",
    "TaskClassifier",
]
