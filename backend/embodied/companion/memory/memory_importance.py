"""
YHLZ Embodied AI V6.0 - 记忆价值评分 (Memory Importance)

职责:
    - 记忆价值评分 (Importance Score):
      Identity Impact + Relationship Impact + Creative Impact
      + Repeat Value
    - 高价值记忆禁止自动删除 (保护规则)

评分维度 (可解释, 每维 0.0~0.5, 总分 0.0~2.0):
    - identity_impact:    身份影响 (身份/人格/核心关键词, 验证确认)
    - relationship_impact: 关系影响 (关系关键词/用户偏好)
    - creative_impact:    创造影响 (被创造方案引用 / 创造来源)
    - repeat_value:       重复价值 (同触发出现次数, 越多越值得保留)

设计原则:
    - 纯规则评分 (禁止黑盒)
    - 每维附 reason (可回溯)
    - 高价值 (score >= high_threshold) → 禁止自动删除
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ImportanceError(Exception):
    """记忆价值评分操作异常"""


# 关键词表 (可解释)
IDENTITY_KEYWORDS: List[str] = [
    "身份", "人格", "核心", "使命", "元", "贞", "价值观",
]
RELATIONSHIP_KEYWORDS: List[str] = [
    "关系", "信任", "偏好", "喜欢", "用户", "互动",
    "铁哥们", "伙伴",
]
CREATIVE_KEYWORDS: List[str] = [
    "创造", "方案", "机会", "proposal", "创意", "价值",
]


class MemoryImportance:
    """记忆价值评分器

    用法:
        scorer = MemoryImportance()
        result = scorer.score(record, context)
        protected = scorer.should_protect(record_id)
    """

    def __init__(self, high_threshold: float = 0.7):
        if not (0.0 <= high_threshold <= 2.0):
            raise ImportanceError(
                f"high_threshold 必须在 [0,2], 当前: {high_threshold}"
            )
        self._lock = threading.RLock()
        self._high_threshold = float(high_threshold)
        self._scores: Dict[str, Dict[str, Any]] = {}

    # ── 评分主入口 ───────────────────────────────────────────────
    def score(
        self,
        record: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """记忆价值评分 (规则驱动, 可解释)

        Args:
            record: 经历/记忆 dict (id/trigger/lesson/source/type/
                value/timestamp)
            context: 上下文 (verification_status / occurrence_count /
                referenced_by_creative)

        Returns:
            {
                'record_id', 'importance_score', 'dimensions': [...],
                'protected', 'level', 'reason',
            }
        """
        with self._lock:
            rid = record.get("id", "")
            if not rid:
                raise ImportanceError("记录缺 id")
            ctx = dict(context or {})
            dims = {
                "identity_impact": self._identity_impact(record, ctx),
                "relationship_impact": self._relationship_impact(
                    record, ctx,
                ),
                "creative_impact": self._creative_impact(record, ctx),
                "repeat_value": self._repeat_value(record, ctx),
            }
            total = round(sum(d["score"] for d in dims.values()), 4)
            protected = total >= self._high_threshold
            level = "high" if protected else (
                "medium" if total >= self._high_threshold / 2 else "low"
            )
            result = {
                "record_id": rid,
                "importance_score": total,
                "dimensions": [
                    {"name": k, "score": v["score"],
                     "reason": v["reason"]}
                    for k, v in dims.items()
                ],
                "protected": protected,
                "level": level,
                "reason": (
                    f"价值分 {total} "
                    f"{'≥' if protected else '<'} "
                    f"保护阈值 {self._high_threshold}"
                    f"{' → 禁止自动删除' if protected else ''}"
                ),
            }
            self._scores[rid] = result
            return dict(result)

    # ── 维度评分 (可解释) ───────────────────────────────────────
    @staticmethod
    def _text(record: Dict[str, Any]) -> str:
        """评分文本: trigger + lesson + source"""
        return " ".join([
            str(record.get("trigger", "")),
            str(record.get("lesson", "")),
            str(record.get("source", "")),
            str(record.get("type", "")),
        ])

    def _identity_impact(
        self, record: Dict[str, Any], ctx: Dict[str, Any],
    ) -> Dict[str, Any]:
        """身份影响: 关键词 + 验证确认"""
        score = 0.0
        hits = [k for k in IDENTITY_KEYWORDS if k in self._text(record)]
        if hits:
            score = min(0.3, 0.15 + 0.05 * (len(hits) - 1))
        if ctx.get("verification_status") == "CONFIRMED":
            score = min(0.4, score + 0.1)
        return {
            "score": round(score, 4),
            "reason": (
                f"身份关键词 {hits if hits else '无'}, "
                f"验证 {ctx.get('verification_status', 'UNKNOWN')}"
            ),
        }

    def _relationship_impact(
        self, record: Dict[str, Any], ctx: Dict[str, Any],
    ) -> Dict[str, Any]:
        """关系影响: 关系关键词"""
        hits = [k for k in RELATIONSHIP_KEYWORDS
                if k in self._text(record)]
        score = min(0.5, 0.2 * len(hits)) if hits else 0.0
        return {
            "score": round(score, 4),
            "reason": f"关系关键词 {hits if hits else '无'}",
        }

    def _creative_impact(
        self, record: Dict[str, Any], ctx: Dict[str, Any],
    ) -> Dict[str, Any]:
        """创造影响: 被方案引用 / 创造来源"""
        score = 0.0
        reasons: List[str] = []
        if ctx.get("referenced_by_creative"):
            score += 0.3
            reasons.append("被创造方案引用")
        hits = [k for k in CREATIVE_KEYWORDS if k in self._text(record)]
        if hits:
            score += 0.1
            reasons.append(f"创造关键词 {hits[:2]}")
        if record.get("source") == "creative_execution":
            score += 0.1
            reasons.append("创造执行来源")
        return {
            "score": round(min(0.5, score), 4),
            "reason": reasons if reasons else "无创造关联",
        }

    @staticmethod
    def _repeat_value(
        record: Dict[str, Any], ctx: Dict[str, Any],
    ) -> Dict[str, Any]:
        """重复价值: 同触发出现次数"""
        n = int(ctx.get("occurrence_count", 1) or 1)
        score = min(0.5, 0.15 + 0.05 * (n - 1))
        return {
            "score": round(score, 4),
            "reason": f"同触发出现 {n} 次",
        }

    # ── 保护规则 ─────────────────────────────────────────────────
    def should_protect(self, record_id: str) -> bool:
        """高价值记忆禁止自动删除"""
        with self._lock:
            r = self._scores.get(record_id)
            return bool(r and r["protected"])

    def get_score(self, record_id: str) -> Optional[Dict[str, Any]]:
        """查询已评记录"""
        with self._lock:
            r = self._scores.get(record_id)
            return dict(r) if r else None

    def protected_ids(self) -> List[str]:
        """全部受保护记录 ID"""
        with self._lock:
            return [
                rid for rid, r in self._scores.items()
                if r["protected"]
            ]

    def stats(self) -> Dict[str, Any]:
        """评分统计"""
        with self._lock:
            scores = list(self._scores.values())
        by_level: Dict[str, int] = {}
        for s in scores:
            by_level[s["level"]] = by_level.get(s["level"], 0) + 1
        avg = (
            sum(s["importance_score"] for s in scores) / len(scores)
            if scores else 0.0
        )
        return {
            "mode": "rule_based",
            "scored_count": len(scores),
            "protected_count": sum(1 for s in scores if s["protected"]),
            "by_level": by_level,
            "avg_importance": round(avg, 4),
            "high_threshold": self._high_threshold,
        }

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = len(self._scores)
            self._scores.clear()
            return n


__all__ = [
    "CREATIVE_KEYWORDS",
    "IDENTITY_KEYWORDS",
    "ImportanceError",
    "MemoryImportance",
    "RELATIONSHIP_KEYWORDS",
]
