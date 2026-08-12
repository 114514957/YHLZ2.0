"""
YHLZ Embodied AI V10.1 - 交互上下文筛选器 (Interaction Context Filter)

职责:
    - 上下文必须经过筛选 (不能直接等同长期记忆)
    - 从原始输入中提取结构化上下文: 主题 / 实体 / 目标 / 约束
    - 只保留当前会话相关的关键信息

设计原则:
    - 上下文 ≠ 长期记忆 (筛选后短期使用, 不写入记忆存储)
    - 规则可解释 (筛选理由)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ContextFilterError(Exception):
    """上下文筛选异常"""


# 上下文主题关键词 (可扩展)
TOPIC_KEYWORDS: Dict[str, List[str]] = {
    "task": ["任务", "完成", "处理", "执行", "task", "todo"],
    "plan": ["计划", "方案", "规划", "plan", "scheme"],
    "chat": ["聊聊", "聊天", "闲谈", "chat", "talk"],
    "problem": ["问题", "故障", "报错", "错误", "bug", "issue"],
    "memory": ["记得", "记忆", "上次", "remember"],
}


class InteractionContextFilter:
    """交互上下文筛选器 (V10.1)

    用法:
        f = InteractionContextFilter()
        ctx = f.filter("请完成任务并处理问题", max_len=200)
    """

    def __init__(self, max_len: int = 200, enabled: bool = True):
        if max_len <= 0:
            raise ContextFilterError(
                f"max_len 必须 > 0, 当前: {max_len}"
            )
        self._lock = threading.RLock()
        self._max_len = int(max_len)
        self._enabled = bool(enabled)
        self._filter_count = 0

    def filter(
        self,
        text: str,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """筛选上下文 (主题/实体/目标/约束 + 裁剪)

        Args:
            text: 原始输入
            extra: 附加字段 (来源/时间等, 透传)

        Returns:
            {
                "mode", "enabled", "source_len", "filtered_len",
                "topic", "entities", "goal", "constraints",
                "summary", "clipped", "reason",
            }
        """
        with self._lock:
            if not self._enabled:
                return {"mode": "error_frame", "ok": False,
                        "reason": "上下文筛选器停用"}
            raw = str(text or "")
            topic = self._detect_topic(raw)
            entities = self._extract_entities(raw)
            goal = self._extract_goal(raw)
            constraints = self._extract_constraints(raw)
            summary = self._clip(raw)
            self._filter_count += 1
            return {
                "mode": "rule_based",
                "enabled": self._enabled,
                "source_len": len(raw),
                "filtered_len": len(summary),
                "topic": topic,
                "entities": entities,
                "goal": goal,
                "constraints": constraints,
                "summary": summary,
                "clipped": len(raw) > self._max_len,
                "reason": "上下文筛选: 主题/实体/目标提取 + 摘要裁剪, "
                          "不等同长期记忆",
                "extra": dict(extra or {}),
            }

    def _detect_topic(self, text: str) -> str:
        """主题检测 (关键词规则)"""
        for topic, kws in TOPIC_KEYWORDS.items():
            for kw in kws:
                if kw in text:
                    return topic
        return "general"

    def _extract_entities(self, text: str) -> List[str]:
        """实体提取 (规则: 引号/书名号内容 + 数字编号)"""
        entities: List[str] = []
        for ch in ("「", "『", "\""):
            if ch in text:
                for seg in text.split(ch)[1:]:
                    if "」" in seg:
                        entities.append(seg.split("」")[0])
                    elif "』" in seg:
                        entities.append(seg.split("』")[0])
                    elif "\"" in seg:
                        entities.append(seg.split("\"")[0])
        return list(dict.fromkeys(entities))[:5]

    def _extract_goal(self, text: str) -> str:
        """目标提取 (动词+宾语规则)"""
        for verb in ("完成", "处理", "实现", "修复", "做", "执行"):
            idx = text.find(verb)
            if idx >= 0:
                return text[idx:idx + 20].strip()
        return ""

    def _extract_constraints(self, text: str) -> List[str]:
        """约束提取 (禁止/必须/不要 等)"""
        constraints: List[str] = []
        for word in ("禁止", "必须", "不要", "不能", "不得"):
            idx = text.find(word)
            if idx >= 0:
                constraints.append(text[idx:idx + 15].strip())
        return constraints[:3]

    def _clip(self, text: str) -> str:
        """摘要裁剪"""
        if len(text) <= self._max_len:
            return text
        head = self._max_len // 2
        tail = self._max_len - head - 3
        return text[:head] + "..." + text[-tail:]

    def stats(self) -> Dict[str, Any]:
        """统计"""
        with self._lock:
            return {
                "mode": "rule_based",
                "enabled": self._enabled,
                "max_len": self._max_len,
                "filter_count": self._filter_count,
            }

    def clear(self) -> int:
        """清空计数 (测试隔离)"""
        with self._lock:
            n = self._filter_count
            self._filter_count = 0
            return n


__all__ = [
    "ContextFilterError",
    "InteractionContextFilter",
    "TOPIC_KEYWORDS",
]
