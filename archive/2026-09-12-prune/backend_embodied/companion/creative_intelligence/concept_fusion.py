"""
YHLZ Embodied AI V8.5 - 概念重组器 (Concept Fusion)

职责:
    - 旧观点重组: Concept A + Concept B + New Context → New Concept
    - 记录: 来源 / 组合逻辑 / 推导过程 (可审计)

设计原则:
    - 重组必须可追溯 (sources/fusion_logic/derivation)
    - 纯规则 (无黑盒)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class FusionError(Exception):
    """概念重组操作异常"""


# 组合逻辑类型 (可解释)
FUSION_LOGIC_TYPES: list = [
    "analogy",       # 类比 (A 与 B 相似结构)
    "merge",         # 合并 (A + B 互补)
    "transfer",      # 迁移 (A 方法迁移到 B 领域)
    "extension",     # 延伸 (B 扩展 A)
]


class ConceptFusion:
    """概念重组器 (旧观点 → 新概念)

    用法:
        fusion = ConceptFusion()
        result = fusion.fuse("模式发现", "记忆整理",
                             "长期成长", "merge")
    """

    def __init__(self, enabled: bool = True,
                 max_records: int = 500):
        if max_records <= 0:
            raise FusionError(
                f"max_records 必须 > 0, 当前: {max_records}"
            )
        self._lock = threading.RLock()
        self._enabled = bool(enabled)
        self._max_records = int(max_records)
        self._results: list = []

    # ── 重组主入口 ───────────────────────────────────────────────
    def fuse(
        self,
        concept_a: str,
        concept_b: str,
        new_context: str = "",
        logic: str = "merge",
        now: Optional[float] = None,
    ) -> Dict[str, Any]:
        """概念重组

        Args:
            concept_a: 概念 A
            concept_b: 概念 B
            new_context: 新上下文
            logic: 组合逻辑 (analogy/merge/transfer/extension)

        Returns:
            {
                'fusion_id', 'new_concept', 'fusion_logic',
                'derivation', 'sources', 'mode',
            }
        """
        with self._lock:
            now = now if now is not None else time.time()
            if not self._enabled:
                return {
                    "mode": "error_frame",
                    "ok": False,
                    "reason": "概念重组停用",
                }
            if not concept_a or not concept_b:
                raise FusionError("概念不能为空")
            if logic not in FUSION_LOGIC_TYPES:
                raise FusionError(
                    f"非法组合逻辑: {logic} "
                    f"(可选: {FUSION_LOGIC_TYPES})"
                )
            # 新概念生成 (可解释组合)
            new_concept, derivation = self._compose(
                concept_a, concept_b, logic,
            )
            result = {
                "fusion_id": "cf_" + uuid.uuid4().hex[:8],
                "new_concept": new_concept,
                "fusion_logic": logic,
                "derivation": derivation,
                "sources": [
                    {"concept": concept_a},
                    {"concept": concept_b},
                ],
                "new_context": str(new_context),
                "mode": "rule_based",
                "created_at": now,
            }
            self._results.append(result)
            if len(self._results) > self._max_records:
                self._results = self._results[-self._max_records:]
            return dict(result)

    # ── 组合 (可解释) ───────────────────────────────────────────
    @staticmethod
    def _compose(a: str, b: str,
                 logic: str) -> tuple:
        """新概念与推导过程"""
        if logic == "analogy":
            return (
                f"{a}×{b}类比",
                f"类比 '{a}' 与 '{b}' 的结构相似性, "
                f"提出跨域映射",
            )
        if logic == "transfer":
            return (
                f"{a}→{b}迁移",
                f"将 '{a}' 的方法迁移到 '{b}' 领域",
            )
        if logic == "extension":
            return (
                f"{b}+{a}延伸",
                f"以 '{b}' 为基础, 延伸 '{a}' 的维度",
            )
        return (
            f"{a}+{b}融合",
            f"合并 '{a}' 与 '{b}' 的互补要素, "
            f"形成组合概念",
        )

    # ── 查询 ─────────────────────────────────────────────────────
    def stats(self) -> Dict[str, Any]:
        """重组统计"""
        with self._lock:
            by_logic: Dict[str, int] = {}
            for r in self._results:
                by_logic[r["fusion_logic"]] = by_logic.get(
                    r["fusion_logic"], 0,
                ) + 1
            return {
                "mode": "rule_based",
                "enabled": self._enabled,
                "fusion_count": len(self._results),
                "by_logic": by_logic,
            }

    def history(self, limit: int = 50) -> list:
        """重组历史"""
        with self._lock:
            recent = list(reversed(self._results))
            if limit > 0:
                recent = recent[:limit]
            return [dict(r) for r in recent]

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = len(self._results)
            self._results.clear()
            return n


__all__ = [
    "ConceptFusion",
    "FUSION_LOGIC_TYPES",
    "FusionError",
]
