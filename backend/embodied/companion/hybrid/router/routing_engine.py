"""
YHLZ Embodied AI V6.8 - 路由引擎 (Routing Engine)

职责:
    - 任务上下文 → 计算位置决策
    - 输出: {route: LOCAL/CLOUD/HYBRID, reason, confidence}

路由规则 (可解释, 按序判定):
    1. 身份相关 / 高隐私 → LOCAL (隐私铁律, 云端否决)
    2. 高实时 / 简单任务 / 低创造 → LOCAL
    3. 高复杂度 / 高知识需求 / 高创造 → CLOUD (受成本/能力约束)
    4. 中复杂度 + 中创造 → HYBRID (本地上下文 → 云端推理 → 本地验证)

策略集成:
    - PrivacyPolicy: 高隐私强制本地
    - CostPolicy: 高成本模型受价值约束
    - CapabilityMatcher: 能力缺失时降级

设计原则:
    - 纯规则路由 (无黑盒, 可解释)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import uuid
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class RoutingError(Exception):
    """路由操作异常"""


# 路由目标 (可解释)
ROUTE_TARGETS: list = ["LOCAL", "CLOUD", "HYBRID"]

# 路由规则权重 (可解释)
ROUTE_RULES: Dict[str, float] = {
    "privacy": 0.35,      # 隐私保护 (铁律)
    "latency": 0.25,      # 实时性
    "complexity": 0.25,   # 复杂度
    "creativity": 0.15,   # 创造需求
}


class RoutingEngine:
    """路由引擎 (任务 → 计算位置)

    用法:
        engine = RoutingEngine(
            privacy=privacy_policy, cost=cost_policy,
            matcher=capability_matcher,
        )
        result = engine.route(task_context)
    """

    def __init__(
        self,
        privacy=None,
        cost=None,
        matcher=None,
        enabled: bool = True,
        local_confidence: float = 0.9,
        cloud_confidence: float = 0.75,
        hybrid_confidence: float = 0.8,
    ):
        self._lock = threading.RLock()
        self._privacy = privacy
        self._cost = cost
        self._matcher = matcher
        self._enabled = bool(enabled)
        self._conf = {
            "LOCAL": float(local_confidence),
            "CLOUD": float(cloud_confidence),
            "HYBRID": float(hybrid_confidence),
        }
        self._results: list = []
        self._route_distribution: Dict[str, int] = {}

    # ── 路由主入口 ───────────────────────────────────────────────
    def route(
        self,
        task_context: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """任务 → 路由决策

        Args:
            task_context: 规范化任务上下文 (含 type/
                complexity/privacy_level/latency_requirement/
                creativity_requirement)

        Returns:
            {
                'route', 'reason', 'confidence', 'checks',
                'mode',
            }
        """
        with self._lock:
            ctx = task_context or {}
            if not self._enabled:
                return {
                    "route": "LOCAL",
                    "reason": "路由引擎停用, 默认本地",
                    "confidence": 0.5,
                    "checks": [],
                    "mode": "rule_based",
                }
            checks: list = []
            ttype = str(ctx.get("type", ""))
            complexity = float(ctx.get("complexity", 0.4))
            privacy = str(ctx.get("privacy_level", "low"))
            latency = str(ctx.get(
                "latency_requirement", "normal",
            ))
            creativity = float(ctx.get(
                "creativity_requirement", 0.2,
            ))
            # 1. 隐私铁律: 高隐私 → 强制本地
            if self._privacy is not None:
                try:
                    pv = self._privacy.evaluate(ctx)
                    if not pv["cloud_allowed"]:
                        return self._finish(
                            "LOCAL", pv["reason"],
                            pv["confidence"], ctx,
                            checks + [{
                                "name": "privacy",
                                "passed": False,
                                "reason": pv["reason"],
                            }],
                        )
                    checks.append({
                        "name": "privacy",
                        "passed": True,
                        "reason": pv["reason"],
                    })
                except Exception as e:
                    logger.warning(
                        f"[Hybrid] 隐私策略异常: {e}",
                    )
            # 2. 身份相关任务 → 本地
            if ttype in ("identity_query", "permission_check",
                         "memory_retrieval"):
                return self._finish(
                    "LOCAL",
                    f"任务 '{ttype}' 涉及身份/记忆/权限, 本地处理",
                    self._conf["LOCAL"], ctx,
                    checks + [{
                        "name": "local_rule",
                        "passed": True,
                        "reason": "身份相关任务本地铁律",
                    }],
                )
            # 3. 高实时 → 本地
            if latency == "realtime":
                return self._finish(
                    "LOCAL",
                    "实时性要求, 本地处理保证响应",
                    self._conf["LOCAL"], ctx,
                    checks + [{
                        "name": "latency",
                        "passed": True,
                        "reason": "高实时任务本地处理",
                    }],
                )
            # 4. 能力匹配 (缺失云端能力 → 降级本地)
            if self._matcher is not None:
                try:
                    m = self._matcher.match(ttype)
                    checks.append({
                        "name": "capability",
                        "passed": True,
                        "reason": m["reason"],
                    })
                    if m["missing"] and not m["cloud"]:
                        return self._finish(
                            "LOCAL",
                            f"云端能力缺失 "
                            f"({m['missing']}), 降级本地",
                            0.6, ctx, checks,
                        )
                except Exception as e:
                    logger.warning(
                        f"[Hybrid] 能力匹配异常: {e}",
                    )
            # 5. 高复杂度/高创造 → 云端 (成本策略约束)
            if complexity >= 0.75 or creativity >= 0.7:
                cost_ok = True
                if self._cost is not None:
                    try:
                        cp = self._cost.evaluate(
                            value_score=creativity,
                            model="deep_reasoning",
                        )
                        cost_ok = cp["allowed"]
                        checks.append({
                            "name": "cost",
                            "passed": cost_ok,
                            "reason": cp["reason"],
                        })
                    except Exception as e:
                        logger.warning(
                            f"[Hybrid] 成本策略异常: {e}",
                        )
                if cost_ok:
                    return self._finish(
                        "CLOUD",
                        f"高复杂度 {complexity} / 高创造 "
                        f"{creativity}, 云端增强",
                        self._conf["CLOUD"], ctx, checks,
                    )
                return self._finish(
                    "LOCAL",
                    "成本策略限制云端调用, 降级本地",
                    0.55, ctx, checks,
                )
            # 6. 中复杂度 + 中创造 → 混合
            if complexity >= 0.45 and creativity >= 0.35:
                return self._finish(
                    "HYBRID",
                    f"复杂度 {complexity} + 创造需求 "
                    f"{creativity}, 本地上下文+云端推理",
                    self._conf["HYBRID"], ctx, checks,
                )
            # 7. 默认本地
            return self._finish(
                "LOCAL",
                f"任务 '{ttype}' 低复杂度, 本地处理",
                self._conf["LOCAL"], ctx, checks,
            )

    # ── 决策完成 (可解释) ───────────────────────────────────────
    def _finish(self, route: str, reason: str,
                confidence: float, ctx: Dict[str, Any],
                checks: list) -> Dict[str, Any]:
        result = {
            "route_id": "rt_" + uuid.uuid4().hex[:8],
            "route": route,
            "reason": reason,
            "confidence": round(float(confidence), 4),
            "checks": list(checks),
            "mode": "rule_based",
        }
        self._results.append(result)
        self._route_distribution[route] = \
            self._route_distribution.get(route, 0) + 1
        return dict(result)

    # ── 查询 ─────────────────────────────────────────────────────
    def stats(self) -> Dict[str, Any]:
        """路由统计"""
        with self._lock:
            return {
                "mode": "rule_based",
                "enabled": self._enabled,
                "route_count": len(self._results),
                "distribution": dict(self._route_distribution),
                "targets": list(ROUTE_TARGETS),
                "rule_weights": dict(ROUTE_RULES),
            }

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = len(self._results)
            self._results.clear()
            self._route_distribution = {}
            return n


__all__ = [
    "ROUTE_RULES",
    "ROUTE_TARGETS",
    "RoutingEngine",
    "RoutingError",
]
