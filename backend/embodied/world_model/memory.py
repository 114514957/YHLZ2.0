"""
YHLZ Embodied AI V4.2 - 环境记忆 (Environment Memory)

职责:
    - 保存环境变化 (change)
    - 保存行动结果 (action / feedback / analysis, 含因果 cause)
    - 保存状态历史 (state)
    - 为 Embodied 层提供专用记忆查询
    - 经验摘要 (V4.2): summary() → 高频失败模式 / 成功率趋势 / 因果统计
    - 跨进程加载 (V4.2): embodied_memory_path 持久化

设计原则:
    - Embodied 专用 Memory: 绝不替代 Memory Core / Vision Memory / Agent Memory
    - 数据独立存储 (本模块内存缓冲 + 可选 JSONL 落盘)
    - 线程安全 (RLock)
    - 可查询 (按类型 / 按 action_id)
    - 可重置 (测试隔离)
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections import deque
from typing import Any, Deque, Dict, List, Optional

from backend.embodied.schema import ExperienceSummary

logger = logging.getLogger(__name__)


class EnvironmentMemoryError(Exception):
    """环境记忆操作异常"""


class EnvironmentMemory:
    """环境记忆 (Embodied 专用)

    条目类型 (entry['type']):
        - 'change':  环境变化摘要 (来自 WorldStateHistory)
        - 'action':  行动结果 (feedback + analysis)
        - 'state':   状态快照摘要
        - 'event':   环境事件 (reset 等)

    用法:
        mem = EnvironmentMemory(max_entries=100)
        mem.record_change(change_dict)
        mem.record_action(feedback_dict, analysis_dict)
        entries = mem.query(type='action', limit=10)
    """

    def __init__(self, max_entries: int = 100):
        if max_entries <= 0:
            raise EnvironmentMemoryError(f"max_entries 必须 > 0, 当前: {max_entries}")
        self._lock = threading.RLock()
        self._entries: Deque[Dict[str, Any]] = deque(maxlen=max_entries)
        self._max_entries = max_entries

    # ── 记录 ──────────────────────────────────────────────────────
    def record_change(
        self,
        change: Dict[str, Any],
        state_id: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """记录环境变化, 返回条目 ID"""
        entry_id = f"chg-{int(time.time() * 1000)}-{len(self._entries)}"
        self._append({
            "entry_id": entry_id,
            "type": "change",
            "state_id": state_id,
            "change": change or {},
            "metadata": metadata or {},
            "timestamp": time.time(),
        })
        return entry_id

    def record_action(
        self,
        feedback: Dict[str, Any],
        analysis: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """记录行动结果 (feedback + 分析), 返回条目 ID"""
        entry_id = f"act-{int(time.time() * 1000)}-{len(self._entries)}"
        self._append({
            "entry_id": entry_id,
            "type": "action",
            "action_id": (feedback or {}).get("action_id", ""),
            "feedback": feedback or {},
            "analysis": analysis or {},
            "metadata": metadata or {},
            "timestamp": time.time(),
        })
        return entry_id

    def record_state(
        self,
        state: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """记录状态快照摘要, 返回条目 ID"""
        entry_id = f"st-{int(time.time() * 1000)}-{len(self._entries)}"
        self._append({
            "entry_id": entry_id,
            "type": "state",
            "state_id": (state or {}).get("state_id", ""),
            "state": state or {},
            "metadata": metadata or {},
            "timestamp": time.time(),
        })
        return entry_id

    def record_event(
        self,
        event: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """记录环境事件 (如 reset), 返回条目 ID"""
        entry_id = f"evt-{int(time.time() * 1000)}-{len(self._entries)}"
        self._append({
            "entry_id": entry_id,
            "type": "event",
            "event": event,
            "metadata": metadata or {},
            "timestamp": time.time(),
        })
        return entry_id

    def _append(self, entry: Dict[str, Any]) -> None:
        with self._lock:
            self._entries.append(entry)

    # ── 查询 ──────────────────────────────────────────────────────
    def query(
        self,
        type: Optional[str] = None,
        action_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """查询记忆条目 (按类型/action_id 过滤, 最新在前)"""
        with self._lock:
            entries = list(self._entries)
        out: List[Dict[str, Any]] = []
        for e in reversed(entries):
            if type and e.get("type") != type:
                continue
            if action_id and e.get("action_id") != action_id:
                continue
            out.append(e)
            if len(out) >= limit:
                break
        return out

    def get(self, entry_id: str) -> Optional[Dict[str, Any]]:
        """按 entry_id 查询条目"""
        with self._lock:
            for e in reversed(self._entries):
                if e.get("entry_id") == entry_id:
                    return e
        return None

    def count(self) -> int:
        with self._lock:
            return len(self._entries)

    def stats(self) -> Dict[str, Any]:
        """统计: 各类型条目数量"""
        with self._lock:
            entries = list(self._entries)
        types = {}
        for e in entries:
            types[e.get("type", "unknown")] = types.get(e.get("type", "unknown"), 0) + 1
        return {
            "total": len(entries),
            "by_type": types,
        }

    def latest_change(self) -> Optional[Dict[str, Any]]:
        """最近一条环境变化记录"""
        with self._lock:
            for e in reversed(self._entries):
                if e.get("type") == "change":
                    return e
        return None

    def latest_action(self) -> Optional[Dict[str, Any]]:
        """最近一条行动结果记录"""
        with self._lock:
            for e in reversed(self._entries):
                if e.get("type") == "action":
                    return e
        return None

    # ── 经验摘要 (V4.2) ───────────────────────────────────────────
    def summary(
        self,
        trend_bucket_size: int = 10,
        top_failures: int = 5,
    ) -> ExperienceSummary:
        """生成具身经验摘要

        内容:
            - 行动统计: total / success_count / success_rate
            - failure_patterns: 高频失败模式 (cause → 次数 + 示例)
            - success_trends: 成功率趋势 (按 N 条一桶)
            - cause_stats: 因果统计 (cause → 次数)
            - top_failures: 最近失败事件示例
        """
        with self._lock:
            entries = list(self._entries)
        actions = [e for e in entries if e.get("type") == "action"]

        total = len(actions)
        if total == 0:
            return ExperienceSummary.create(
                total_actions=0, success_count=0, success_rate=0.0,
                failure_patterns=[], success_trends=[],
                cause_stats={}, top_failures=[],
            )

        success_count = sum(
            1 for e in actions
            if (e.get("feedback") or {}).get("result") == "success"
        )
        success_rate = success_count / total

        # 失败模式: 按 cause 聚合
        pattern_counts: Dict[str, int] = {}
        examples: Dict[str, str] = {}
        failures: List[Dict[str, Any]] = []
        cause_stats: Dict[str, int] = {}
        for e in reversed(actions):
            analysis = e.get("analysis") or {}
            feedback = e.get("feedback") or {}
            result = feedback.get("result", "")
            cause = analysis.get("cause") or feedback.get("cause") or "no_cause"
            cause_stats[cause] = cause_stats.get(cause, 0) + 1
            if result == "success":
                continue
            pattern_counts[cause] = pattern_counts.get(cause, 0) + 1
            if cause not in examples:
                examples[cause] = (
                    analysis.get("cause_detail")
                    or analysis.get("failure_reason")
                    or feedback.get("error")
                    or ""
                )
            failures.append({
                "action_id": e.get("action_id", ""),
                "result": result,
                "cause": cause,
                "reason": analysis.get("failure_reason") or feedback.get("error"),
                "timestamp": e.get("timestamp", 0.0),
            })

        failure_patterns = [
            {
                "cause": cause,
                "count": count,
                "example": examples.get(cause, ""),
            }
            for cause, count in sorted(
                pattern_counts.items(), key=lambda kv: kv[1], reverse=True,
            )
        ]

        # 成功率趋势 (按 trend_bucket_size 条一桶)
        bucket_size = max(1, int(trend_bucket_size))
        trends: List[Dict[str, Any]] = []
        for start in range(0, total, bucket_size):
            bucket = actions[total - start - bucket_size: total - start]
            if not bucket:
                break
            ok = sum(
                1 for e in bucket
                if (e.get("feedback") or {}).get("result") == "success"
            )
            trends.append({
                "bucket": start // bucket_size,
                "from": start,
                "to": min(start + bucket_size, total),
                "success_rate": round(ok / len(bucket), 4),
            })
        trends.reverse()

        return ExperienceSummary.create(
            total_actions=total, success_count=success_count,
            success_rate=round(success_rate, 4),
            failure_patterns=failure_patterns,
            success_trends=trends,
            cause_stats=cause_stats,
            top_failures=failures[:top_failures],
        )

    # ── 跨进程持久化 (V4.2) ───────────────────────────────────────
    def load_or_init(self, path: Optional[str]) -> None:
        """从路径加载记忆 (路径不存在时静默跳过, 供跨进程复用)"""
        if not path:
            return
        if not os.path.isfile(path):
            logger.info(f"[EmbodiedMemory] 记忆文件不存在, 跳过加载: {path}")
            return
        try:
            self.load_from_file(path)
        except Exception as e:
            logger.warning(f"[EmbodiedMemory] 加载记忆失败: {e}")

    # ── 持久化 (JSONL) ────────────────────────────────────────────
    def save_to_file(self, path: str) -> int:
        """保存全部记忆到 JSONL 文件"""
        with self._lock:
            entries = list(self._entries)
        with open(path, "w", encoding="utf-8") as f:
            for e in entries:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
        logger.info(f"[EmbodiedMemory] 已保存到 {path}, 共 {len(entries)} 条")
        return len(entries)

    def load_from_file(self, path: str) -> int:
        """从 JSONL 文件加载记忆"""
        loaded = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    loaded.append(json.loads(line))
                except json.JSONDecodeError as e:
                    logger.warning(f"[EmbodiedMemory] 跳过坏行: {e}")
        with self._lock:
            for e in loaded:
                self._entries.append(e)
        logger.info(f"[EmbodiedMemory] 已从 {path} 加载 {len(loaded)} 条")
        return len(loaded)

    # ── 生命周期 ──────────────────────────────────────────────────
    def clear(self) -> int:
        """清空记忆, 返回清理数量"""
        with self._lock:
            n = len(self._entries)
            self._entries.clear()
        logger.info(f"[EmbodiedMemory] 记忆已清空, 清理 {n} 条")
        return n

    @property
    def max_entries(self) -> int:
        with self._lock:
            return self._max_entries


__all__ = ["EnvironmentMemory", "EnvironmentMemoryError"]
