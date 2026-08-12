"""
YHLZ Embodied AI V4.1 - 反馈处理器 (Feedback Processor)

职责:
    - FeedbackStore: 反馈记录 + 指标统计 (成功/失败/耗时)
    - FeedbackProcessor: 编排处理链路:
        Feedback 到达 → 存储 → 分析器分析 → 写入环境记忆 → 世界模型对照

设计原则:
    - 内存缓冲 (deque, 可配置上限) + 可选 JSONL 落盘
    - 线程安全 (RLock)
    - 数据独立存储 (绝不写入 Agent Memory)
    - 处理链路可注入 (analyzer / memory 可替换)
"""
from __future__ import annotations

import json
import logging
import threading
from collections import deque
from typing import Any, Deque, Dict, List, Optional

from backend.embodied.feedback.analyzer import FeedbackAnalyzer
from backend.embodied.schema import (
    EmbodiedAction,
    EnvironmentState,
    Feedback,
    FeedbackAnalysis,
    FeedbackResult,
)

logger = logging.getLogger(__name__)


class FeedbackStoreError(Exception):
    """反馈存储操作异常"""


class FeedbackStore:
    """反馈存储与统计

    用法:
        store = FeedbackStore(max_entries=200)
        store.add(feedback)
        stats = store.stats()
    """

    def __init__(self, max_entries: int = 200):
        if max_entries <= 0:
            raise FeedbackStoreError(f"max_entries 必须 > 0, 当前: {max_entries}")
        self._lock = threading.RLock()
        self._entries: Deque[Feedback] = deque(maxlen=max_entries)
        self._max_entries = max_entries

    # ── 记录 ──────────────────────────────────────────────────────
    def add(self, feedback: Feedback) -> Feedback:
        """添加反馈记录"""
        if feedback is None:
            raise FeedbackStoreError("反馈不能为 None")
        with self._lock:
            self._entries.append(feedback)
        logger.debug(
            f"[Feedback] 记录 action_id={feedback.action_id} "
            f"result={feedback.result}"
        )
        return feedback

    # ── 查询 ──────────────────────────────────────────────────────
    def get(self, action_id: str) -> Optional[Feedback]:
        """按 action_id 查询反馈 (None=未找到)"""
        with self._lock:
            for e in reversed(self._entries):
                if e.action_id == action_id:
                    return e
        return None

    def query(
        self,
        result: Optional[str] = None,
        action_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[Feedback]:
        """查询反馈 (按条件过滤, 最新在前)"""
        with self._lock:
            entries = list(self._entries)
        out: List[Feedback] = []
        for e in reversed(entries):
            if result and e.result != result:
                continue
            if action_id and e.action_id != action_id:
                continue
            out.append(e)
            if len(out) >= limit:
                break
        return out

    def query_dicts(
        self,
        result: Optional[str] = None,
        action_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """查询反馈 (dict 形式)"""
        return [e.to_dict() for e in self.query(result=result, action_id=action_id, limit=limit)]

    # ── 统计 ──────────────────────────────────────────────────────
    def stats(self) -> Dict[str, Any]:
        """统计信息 + 性能指标"""
        with self._lock:
            entries = list(self._entries)
        total = len(entries)
        if total == 0:
            return {
                "total": 0, "success_count": 0, "success_rate": 0.0,
                "failure_count": 0, "failure_rate": 0.0,
                "partial_count": 0, "no_change_count": 0,
                "avg_latency_ms": 0.0,
            }
        success = sum(1 for e in entries if e.result == FeedbackResult.SUCCESS.value)
        failure = sum(1 for e in entries if e.result == FeedbackResult.FAILURE.value)
        partial = sum(1 for e in entries if e.result == FeedbackResult.PARTIAL.value)
        no_change = sum(1 for e in entries if e.result == FeedbackResult.NO_CHANGE.value)
        latencies = [e.latency_ms for e in entries]
        return {
            "total": total,
            "success_count": success,
            "success_rate": round(success / total, 4),
            "failure_count": failure,
            "failure_rate": round(failure / total, 4),
            "partial_count": partial,
            "no_change_count": no_change,
            "avg_latency_ms": round(sum(latencies) / len(latencies), 2),
        }

    # ── 持久化 ────────────────────────────────────────────────────
    def save_to_file(self, path: str) -> int:
        """保存反馈到 JSONL 文件"""
        with self._lock:
            entries = list(self._entries)
        with open(path, "w", encoding="utf-8") as f:
            for e in entries:
                f.write(json.dumps(e.to_dict(), ensure_ascii=False) + "\n")
        logger.info(f"[Feedback] 已保存到 {path}, 共 {len(entries)} 条")
        return len(entries)

    # ── 生命周期 ──────────────────────────────────────────────────
    def clear(self) -> int:
        """清空反馈, 返回清理数量"""
        with self._lock:
            n = len(self._entries)
            self._entries.clear()
        logger.info(f"[Feedback] 反馈已清空, 清理 {n} 条")
        return n

    def count(self) -> int:
        with self._lock:
            return len(self._entries)

    @property
    def max_entries(self) -> int:
        with self._lock:
            return self._max_entries


class FeedbackProcessor:
    """反馈处理器: 编排 存储 → 分析 → 记忆 → 对照

    用法:
        processor = FeedbackProcessor(analyzer=analyzer)
        analysis = processor.process(feedback, action=action, state=state,
                                     world_model=wm, memory=mem)
    """

    def __init__(
        self,
        store: Optional[FeedbackStore] = None,
        analyzer: Optional[FeedbackAnalyzer] = None,
    ):
        self._lock = threading.RLock()
        self._store: FeedbackStore = store or FeedbackStore()
        self._analyzer: FeedbackAnalyzer = analyzer or FeedbackAnalyzer()

    @property
    def store(self) -> FeedbackStore:
        return self._store

    @property
    def analyzer(self) -> FeedbackAnalyzer:
        return self._analyzer

    # ── 处理链路 ──────────────────────────────────────────────────
    def process(
        self,
        feedback: Feedback,
        action: Optional[EmbodiedAction] = None,
        state: Optional[EnvironmentState] = None,
        world_model: Any = None,
        memory: Any = None,
    ) -> FeedbackAnalysis:
        """处理反馈: 存储 → 分析 → 记忆 → 世界模型对照

        Args:
            feedback:  行动反馈 (必填)
            action:    对应动作 (可选)
            state:     动作后状态 (可选)
            world_model: WorldModel 实例 (可选, 用于状态对照)
            memory:     EnvironmentMemory 实例 (可选, 用于记忆)

        Returns:
            FeedbackAnalysis
        """
        # 1. 存储
        self._store.add(feedback)

        # 2. 分析
        analysis = self._analyzer.analyze(feedback, action=action, state=state)

        # 3. 记忆 (Embodied 专用, 独立于 Agent Memory)
        if memory is not None:
            memory.record_action(
                feedback=feedback.to_dict(),
                analysis=analysis.to_dict(),
                metadata={"action_type": action.action_type if action else ""},
            )
            if feedback.environment_change:
                memory.record_change(
                    change=feedback.environment_change,
                    state_id=feedback.new_state.state_id if feedback.new_state else "",
                )

        # 4. 世界模型对照 (若提供)
        if world_model is not None:
            latest = world_model.get_latest()
            if latest is not None and state is not None:
                try:
                    diff = world_model.diff_states(latest, state)
                    analysis.environment_change.setdefault("state_diff", diff)
                except Exception as e:
                    logger.warning(f"[Feedback] 状态对照失败: {e}")

        logger.info(
            f"[Feedback] 处理完成 action_id={feedback.action_id} "
            f"result={feedback.result} analysis.success={analysis.success}"
        )
        return analysis

    def stats(self) -> Dict[str, Any]:
        return {
            "store": self._store.stats(),
            "analyzer": self._analyzer.stats(),
        }

    def reset(self) -> None:
        with self._lock:
            self._store.clear()
            self._analyzer.reset()


__all__ = ["FeedbackStore", "FeedbackStoreError", "FeedbackProcessor"]
