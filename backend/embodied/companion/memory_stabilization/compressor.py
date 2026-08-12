"""
YHLZ Embodied AI V10.1 - 记忆压缩 (Memory Compressor)

职责:
    - 重复信息合并: 同触发词 / 同内容去重
    - 输出方案: {kept, merged, merged_from} 不直接改存储
    - 压缩可解释: 每组合并输出 reason

设计原则:
    - 按 trigger 归一化分组 → 组内按内容相似度合并
    - 保留价值最高记录为主记录, 其余合并 (merged_from)
    - 相似度阈值可配置 (0.0~1.0)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import re
import threading
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class CompressorError(Exception):
    """记忆压缩异常"""


def normalize_text(text: str) -> str:
    """文本归一化 (去空白/标点/小写)"""
    if not text:
        return ""
    t = str(text).lower().strip()
    t = re.sub(r"[\s\u3000，。！？、；：""''（）《》\-_,.!?;:()\[\]{}]", "", t)
    return t


def text_similarity(a: str, b: str) -> float:
    """内容相似度 (0.0~1.0, 字符按序匹配率, 长串归一化)"""
    na, nb = normalize_text(a), normalize_text(b)
    if not na and not nb:
        return 1.0
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    short, long = (na, nb) if len(na) <= len(nb) else (nb, na)
    if not short:
        return 0.0
    matched = 0
    long_idx = 0
    for ch in short:
        found = long.find(ch, long_idx)
        if found >= 0:
            matched += 1
            long_idx = found + 1
    # 长串归一化: 部分匹配受长度差异惩罚
    return round(matched / len(long), 4)


class MemoryCompressor:
    """记忆压缩器 (V10.1)

    用法:
        c = MemoryCompressor(similarity_threshold=0.9)
        plan = c.compress(records)
        # plan = {"kept": [...], "merged": [...], "merged_from": [...]}
    """

    def __init__(self, similarity_threshold: float = 0.9,
                 enabled: bool = True):
        if not (0.0 <= similarity_threshold <= 1.0):
            raise CompressorError(
                f"similarity_threshold 必须在 [0,1], "
                f"当前: {similarity_threshold}"
            )
        self._lock = threading.RLock()
        self._threshold = float(similarity_threshold)
        self._enabled = bool(enabled)
        self._compress_count = 0

    def compress(
        self,
        records: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """压缩方案: 同触发词分组 + 同内容合并

        Args:
            records: 记忆记录 dict 列表 (id/trigger/lesson/action/
                     result/value/confidence 等)

        Returns:
            {
                "mode", "enabled", "total", "groups",
                "kept": 保留记录 ID 列表,
                "merged": [{
                    "primary_id", "merged_ids", "count",
                    "similarity", "reason",
                }],
                "merged_from": 被合并记录 ID 列表,
            }
        """
        with self._lock:
            if not self._enabled:
                return {
                    "mode": "error_frame",
                    "ok": False,
                    "reason": "记忆压缩停用",
                }
            # 按 trigger 归一化分组
            groups: Dict[str, List[Dict[str, Any]]] = {}
            for rec in records:
                key = normalize_text(rec.get("trigger", ""))
                groups.setdefault(key, []).append(rec)

            kept: List[str] = []
            merged_plans: List[Dict[str, Any]] = []
            merged_from: List[str] = []
            group_stats: List[Dict[str, Any]] = []

            for key, group in groups.items():
                group_stats.append({
                    "trigger_key": key,
                    "count": len(group),
                })
                if len(group) <= 1:
                    kept.extend(r["id"] for r in group)
                    continue
                # 组内两两比较内容相似度, 相似记录合并到最高分记录
                candidates = sorted(
                    group,
                    key=lambda r: self._score(r),
                    reverse=True,
                )
                while candidates:
                    primary = candidates.pop(0)
                    kept.append(primary["id"])
                    rest: List[Dict[str, Any]] = []
                    for rec in candidates:
                        sim = self._content_similarity(primary, rec)
                        if sim >= self._threshold:
                            merged_plans.append({
                                "primary_id": primary["id"],
                                "merged_ids": [rec["id"]],
                                "count": 2,
                                "similarity": sim,
                                "reason": (
                                    f"同触发 '{primary.get('trigger')}' "
                                    f"内容相似 {sim} >= 阈值 "
                                    f"{self._threshold}"
                                ),
                            })
                            merged_from.append(rec["id"])
                        else:
                            rest.append(rec)
                    candidates = rest

            self._compress_count += 1
            return {
                "mode": "rule_based",
                "enabled": self._enabled,
                "total": len(records),
                "groups": group_stats,
                "kept": kept,
                "merged": merged_plans,
                "merged_from": merged_from,
            }

    def _content_similarity(
        self, a: Dict[str, Any], b: Dict[str, Any],
    ) -> float:
        """两条记录内容相似度 (文本字段拼接后整体比较)"""
        fields = ("lesson", "action", "result", "evaluation")
        ta = " ".join(str(a.get(f, "")) for f in fields)
        tb = " ".join(str(b.get(f, "")) for f in fields)
        return text_similarity(ta, tb)

    @staticmethod
    def _score(record: Dict[str, Any]) -> float:
        """记录质量分 (value + confidence 加权)"""
        try:
            value = float(record.get("value", 0.5))
        except (TypeError, ValueError):
            value = 0.5
        try:
            conf = float(record.get("confidence", 0.0))
        except (TypeError, ValueError):
            conf = 0.0
        return value + conf * 0.1

    def stats(self) -> Dict[str, Any]:
        """压缩统计"""
        with self._lock:
            return {
                "mode": "rule_based",
                "enabled": self._enabled,
                "similarity_threshold": self._threshold,
                "compress_count": self._compress_count,
            }

    def clear(self) -> int:
        """清空计数 (测试隔离)"""
        with self._lock:
            n = self._compress_count
            self._compress_count = 0
            return n


__all__ = [
    "CompressorError",
    "MemoryCompressor",
    "normalize_text",
    "text_similarity",
]
