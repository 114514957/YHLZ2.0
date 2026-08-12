"""
YHLZ Input Aggregator V10.1.8

职责:
    - 连续输入治理: 分类 / 合并 / 优先级队列
    - 功能:
      - 重复问题合并
      - 无意义输入降权
      - 重要问题优先
      - 直播弹幕筛选

流程:
    Input Stream → Classifier → Merge → Priority Queue → Conversation Manager

设计原则:
    - FIFO Queue 不作为最终方案, 增加治理层
    - 规则可解释 (rule/reason)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from collections import deque
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class InputAggregatorError(Exception):
    """输入治理器异常"""


# 输入分类 (可解释)
INPUT_CLASSES: List[str] = [
    "important",   # 重要问题: 任务/问题/方案/决策
    "normal",      # 普通对话
    "chat",        # 闲聊
    "noise",       # 无意义/弹幕噪声
]

# 优先级 (重要 > 普通 > 闲聊)
PRIORITY_MAP: Dict[str, int] = {
    "important": 3,
    "normal": 2,
    "chat": 1,
    "noise": 0,
}

# 重要信号词
IMPORTANT_KEYWORDS: List[str] = [
    "任务", "问题", "方案", "决策", "修复", "实现",
    "部署", "架构", "设计", "错误", "bug", "计划",
]

# 闲聊信号词
CHAT_KEYWORDS: List[str] = [
    "哈哈", "嘻嘻", "随便", "聊聊", "在吗", "你好呀",
    "666", "好棒", "无聊",
]

# 噪声信号词 (弹幕/无意义)
NOISE_KEYWORDS: List[str] = [
    "666", "233", "hhh", "路过", "打卡", "111",
]


class InputItem:
    """治理后输入项"""

    def __init__(
        self,
        text: str,
        source: str = "user",
        input_class: str = "normal",
    ):
        self.input_id = "in_" + uuid.uuid4().hex[:10]
        self.text = str(text)
        self.source = str(source)
        self.input_class = input_class
        self.priority = PRIORITY_MAP.get(input_class, 2)
        self.timestamp = time.time()
        self.merged_from: List[str] = []
        self.dropped = False
        self.drop_reason = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "input_id": self.input_id,
            "text": self.text[:200],
            "source": self.source,
            "input_class": self.input_class,
            "priority": self.priority,
            "timestamp": self.timestamp,
            "merged_from": list(self.merged_from),
            "dropped": self.dropped,
            "drop_reason": self.drop_reason,
        }


class InputAggregator:
    """输入治理器 (V10.1.8)

    用法:
        agg = InputAggregator()
        item = agg.process("帮我修个bug")
        next_item = agg.next()
    """

    def __init__(
        self,
        max_queue: int = 30,
        merge_threshold: float = 0.8,
        enabled: bool = True,
    ):
        if max_queue <= 0:
            raise InputAggregatorError(
                f"max_queue 必须 > 0, 当前: {max_queue}"
            )
        self._lock = threading.RLock()
        self._enabled = bool(enabled)
        self._max_queue = int(max_queue)
        self._merge_threshold = float(merge_threshold)
        self._queue: deque = deque()
        self._history: List[InputItem] = []
        self._stats: Dict[str, int] = {
            "processed": 0, "merged": 0, "dropped": 0,
        }

    # ── 处理链 ─────────────────────────────────────────────────
    def process(
        self,
        text: str,
        source: str = "user",
    ) -> InputItem:
        """Input Stream → Classifier → Merge → Priority Queue"""
        with self._lock:
            if not self._enabled:
                raise InputAggregatorError("输入治理器停用")
            # 1. 分类
            input_class = self._classify(text)
            item = InputItem(text, source, input_class)

            # 2. 噪声丢弃
            if input_class == "noise":
                item.dropped = True
                item.drop_reason = "无意义输入/弹幕噪声"
                self._stats["dropped"] += 1
                self._history.append(item)
                return item

            # 3. 重复合并 (与队列中同 class 高相似输入合并)
            self._merge_duplicates(item)

            # 4. 入队 (按优先级插入)
            if len(self._queue) >= self._max_queue:
                # 队满: 新输入优先级高于队内最低 → 挤掉; 否则拒绝新输入
                self._handle_queue_full(item)
            self._insert_by_priority(item)

            self._stats["processed"] += 1
            self._history.append(item)
            if len(self._history) > 200:
                self._history = self._history[-200:]
            return item

    def _classify(self, text: str) -> str:
        """Classifier: 关键词规则分类"""
        content = str(text or "")
        if any(k in content for k in NOISE_KEYWORDS) and \
                len(content) <= 4:
            return "noise"
        important = sum(
            1 for k in IMPORTANT_KEYWORDS if k in content
        )
        chat = sum(1 for k in CHAT_KEYWORDS if k in content)
        if important >= 1:
            return "important"
        if chat >= 1 and important == 0:
            return "chat"
        return "normal"

    def _merge_duplicates(self, item: InputItem) -> None:
        """Merge: 与队列中相似输入合并 (内容重叠率)"""
        for existing in list(self._queue):
            if existing.input_class != item.input_class:
                continue
            overlap = self._text_overlap(item.text, existing.text)
            if overlap >= self._merge_threshold:
                existing.merged_from.append(item.text[:100])
                item.dropped = True
                item.drop_reason = (
                    f"与 {existing.input_id} 重复 "
                    f"(重叠率 {overlap:.0%})"
                )
                self._stats["merged"] += 1
                return

    @staticmethod
    def _text_overlap(a: str, b: str) -> float:
        """文本重叠率"""
        if not a or not b:
            return 0.0
        a_set, b_set = set(a), set(b)
        inter = len(a_set & b_set)
        return inter / max(len(a_set), len(b_set))

    def _insert_by_priority(self, item: InputItem) -> None:
        """Priority Queue: 按优先级插入 (高优先在前)"""
        inserted = False
        for i, existing in enumerate(self._queue):
            if item.priority > existing.priority:
                self._queue.insert(i, item)
                inserted = True
                break
        if not inserted:
            self._queue.append(item)

    def _handle_queue_full(self, item: InputItem) -> None:
        """队满处理: 新输入 vs 队内最低优先级"""
        # 找队内最低优先级项
        lowest_idx = -1
        lowest_pri = 99
        for i, existing in enumerate(self._queue):
            if existing.priority < lowest_pri:
                lowest_pri = existing.priority
                lowest_idx = i
        # 新输入优先级 ≤ 队内最低 → 拒绝新输入 (不挤占)
        if item.priority <= lowest_pri:
            item.dropped = True
            item.drop_reason = f"队列已满且优先级低 (min={lowest_pri})"
            self._stats["dropped"] += 1
            return
        # 新输入优先级更高 → 挤掉队内最低
        evicted = self._queue[lowest_idx]
        evicted.dropped = True
        evicted.drop_reason = f"被更高优先级输入挤掉"
        del self._queue[lowest_idx]
        self._stats["dropped"] += 1

    # ── 查询 ────────────────────────────────────────────────────
    def next(self) -> Optional[InputItem]:
        """取下一个输入 (按优先级)"""
        with self._lock:
            while self._queue:
                item = self._queue.popleft()
                if not item.dropped:
                    return item
            return None

    def peek(self) -> Optional[InputItem]:
        """查看下一个 (不移除)"""
        with self._lock:
            for item in self._queue:
                if not item.dropped:
                    return item
            return None

    def queue_length(self) -> int:
        with self._lock:
            return sum(1 for i in self._queue if not i.dropped)

    def stats(self) -> Dict[str, Any]:
        """统计"""
        with self._lock:
            return {
                "mode": "rule_based",
                "enabled": self._enabled,
                "max_queue": self._max_queue,
                "queue_length": self.queue_length(),
                "processed": self._stats["processed"],
                "merged": self._stats["merged"],
                "dropped": self._stats["dropped"],
            }

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = len(self._queue)
            self._queue.clear()
            self._history.clear()
            self._stats = {
                "processed": 0, "merged": 0, "dropped": 0,
            }
            return n


__all__ = [
    "IMPORTANT_KEYWORDS",
    "INPUT_CLASSES",
    "InputAggregator",
    "InputAggregatorError",
    "InputItem",
    "PRIORITY_MAP",
]
