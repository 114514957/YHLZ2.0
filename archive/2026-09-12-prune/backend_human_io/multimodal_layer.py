"""
YHLZ Multimodal Experience Layer V10.1.2 - 多模态经验输入层

职责:
    - 输入: Camera / Screen / Audio / Video / Stream / 弹幕
    - 流程: Input → Detection → Understanding → Importance Evaluation
      → Memory Decision → Storage / Discard
    - 评分规则: 0-4 丢弃 / 5-7 短期记忆 / 8-10 长期候选
    - 弹幕: Noise Filter → Intent Analysis → Value Assessment → Memory Decision

设计原则:
    - 禁止逐帧永久保存 / 禁止弹幕全部保存 / 禁止垃圾信息污染 Memory
    - 价值判断 (0-10) 可解释
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class MultimodalError(Exception):
    """多模态经验层异常"""


# 输入类型 (可解释)
INPUT_TYPES: List[str] = [
    "camera",   # 摄像头
    "screen",   # 屏幕
    "audio",    # 音频
    "video",    # 视频
    "stream",   # 直播流
    "danmaku",  # 弹幕
]

# 分类 (可解释)
CLASSIFICATIONS: List[str] = [
    "high_value",  # 高价值 → 进入候选记忆
    "temporary",   # 临时 → 仅当前任务
    "noise",       # 噪声 → 丢弃
]

# 评分区间 (可解释)
SCORE_DISCARD_MAX: int = 4    # 0-4 丢弃
SCORE_SHORT_MIN: int = 5      # 5-7 短期记忆
SCORE_LONG_MIN: int = 8       # 8-10 长期候选


class MultimodalExperienceLayer:
    """多模态经验输入层 (V10.1.2)

    用法:
        layer = MultimodalExperienceLayer()
        r = layer.process("screen", "完成项目部署", source="user")
        r = layer.process("danmaku", "666", source="stream")
    """

    def __init__(
        self,
        max_records: int = 2000,
        enabled: bool = True,
    ):
        if max_records <= 0:
            raise MultimodalError(
                f"max_records 必须 > 0, 当前: {max_records}"
            )
        self._lock = threading.RLock()
        self._max_records = int(max_records)
        self._enabled = bool(enabled)
        self._records: List[Dict[str, Any]] = []
        self._discard_count = 0

    def process(
        self,
        input_type: str,
        content: str,
        source: str = "",
        context: str = "",
    ) -> Dict[str, Any]:
        """处理多模态输入 (检测→理解→价值评估→记忆决策)

        Args:
            input_type: 输入类型 (INPUT_TYPES)
            content: 内容/描述
            source: 来源
            context: 上下文 (任务/场景)

        Returns:
            {
                'mode', 'input_type', 'classification',
                'importance_score', 'memory_decision',
                'reason', 'record_id',
            }
        """
        with self._lock:
            if not self._enabled:
                return {"mode": "error_frame", "ok": False,
                        "reason": "多模态经验层停用"}
            if input_type not in INPUT_TYPES:
                raise MultimodalError(
                    f"非法输入类型: {input_type} "
                    f"(可选: {INPUT_TYPES})"
                )
            text = str(content or "")
            score = self._score(text, context, input_type)
            classification = self._classify(score)
            decision = self._memory_decision(classification)
            record = {
                "record_id": "me_" + uuid.uuid4().hex[:10],
                "timestamp": time.time(),
                "input_type": input_type,
                "content": text[:500],
                "source": str(source),
                "context": str(context),
                "importance_score": score,
                "classification": classification,
                "memory_decision": decision,
                "reason": self._reason(score, classification),
            }
            if classification == "noise":
                self._discard_count += 1
            else:
                self._records.append(record)
                if len(self._records) > self._max_records:
                    self._records = \
                        self._records[-self._max_records:]
            return {
                "mode": "rule_based", "ok": True,
                **record,
            }

    def _score(
        self, content: str, context: str, input_type: str,
    ) -> int:
        """重要性评分 (0-10)"""
        score = 3
        text = content + " " + str(context)
        # 高价值信号 (核心任务词)
        for kw in ("任务", "项目", "方案", "决策", "结论",
                   "问题", "反馈", "需求", "计划", "新知识",
                   "部署", "设计", "完成"):
            if kw in text:
                score += 1
        # 用户观点信号
        if any(kw in text for kw in ("我认为", "建议", "应该",
                                     "希望", "观点")):
            score += 2
        # 弹幕噪声抑制
        if input_type == "danmaku":
            if len(content) <= 3 and content.isdigit():
                score = max(score - 4, 0)
            if content in ("666", "哈哈", "hhh", "233", "路过"):
                score = 0
        return min(score, 10)

    @staticmethod
    def _classify(score: int) -> str:
        """分类 (可解释)"""
        if score <= SCORE_DISCARD_MAX:
            return "noise"
        if score <= 7:
            return "temporary"
        return "high_value"

    @staticmethod
    def _memory_decision(classification: str) -> str:
        """记忆决策"""
        return {
            "high_value": "long_term_candidate",
            "temporary": "short_term",
            "noise": "discard",
        }[classification]

    @staticmethod
    def _reason(score: int, classification: str) -> str:
        """可解释理由"""
        if classification == "noise":
            return f"评分 {score} <= {SCORE_DISCARD_MAX}: 丢弃"
        if classification == "temporary":
            return (
                f"评分 {score} ({SCORE_SHORT_MIN}-7): 短期记忆, "
                "仅当前任务使用"
            )
        return f"评分 {score} >= {SCORE_LONG_MIN}: 长期候选"

    def query(
        self,
        classification: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """查询记录"""
        with self._lock:
            records = list(self._records)
        out = []
        for r in reversed(records):
            if classification and \
                    r["classification"] != classification:
                continue
            out.append(dict(r))
            if 0 < limit <= len(out):
                break
        return out

    def stats(self) -> Dict[str, Any]:
        """统计"""
        with self._lock:
            by_type: Dict[str, int] = {}
            by_class: Dict[str, int] = {}
            for r in self._records:
                by_type[r["input_type"]] = by_type.get(
                    r["input_type"], 0,
                ) + 1
                by_class[r["classification"]] = by_class.get(
                    r["classification"], 0,
                ) + 1
            return {
                "mode": "rule_based",
                "enabled": self._enabled,
                "total_kept": len(self._records),
                "discard_count": self._discard_count,
                "by_type": by_type,
                "by_classification": by_class,
            }

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = len(self._records) + self._discard_count
            self._records.clear()
            self._discard_count = 0
            return n


__all__ = [
    "CLASSIFICATIONS",
    "INPUT_TYPES",
    "MultimodalError",
    "MultimodalExperienceLayer",
    "SCORE_DISCARD_MAX",
    "SCORE_LONG_MIN",
    "SCORE_SHORT_MIN",
]
