"""
YHLZ Embodied AI V8.5 - 思维火花生成器 (Idea Spark Generator)

职责:
    - 发现: 未连接知识 / 潜在关系 / 新组合可能
    - 输入: Existing Memory + Current Problem + Context
    - 输出: Idea Spark

火花类型 (可解释):
    - unconnected_link   未连接知识配对
    - potential_relation 潜在关系
    - new_combination    新组合可能

设计原则:
    - 纯规则发现 (基于知识图, 禁止无依据)
    - 火花必须含 basis (依据)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class SparkError(Exception):
    """思维火花操作异常"""


class IdeaSparkGenerator:
    """思维火花生成器 (知识图 → 火花)

    用法:
        generator = IdeaSparkGenerator(graph=graph)
        sparks = generator.generate(problem, context)
    """

    def __init__(
        self,
        graph=None,
        enabled: bool = True,
        max_sparks: int = 10,
    ):
        if max_sparks <= 0:
            raise SparkError(
                f"max_sparks 必须 > 0, 当前: {max_sparks}"
            )
        self._lock = threading.RLock()
        self._graph = graph
        self._enabled = bool(enabled)
        self._max = int(max_sparks)
        self._sparks: list = []

    # ── 生成主入口 ───────────────────────────────────────────────
    def generate(
        self,
        problem: str,
        context: Optional[Dict[str, Any]] = None,
        now: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """生成思维火花

        Args:
            problem: 当前问题
            context: 上下文 (可空)

        Returns:
            火花列表 (含 basis, 可解释)
        """
        with self._lock:
            now = now if now is not None else time.time()
            if not self._enabled:
                return []
            if self._graph is None:
                return []
            sparks: List[Dict[str, Any]] = []
            # 1. 未连接知识配对 (unconnected_link)
            lonely = self._graph.unconnected(limit=10)
            for i in range(0, len(lonely) - 1, 2):
                a = lonely[i]["concept"]
                b = lonely[i + 1]["concept"]
                sparks.append(self._build(
                    "unconnected_link",
                    f"连接未关联知识 '{a}' 与 '{b}'",
                    f"两者均无既有关系, 潜在连接点",
                    confidence=0.5,
                    related=[a, b],
                    now=now,
                ))
            # 2. 问题 × 高频概念 (new_combination)
            concepts = self._top_concepts(limit=4)
            for concept in concepts:
                sparks.append(self._build(
                    "new_combination",
                    f"将 '{concept}' 应用于问题 "
                    f"'{problem[:20]}'",
                    f"领域概念与问题域存在组合可能",
                    confidence=0.6,
                    related=[concept, problem[:20]],
                    now=now,
                ))
            # 3. 邻居桥接 (potential_relation)
            for concept in concepts[:2]:
                neighbors = self._graph.neighbors(concept)
                for nb in neighbors[:2]:
                    sparks.append(self._build(
                        "potential_relation",
                        f"探索 '{concept}' 与 '{nb['concept']}' "
                        f"的深层关系",
                        f"已有直接关系, 可能延伸新维度",
                        confidence=0.55,
                        related=[concept, nb["concept"]],
                        now=now,
                    ))
            kept = sparks[:self._max]
            self._sparks.extend(kept)
            return [dict(s) for s in kept]

    # ── 构建 (可解释) ───────────────────────────────────────────
    def _build(self, spark_type: str, idea: str,
               basis: str, confidence: float,
               related: list, now: float) -> Dict[str, Any]:
        return {
            "spark_id": "sp_" + uuid.uuid4().hex[:8],
            "spark_type": spark_type,
            "idea": idea,
            "basis": basis,
            "confidence": round(min(1.0, max(0.0, confidence)),
                                4),
            "related_concepts": list(related),
            "created_at": now,
        }

    def _top_concepts(self, limit: int = 4) -> List[str]:
        """高频概念 (按关系数)"""
        if self._graph is None:
            return []
        try:
            counts: Dict[str, int] = {}
            for r in self._graph._relations:
                counts[r["from"]] = counts.get(r["from"], 0) + 1
            ordered = sorted(
                counts.items(), key=lambda kv: kv[1],
                reverse=True,
            )
            return [c for c, _ in ordered[:limit]]
        except Exception:
            return []

    # ── 查询 ─────────────────────────────────────────────────────
    def stats(self) -> Dict[str, Any]:
        """火花统计"""
        with self._lock:
            by_type: Dict[str, int] = {}
            for s in self._sparks:
                by_type[s["spark_type"]] = by_type.get(
                    s["spark_type"], 0,
                ) + 1
            return {
                "mode": "rule_based",
                "enabled": self._enabled,
                "spark_count": len(self._sparks),
                "by_type": by_type,
            }

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = len(self._sparks)
            self._sparks.clear()
            return n


__all__ = [
    "IdeaSparkGenerator",
    "SparkError",
]
