"""
YHLZ Embodied AI V6.8 - 路由策略 (Routing Policy)

职责:
    - 综合路由约束 (隐私 + 成本 + 能力 + 实时性)
    - 输出路由建议 + 否决原因 (可解释)

设计原则:
    - 纯规则 (无黑盒)
    - 策略组合可解释
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class RoutingPolicyError(Exception):
    """路由策略操作异常"""


class RoutingPolicy:
    """路由策略 (综合约束 → 路由修正)

    用法:
        policy = RoutingPolicy(privacy=privacy_policy,
                               cost=cost_policy)
        r = policy.evaluate(task_context)
    """

    def __init__(
        self,
        privacy=None,
        cost=None,
        enabled: bool = True,
    ):
        self._lock = threading.RLock()
        self._privacy = privacy
        self._cost = cost
        self._enabled = bool(enabled)
        self._evaluate_count = 0

    # ── 评估主入口 ───────────────────────────────────────────────
    def evaluate(
        self,
        task_context: Optional[Dict[str, Any]],
        desired_route: str = "LOCAL",
    ) -> Dict[str, Any]:
        """路由约束评估

        Args:
            task_context: 任务上下文
            desired_route: 期望路由 (LOCAL/CLOUD/HYBRID)

        Returns:
            {
                'allowed', 'final_route', 'reasons', 'mode',
            }
        """
        with self._lock:
            ctx = task_context or {}
            if not self._enabled:
                return {
                    "allowed": True,
                    "final_route": desired_route,
                    "reasons": ["路由策略停用"],
                    "mode": "rule_based",
                }
            reasons: list = []
            allowed = True
            final = desired_route
            # 1. 隐私约束 (铁律)
            if self._privacy is not None:
                try:
                    pv = self._privacy.evaluate(ctx)
                    if not pv["cloud_allowed"] and \
                            final != "LOCAL":
                        final = "LOCAL"
                        reasons.append(
                            f"隐私否决: {pv['reason']}",
                        )
                    else:
                        reasons.append(pv["reason"])
                except Exception as e:
                    logger.warning(
                        f"[Hybrid] 隐私策略异常: {e}",
                    )
            # 2. 成本约束
            if self._cost is not None and final == "CLOUD":
                try:
                    cp = self._cost.evaluate(
                        value_score=float(ctx.get(
                            "creativity_requirement", 0.0,
                        )),
                        model="cloud_deep_reasoning",
                    )
                    if not cp["allowed"]:
                        final = "LOCAL"
                        reasons.append(
                            f"成本否决: {cp['reason']}",
                        )
                    else:
                        reasons.append(cp["reason"])
                except Exception as e:
                    logger.warning(
                        f"[Hybrid] 成本策略异常: {e}",
                    )
            # 3. 混合要求
            if final == "CLOUD" and ctx.get(
                "latency_requirement",
            ) == "realtime":
                final = "HYBRID"
                reasons.append(
                    "实时性要求: 云端结果需本地即时校验",
                )
            self._evaluate_count += 1
            return {
                "allowed": allowed,
                "final_route": final,
                "reasons": reasons,
                "mode": "rule_based",
            }

    # ── 查询 ─────────────────────────────────────────────────────
    def stats(self) -> Dict[str, Any]:
        """路由策略统计"""
        with self._lock:
            return {
                "mode": "rule_based",
                "enabled": self._enabled,
                "evaluate_count": self._evaluate_count,
            }

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            self._evaluate_count = 0
            return 0


__all__ = [
    "RoutingPolicy",
    "RoutingPolicyError",
]
