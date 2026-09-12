"""
YHLZ Embodied AI V8.5 - 知识图 (Knowledge Graph)

职责:
    - 概念节点与关系边管理
    - 未连接知识发现 (创造入口)
    - 支撑: 思维火花/概念重组/边界检测

设计原则:
    - 纯规则图 (无黑盒)
    - 来源可追溯 (evidence)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class KnowledgeGraphError(Exception):
    """知识图操作异常"""


class KnowledgeGraph:
    """知识图 (概念 + 关系)

    用法:
        graph = KnowledgeGraph()
        graph.add_concept("模式发现", "method")
        graph.add_relation("经验", "模式发现", "推导")
        sparks = graph.unconnected()
    """

    def __init__(self, max_nodes: int = 2000):
        if max_nodes <= 0:
            raise KnowledgeGraphError(
                f"max_nodes 必须 > 0, 当前: {max_nodes}"
            )
        self._lock = threading.RLock()
        self._max_nodes = int(max_nodes)
        self._nodes: Dict[str, Dict[str, Any]] = {}
        self._relations: list = []

    # ── 概念 ─────────────────────────────────────────────────────
    def add_concept(
        self,
        concept: str,
        category: str = "general",
        source: str = "memory",
        confidence: float = 0.5,
    ) -> Dict[str, Any]:
        """添加概念节点 (同名更新)"""
        with self._lock:
            if not concept:
                raise KnowledgeGraphError("概念不能为空")
            node = {
                "node_id": "kg_" + uuid.uuid4().hex[:8],
                "concept": str(concept),
                "category": str(category),
                "source": str(source),
                "confidence": round(min(
                    1.0, max(0.0, float(confidence)),
                ), 4),
                "created_at": time.time(),
            }
            self._nodes[concept] = node
            if len(self._nodes) > self._max_nodes:
                # 淘汰最旧 (简单策略)
                oldest = min(
                    self._nodes.values(),
                    key=lambda n: n["created_at"],
                )
                self._nodes.pop(oldest["concept"], None)
            return dict(node)

    def get(self, concept: str) -> Optional[Dict[str, Any]]:
        """查询概念"""
        with self._lock:
            node = self._nodes.get(concept)
            return dict(node) if node is not None else None

    # ── 关系 ─────────────────────────────────────────────────────
    def add_relation(
        self,
        from_concept: str,
        to_concept: str,
        relation: str = "related",
        evidence: str = "",
    ) -> Dict[str, Any]:
        """添加关系边 (概念自动创建)"""
        with self._lock:
            if from_concept not in self._nodes:
                self.add_concept(from_concept)
            if to_concept not in self._nodes:
                self.add_concept(to_concept)
            rel = {
                "relation_id": "kr_" + uuid.uuid4().hex[:8],
                "from": str(from_concept),
                "to": str(to_concept),
                "relation": str(relation),
                "evidence": str(evidence),
                "created_at": time.time(),
            }
            self._relations.append(rel)
            return dict(rel)

    def relations_of(self, concept: str) -> List[Dict[str, Any]]:
        """概念的关系"""
        with self._lock:
            return [
                dict(r) for r in self._relations
                if r["from"] == concept or r["to"] == concept
            ]

    # ── 发现 (创造入口) ─────────────────────────────────────────
    def unconnected(self, limit: int = 20) -> List[Dict[str, Any]]:
        """未连接概念 (潜在关系入口)"""
        with self._lock:
            connected: set = set()
            for r in self._relations:
                connected.add(r["from"])
                connected.add(r["to"])
            lonely = [
                dict(n) for n in self._nodes.values()
                if n["concept"] not in connected
            ]
            if limit > 0:
                lonely = lonely[:limit]
            return lonely

    def neighbors(self, concept: str) -> List[Dict[str, Any]]:
        """邻居概念"""
        with self._lock:
            rels = [
                r for r in self._relations
                if r["from"] == concept
            ]
            return [
                dict(self._nodes[r["to"]])
                for r in rels
                if r["to"] in self._nodes
            ]

    def load_records(self, records: List[Dict[str, Any]]) -> int:
        """从经历/记忆加载概念 (Continuity)"""
        with self._lock:
            n = 0
            for rec in records or []:
                trigger = str(rec.get("trigger", "")).strip()
                if trigger:
                    self.add_concept(
                        trigger, "experience",
                        source=str(rec.get("source", "memory")),
                        confidence=float(rec.get(
                            "confidence", 0.5,
                        )),
                    )
                    n += 1
            return n

    # ── 查询 ─────────────────────────────────────────────────────
    def stats(self) -> Dict[str, Any]:
        """知识图统计"""
        with self._lock:
            by_category: Dict[str, int] = {}
            for n in self._nodes.values():
                by_category[n["category"]] = by_category.get(
                    n["category"], 0,
                ) + 1
            return {
                "mode": "rule_based",
                "node_count": len(self._nodes),
                "relation_count": len(self._relations),
                "by_category": by_category,
                "unconnected_count": len(
                    self.unconnected(limit=0),
                ),
            }

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = len(self._nodes) + len(self._relations)
            self._nodes.clear()
            self._relations.clear()
            return n


__all__ = [
    "KnowledgeGraph",
    "KnowledgeGraphError",
]
