"""
YHLZ Embodied AI V9.0 - 知识获取 (Knowledge Acquisition)

职责:
    - 支持来源: 本地知识 / 用户授权资料 / 云端模型 / 外部工具
    - 所有来源记录
    - 未知来源禁止进入长期记忆

设计原则:
    - 来源可追溯 (source/source_reliable)
    - 未知来源 → unreliable → 不入长期记忆
    - Mock 优先 (外部来源可注入)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class AcquisitionError(Exception):
    """知识获取操作异常"""


# 来源类型 (可解释)
SOURCE_TYPES: list = ["local", "user_authorized", "cloud",
                      "tool", "unknown"]

# 来源 → 默认可靠度 (可解释)
SOURCE_RELIABILITY: Dict[str, float] = {
    "local": 0.9,             # 本地知识
    "user_authorized": 0.85,  # 用户授权资料
    "cloud": 0.7,             # 云端模型
    "tool": 0.75,             # 外部工具
    "unknown": 0.0,           # 未知来源 (禁止入长期记忆)
}


class KnowledgeAcquisition:
    """知识获取器 (来源记录 + 可靠度)

    用法:
        acq = KnowledgeAcquisition()
        r = acq.acquire("问题", "local")
    """

    def __init__(
        self,
        providers: Optional[Dict[str, Callable]] = None,
        enabled: bool = True,
        max_records: int = 2000,
    ):
        if max_records <= 0:
            raise AcquisitionError(
                f"max_records 必须 > 0, 当前: {max_records}"
            )
        self._lock = threading.RLock()
        self._enabled = bool(enabled)
        self._max_records = int(max_records)
        self._providers = dict(providers or {})
        self._records: list = []

    # ── 获取主入口 ───────────────────────────────────────────────
    def acquire(
        self,
        query: str,
        source: str = "local",
        now: Optional[float] = None,
    ) -> Dict[str, Any]:
        """获取知识 (来源必须记录)

        Args:
            query: 查询
            source: 来源 (local/user_authorized/cloud/tool/
                unknown)

        Returns:
            {
                'result_id', 'content', 'source',
                'source_reliable', 'reliability', 'mode',
            }
        """
        with self._lock:
            now = now if now is not None else time.time()
            if not self._enabled:
                return {
                    "mode": "error_frame",
                    "ok": False,
                    "reason": "知识获取停用",
                }
            source = str(source)
            if source not in SOURCE_TYPES:
                source = "unknown"
            # 执行 (provider 注入或默认规则)
            content = self._fetch(query, source)
            reliability = SOURCE_RELIABILITY.get(source, 0.0)
            reliable = reliability >= 0.5
            result = {
                "result_id": "ka_" + uuid.uuid4().hex[:8],
                "query": str(query),
                "content": content,
                "source": source,
                "source_reliable": reliable,
                "reliability": reliability,
                "mode": "rule_based",
                "acquired_at": now,
            }
            self._records.append(result)
            if len(self._records) > self._max_records:
                self._records = self._records[-self._max_records:]
            return dict(result)

    # ── 获取执行 (可解释) ───────────────────────────────────────
    def _fetch(self, query: str, source: str) -> str:
        """获取内容 (provider 优先, 默认规则)"""
        provider = self._providers.get(source)
        if provider is not None:
            try:
                result = provider(query)
                return str(result)
            except Exception as e:
                logger.warning(
                    f"[Research] 来源 '{source}' 获取失败: "
                    f"{e}",
                )
                return f"[{source} 获取失败]"
        return (
            f"[{source} 规则结果] 关于 '{query[:30]}' "
            f"的本地知识摘要"
        )

    # ── 查询 ─────────────────────────────────────────────────────
    def records(self, limit: int = 100) -> list:
        """获取记录"""
        with self._lock:
            recent = list(reversed(self._records))
            if limit > 0:
                recent = recent[:limit]
            return [dict(r) for r in recent]

    def stats(self) -> Dict[str, Any]:
        """获取统计"""
        with self._lock:
            by_source: Dict[str, int] = {}
            for r in self._records:
                by_source[r["source"]] = by_source.get(
                    r["source"], 0,
                ) + 1
            return {
                "mode": "rule_based",
                "enabled": self._enabled,
                "record_count": len(self._records),
                "by_source": by_source,
                "unreliable_count": sum(
                    1 for r in self._records
                    if not r["source_reliable"]
                ),
                "source_types": list(SOURCE_TYPES),
            }

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = len(self._records)
            self._records.clear()
            return n


__all__ = [
    "AcquisitionError",
    "SOURCE_RELIABILITY",
    "SOURCE_TYPES",
    "KnowledgeAcquisition",
]
