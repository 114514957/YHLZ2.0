"""
YHLZ Embodied AI V10.1 - 记忆冲突检测 (Memory Conflict Detector)

职责:
    - 矛盾记忆标记: 同主题正反结论 → 冲突标记
    - 不自动删除, 只标记 + 上报 (经宪法)
    - 规则可解释 (reason 字段)

设计原则:
    - 同触发词分组 → 组内结论语义冲突检测
    - 否定信号表: 成功/失败, 可以/不行, 有效/无效 等
    - 冲突只标记不上报决策 (治理由上层执行)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import re
import threading
import time
from typing import Any, Dict, List, Optional

from backend.embodied.companion.memory_stabilization.compressor import (
    normalize_text,
)

logger = logging.getLogger(__name__)


class ConflictDetectorError(Exception):
    """记忆冲突检测异常"""


# 否定信号对 (可解释: 正向 ↔ 反向)
POSITIVE_SIGNALS: List[str] = [
    "成功", "可以", "有效", "没问题", "通过", "正确",
    "可行", "有益", "上升", "增长", "完成",
    "success", "ok", "valid", "works", "pass",
]
NEGATIVE_SIGNALS: List[str] = [
    "失败", "不行", "无效", "有问题", "不通过", "错误",
    "不可行", "有害", "下降", "减少", "未完成",
    "fail", "failed", "bad", "invalid", "broken",
]


class MemoryConflictDetector:
    """记忆冲突检测器 (V10.1)

    用法:
        d = MemoryConflictDetector()
        report = d.detect(records)
    """

    def __init__(self, enabled: bool = True):
        self._lock = threading.RLock()
        self._enabled = bool(enabled)
        self._detect_count = 0

    def detect(
        self,
        records: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """冲突检测: 同触发组内正反结论标记

        Args:
            records: 记忆记录 dict 列表

        Returns:
            {
                "mode", "enabled", "total",
                "conflicts": [{
                    "conflict_id", "trigger", "record_ids",
                    "conflict_type", "detail", "reason",
                }],
            }
        """
        with self._lock:
            if not self._enabled:
                return {
                    "mode": "error_frame",
                    "ok": False,
                    "reason": "记忆冲突检测停用",
                }
            # 按 trigger 归一化分组
            groups: Dict[str, List[Dict[str, Any]]] = {}
            for rec in records:
                key = normalize_text(rec.get("trigger", ""))
                groups.setdefault(key, []).append(rec)

            conflicts: List[Dict[str, Any]] = []
            for key, group in groups.items():
                if len(group) < 2:
                    continue
                pos_ids: List[str] = []
                neg_ids: List[str] = []
                for rec in group:
                    stance = self._stance(rec)
                    rid = rec.get("id", "")
                    if stance > 0:
                        pos_ids.append(rid)
                    elif stance < 0:
                        neg_ids.append(rid)
                if pos_ids and neg_ids:
                    conflicts.append({
                        "conflict_id": "cf_" + __import__(
                            "uuid",
                        ).uuid4().hex[:8],
                        "trigger": group[0].get("trigger", ""),
                        "record_ids": pos_ids + neg_ids,
                        "conflict_type": "contradiction",
                        "detail": (
                            f"同触发 '{group[0].get('trigger', '')}' "
                            f"结论相反: 正向 {len(pos_ids)} 条 / "
                            f"反向 {len(neg_ids)} 条"
                        ),
                        "reason": (
                            "同主题记忆存在正反结论, 标记不自动删除, "
                            "上报治理"
                        ),
                    })

            self._detect_count += 1
            return {
                "mode": "rule_based",
                "enabled": self._enabled,
                "total": len(records),
                "conflicts": conflicts,
            }

    def _stance(self, record: Dict[str, Any]) -> int:
        """记录结论立场: 1 正向 / -1 反向 / 0 中性"""
        text = " ".join(str(record.get(k, "")) for k in (
            "lesson", "result", "evaluation", "action",
        ))
        norm = normalize_text(text)
        if not norm:
            return 0
        # 英文信号在原文整词匹配, 中文信号在归一化文本子串匹配
        pos_hits = sum(
            1 for s in POSITIVE_SIGNALS
            if self._signal_hit(s, text, norm)
        )
        neg_hits = sum(
            1 for s in NEGATIVE_SIGNALS
            if self._signal_hit(s, text, norm)
        )
        if pos_hits > neg_hits:
            return 1
        if neg_hits > pos_hits:
            return -1
        return 0

    @staticmethod
    def _signal_hit(signal: str, raw: str, norm: str) -> bool:
        """信号匹配: 英文整词 (原文, 词边界) / 中文子串 (归一化)"""
        if not signal:
            return False
        if signal.isascii() and signal.isalpha():
            return re.search(
                rf"\b{re.escape(signal)}\b", raw,
            ) is not None
        return normalize_text(signal) in norm

    def stats(self) -> Dict[str, Any]:
        """冲突检测统计"""
        with self._lock:
            return {
                "mode": "rule_based",
                "enabled": self._enabled,
                "detect_count": self._detect_count,
            }

    def clear(self) -> int:
        """清空计数 (测试隔离)"""
        with self._lock:
            n = self._detect_count
            self._detect_count = 0
            return n


__all__ = [
    "ConflictDetectorError",
    "MemoryConflictDetector",
    "NEGATIVE_SIGNALS",
    "POSITIVE_SIGNALS",
]
