"""
YHLZ Embodied AI V5.7 - 经历记录数据模型 (Experience Record)

职责:
    - ExperienceRecord: 经历记录 (id/type/source/trigger/action/result/
      evaluation/lesson/confidence/timestamp)
    - 5 种经验类型: interaction / engineering / decision / failure /
      improvement
    - 价值评估: 高价值经验长期保存, 低价值逐渐衰减

设计原则:
    - 只记录经历与经验 (不记录完整聊天, 不写 Agent Memory)
    - 可解释: lesson 为规则抽取的经验教训
    - 禁止无限记忆 (store 有上限, 低价值衰减/遗忘)
    - 不替代核心 Agent 决策 (经验仅供参考)
"""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ExperienceError(Exception):
    """经历记录操作异常"""


# 经验类型白名单 (可解释)
EXPERIENCE_TYPES: List[str] = [
    "interaction",    # 互动经验 (与用户/环境互动)
    "engineering",    # 工程经验 (开发/构建过程)
    "decision",       # 决策经验 (选择/取舍)
    "failure",        # 失败经验 (失败原因/教训)
    "improvement",    # 改进经验 (优化/提升)
]

# 价值评估 (可解释)
VALUE_LOW = 0.3       # 低价值
VALUE_MEDIUM = 0.6    # 中价值
VALUE_HIGH = 0.8      # 高价值


@dataclass
class ExperienceRecord:
    """经历记录 (Experience Memory)

    Attributes:
        id:          记录 ID
        type:        经验类型 (interaction/engineering/decision/failure/improvement)
        source:      来源 (如 companion_handle / run_goal / reflection)
        trigger:     触发情境 (如 '完成V5.6开发')
        action:      执行动作 (可选)
        result:      结果 (可选)
        evaluation:  评估 (可选)
        lesson:      经验教训 (规则抽取, 可解释)
        confidence:  置信度 (0.0~1.0)
        value:       价值 (0.0~1.0, 高价值长期保存)
        timestamp:   记录时间
    """
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    type: str = "interaction"
    source: str = ""
    trigger: str = ""
    action: str = ""
    result: str = ""
    evaluation: str = ""
    lesson: str = ""
    confidence: float = 0.0
    value: float = VALUE_MEDIUM
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "source": self.source,
            "trigger": self.trigger,
            "action": self.action,
            "result": self.result,
            "evaluation": self.evaluation,
            "lesson": self.lesson,
            "confidence": round(self.confidence, 4),
            "value": round(self.value, 4),
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ExperienceRecord":
        return cls(
            id=d.get("id", uuid.uuid4().hex),
            type=d.get("type", "interaction"),
            source=d.get("source", ""),
            trigger=d.get("trigger", ""),
            action=d.get("action", ""),
            result=d.get("result", ""),
            evaluation=d.get("evaluation", ""),
            lesson=d.get("lesson", ""),
            confidence=float(d.get("confidence", 0.0)),
            value=float(d.get("value", VALUE_MEDIUM)),
            timestamp=float(d.get("timestamp", time.time())),
        )

    @classmethod
    def create(
        cls,
        type: str,
        trigger: str,
        lesson: str,
        source: str = "",
        action: str = "",
        result: str = "",
        evaluation: str = "",
        confidence: float = 0.0,
        value: float = VALUE_MEDIUM,
    ) -> "ExperienceRecord":
        """创建经历记录 (校验类型)"""
        if type not in EXPERIENCE_TYPES:
            raise ExperienceError(
                f"非法经验类型: {type} (可选: {EXPERIENCE_TYPES})"
            )
        if not (0.0 <= confidence <= 1.0):
            raise ExperienceError(
                f"confidence 必须在 [0,1], 当前: {confidence}"
            )
        if not (0.0 <= value <= 1.0):
            raise ExperienceError(f"value 必须在 [0,1], 当前: {value}")
        if not trigger:
            raise ExperienceError("trigger 不能为空")
        return cls(
            type=type, trigger=trigger, lesson=lesson,
            source=source, action=action, result=result,
            evaluation=evaluation, confidence=confidence, value=value,
        )


__all__ = [
    "EXPERIENCE_TYPES",
    "ExperienceError",
    "ExperienceRecord",
    "VALUE_HIGH",
    "VALUE_LOW",
    "VALUE_MEDIUM",
]
