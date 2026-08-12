"""
YHLZ Token Optimization Layer V10.1.3 - 对话压缩器 (Conversation Compressor)

职责:
    - 对话压缩: 10000 Token → 1000 Token (总结)
    - 保存: 关键结论 / 重要决定 / 未解决问题 / 下一步
    - 禁止保存全部聊天

设计原则:
    - 压缩规则可解释 (rule/reason)
    - 压缩结果结构化 (关键结论/决定/问题/下一步)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class CompressorError(Exception):
    """对话压缩器异常"""


class ConversationCompressor:
    """对话压缩器 (V10.1.3)

    用法:
        cc = ConversationCompressor(compress_ratio=0.1)
        r = cc.compress("长对话文本...")
        # r = {compressed, summary, key_points, decisions,
        #      open_questions, next_steps}
    """

    def __init__(
        self,
        compress_ratio: float = 0.1,
        max_summary_len: int = 1000,
        enabled: bool = True,
    ):
        if not (0.0 < compress_ratio <= 1.0):
            raise CompressorError(
                f"compress_ratio 必须在 (0,1], 当前: {compress_ratio}"
            )
        self._lock = threading.RLock()
        self._compress_ratio = float(compress_ratio)
        self._max_summary_len = int(max_summary_len)
        self._enabled = bool(enabled)
        self._records: List[Dict[str, Any]] = []

    def compress(
        self,
        text: str,
        key_points: Optional[List[str]] = None,
        decisions: Optional[List[str]] = None,
        open_questions: Optional[List[str]] = None,
        next_steps: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """压缩对话 (总结 + 结构化要点)"""
        with self._lock:
            if not self._enabled:
                return {"mode": "error_frame", "ok": False,
                        "reason": "对话压缩器停用"}
            raw = str(text or "")
            target_len = max(
                10, int(len(raw) * self._compress_ratio),
            )
            summary = self._summarize(raw, target_len)
            record = {
                "compress_id": "cc_" + uuid.uuid4().hex[:10],
                "timestamp": time.time(),
                "original_len": len(raw),
                "compressed_len": len(summary),
                "ratio": round(
                    len(summary) / len(raw), 4,
                ) if raw else 0.0,
                "summary": summary,
                "key_points": list(key_points or []),
                "decisions": list(decisions or []),
                "open_questions": list(open_questions or []),
                "next_steps": list(next_steps or []),
            }
            self._records.append(record)
            if len(self._records) > 200:
                self._records = self._records[-200:]
            return {
                "mode": "rule_based", "ok": True,
                "compressed": summary,
                "summary": summary,
                "original_len": len(raw),
                "compressed_len": len(summary),
                "ratio": record["ratio"],
                "key_points": record["key_points"],
                "decisions": record["decisions"],
                "open_questions": record["open_questions"],
                "next_steps": record["next_steps"],
                "reason": (
                    f"压缩 {len(raw)} → {len(summary)} "
                    f"(目标 {target_len})"
                ),
            }

    def _summarize(self, text: str, target_len: int) -> str:
        """规则总结: 头部保留 + 关键句提取"""
        if len(text) <= target_len:
            return text
        # 简单规则: 保留前 40% 与关键句 (含结论/决定/下一步关键词)
        head_len = max(10, int(target_len * 0.5))
        head = text[:head_len]
        tail_budget = target_len - head_len - 3
        key_sentences = []
        for sentence in text.split("。"):
            if any(k in sentence for k in (
                "结论", "决定", "下一步", "问题", "注意", "完成",
            )):
                key_sentences.append(sentence)
        tail = ""
        for s in key_sentences:
            if len(tail) + len(s) + 1 <= tail_budget:
                tail += s + "。"
        if not tail:
            tail = text[-tail_budget:] if tail_budget > 0 else ""
        return head + "..." + tail

    def history(self, limit: int = 50) -> List[Dict[str, Any]]:
        """压缩历史 (最新在前)"""
        with self._lock:
            records = list(self._records)
        out = []
        for r in reversed(records):
            out.append(dict(r))
            if 0 < limit <= len(out):
                break
        return out

    def stats(self) -> Dict[str, Any]:
        """统计"""
        with self._lock:
            total_original = sum(
                r["original_len"] for r in self._records
            )
            total_compressed = sum(
                r["compressed_len"] for r in self._records
            )
            return {
                "mode": "rule_based",
                "enabled": self._enabled,
                "compress_ratio": self._compress_ratio,
                "total_compressions": len(self._records),
                "total_original_len": total_original,
                "total_compressed_len": total_compressed,
                "saved_ratio": round(
                    1.0 - (total_compressed / total_original), 4,
                ) if total_original else 0.0,
            }

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = len(self._records)
            self._records.clear()
            return n


__all__ = [
    "CompressorError",
    "ConversationCompressor",
]
