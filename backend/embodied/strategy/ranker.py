"""
YHLZ Embodied AI V4.4 - 策略候选排序器 (Policy Ranker, Rule-based)

职责:
    - 候选策略质量排序: trigger → scene → goal_type → candidates → quality ranking → best
    - 排序规则 (可解释): hit_rate × 权重 + acceptance_rate × 权重 + 更新时间新鲜度 × 权重
    - 输出"为什么选择该策略" (reason), 保证决策可解释
    - 纯规则 + 统计 + 阈值: 禁止神经网络训练 / 黑盒优化

设计原则:
    - 确定性: 相同输入 → 相同排序 (同分按 updated_at 新者优先, 再按 trigger 字典序)
    - 权重校验: 权重必须 >= 0 且总和 > 0 (配置驱动)
    - 数据独立存储: 不写入 Agent Memory
    - 线程安全 (RLock)
"""
from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Optional

logger = __import__("logging").getLogger(__name__)


class PolicyRankerError(Exception):
    """策略排序器异常"""


class PolicyRanker:
    """策略候选排序器 (可解释打分)

    用法:
        ranker = PolicyRanker(hit_rate_weight=0.5, acceptance_weight=0.3, recency_weight=0.2)
        ranked = ranker.rank(candidates, scene='room', goal_type='pick')
        best = ranker.select_best(candidates)   # {'policy': {...}, 'reason': ...}
    """

    def __init__(
        self,
        hit_rate_weight: float = 0.5,
        acceptance_weight: float = 0.3,
        recency_weight: float = 0.2,
        recency_half_life_days: float = 30.0,
    ):
        if hit_rate_weight < 0 or acceptance_weight < 0 or recency_weight < 0:
            raise PolicyRankerError("排序权重不能为负")
        if hit_rate_weight + acceptance_weight + recency_weight <= 0:
            raise PolicyRankerError("排序权重总和必须 > 0")
        if recency_half_life_days <= 0:
            raise PolicyRankerError(
                f"recency_half_life_days 必须 > 0, 当前: {recency_half_life_days}"
            )
        self._lock = threading.RLock()
        self._w_hit = float(hit_rate_weight)
        self._w_acc = float(acceptance_weight)
        self._w_rec = float(recency_weight)
        self._half_life_days = float(recency_half_life_days)

    # ── 打分 (可解释) ─────────────────────────────────────────────
    def recency_score(self, updated_at: float, now: Optional[float] = None) -> float:
        """新鲜度得分: 越新越高 (0.0 ~ 1.0)

        规则: recency = max(0, 1 - 距今天数 / 半衰期天数)
        """
        now = now if now is not None else time.time()
        if updated_at <= 0:
            return 0.0
        age_days = max(0.0, (now - updated_at) / 86400.0)
        return round(max(0.0, 1.0 - age_days / self._half_life_days), 4)

    def score(self, policy, now: Optional[float] = None) -> float:
        """综合质量得分 (0.0 ~ 1.0)

        score = hit_rate × w_hit + acceptance_rate × w_acc + recency × w_rec
        """
        rec = self.recency_score(policy.updated_at, now)
        s = (
            policy.hit_rate * self._w_hit
            + policy.acceptance_rate * self._w_acc
            + rec * self._w_rec
        )
        return round(s, 4)

    def explain(self, policy, now: Optional[float] = None) -> str:
        """可解释理由: 为什么该策略得分为此值"""
        rec = self.recency_score(policy.updated_at, now)
        return (
            f"score={self.score(policy, now):.4f} = "
            f"hit_rate({policy.hit_rate:.2f})×{self._w_hit:.2f} + "
            f"acceptance_rate({policy.acceptance_rate:.2f})×{self._w_acc:.2f} + "
            f"recency({rec:.2f})×{self._w_rec:.2f}"
        )

    # ── 排序 (确定性 + 可解释) ────────────────────────────────────
    def rank(
        self,
        candidates,
        now: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """候选策略排序 (得分降序, 同分按 updated_at 新者优先)

        Args:
            candidates: PolicyTable.candidates() 输出 (ExperiencePolicy 列表)

        Returns:
            [{'trigger', 'strategy', 'kind', 'score', 'rank', 'reason',
              'hit_rate', 'acceptance_rate', 'version', 'status', 'updated_at'}, ...]
        """
        if not candidates:
            return []
        scored: List[Dict[str, Any]] = []
        for p in candidates:
            scored.append({
                "trigger": p.trigger,
                "strategy": p.strategy,
                "kind": p.kind,
                "score": self.score(p, now),
                "hit_rate": p.hit_rate,
                "acceptance_rate": p.acceptance_rate,
                "version": p.version,
                "status": p.effective_status,
                "updated_at": p.updated_at,
                "reason": self.explain(p, now),
            })
        # 确定性排序: 得分降序 → 更新时间降序 → trigger 字典序
        scored.sort(key=lambda x: (-x["score"], -x["updated_at"], x["trigger"]))
        for i, item in enumerate(scored, start=1):
            item["rank"] = i
        return scored

    def select_best(
        self,
        candidates,
        now: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        """选择最佳策略 (可解释)

        Returns:
            {'policy': ExperiencePolicy, 'ranked': [...], 'best': {...}, 'reason': str}
            无候选 → None
        """
        if not candidates:
            return None
        ranked = self.rank(candidates, now)
        best = ranked[0]
        return {
            "policy": candidates,
            "ranked": ranked,
            "best": best,
            "reason": (
                f"候选 {len(ranked)} 个 (scene/goal_type 匹配), "
                f"排序后选择: {best['trigger']} v{best['version']}, {best['reason']}"
            ),
        }

    def weights(self) -> Dict[str, float]:
        with self._lock:
            return {
                "hit_rate_weight": self._w_hit,
                "acceptance_weight": self._w_acc,
                "recency_weight": self._w_rec,
                "recency_half_life_days": self._half_life_days,
            }


__all__ = ["PolicyRanker", "PolicyRankerError"]
