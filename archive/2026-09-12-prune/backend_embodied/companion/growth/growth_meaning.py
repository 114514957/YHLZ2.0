"""
YHLZ Embodied AI V6.0 - 成长意义 (Growth Meaning)

职责:
    - 让成长具有意义 (不是"经验+100")
    - 解释: 发生了什么 → 意味着什么 → 影响未来什么
    - 输出:
      {event, meaning, impact, future_effect}

事件类型 (可解释):
    - experience_added:          新经历
    - experience_confirmed:      经验确认
    - reflection_created:        反思报告
    - creative_proposal:         创造方案
    - creative_completed:        创造完成
    - relationship_change:       关系变化
    - verification_rejected:     经验被拒绝 (认知免疫)
    - identity_change:           身份变化

设计原则:
    - 纯规则解释 (禁止黑盒)
    - 每条解释含意义/影响/未来效果
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class MeaningError(Exception):
    """成长意义操作异常"""


# 事件类型白名单 (可解释)
GROWTH_EVENT_TYPES: List[str] = [
    "experience_added",
    "experience_confirmed",
    "task_completed",
    "reflection_created",
    "creative_proposal",
    "creative_completed",
    "relationship_change",
    "verification_rejected",
    "identity_change",
    "multimodal_perception",
]

# 意义模板 (可解释)
MEANING_TEMPLATES: Dict[str, Dict[str, str]] = {
    "experience_added": {
        "meaning": "获得了一次新经历, 为经验库增加样本",
        "impact": "提高该情境的经验覆盖度",
        "future_effect": "未来遇到同类情境时可参考此经历",
    },
    "experience_confirmed": {
        "meaning": "经历通过多次验证, 成为可靠经验",
        "impact": "可靠经验可参与反思与创造",
        "future_effect": "认知免疫: 可靠经验进入长期成长参考",
    },
    "task_completed": {
        "meaning": "完成一次任务委派, 产生互动经历",
        "impact": "增加互动经验与关系积累",
        "future_effect": "持续积累是长期成长的基础",
    },
    "multimodal_perception": {
        "meaning": "接收并验证一次多模态感知事件",
        "impact": "扩展对环境的理解输入",
        "future_effect": "经反思后可能形成记忆候选",
    },
    "reflection_created": {
        "meaning": "完成一次反思, 从经历中提取规律",
        "impact": "发现模式/失败原因/改进方向",
        "future_effect": "驱动机会发现与创造方案",
    },
    "creative_proposal": {
        "meaning": "基于可靠经验提出创造方案",
        "impact": "将机会转化为可执行的方案",
        "future_effect": "经审批后可执行并形成新经验",
    },
    "creative_completed": {
        "meaning": "创造方案执行完成并形成新经验",
        "impact": "创造价值闭环完成",
        "future_effect": "新经验进入验证, 扩充可靠经验库",
    },
    "relationship_change": {
        "meaning": "与用户的关系状态发生变化",
        "impact": "影响互动方式与信任水平",
        "future_effect": "长期陪伴的基础逐步深化",
    },
    "verification_rejected": {
        "meaning": "错误经验被拒绝, 认知免疫生效",
        "impact": "防止错误经验进入长期参考",
        "future_effect": "减少幻觉与错误循环强化",
    },
    "identity_change": {
        "meaning": "身份状态发生变化 (需审批)",
        "impact": "影响伙伴的长期演化轨迹",
        "future_effect": "身份连续性由快照历史保证",
    },
}


class GrowthMeaning:
    """成长意义解释器

    用法:
        gm = GrowthMeaning()
        result = gm.interpret("experience_confirmed",
                              detail="exp_1 确认")
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._interpretations: List[Dict[str, Any]] = []

    # ── 解释主入口 ───────────────────────────────────────────────
    def interpret(
        self, event_type: str,
        detail: str = "",
        context: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        """解释成长事件意义 (规则驱动)

        Args:
            event_type: 事件类型 (GROWTH_EVENT_TYPES)
            detail: 事件细节
            context: 上下文 (可空)

        Returns:
            {
                'meaning_id', 'event', 'meaning', 'impact',
                'future_effect', 'detail', 'mode',
            }
        """
        with self._lock:
            if event_type not in GROWTH_EVENT_TYPES:
                raise MeaningError(
                    f"非法事件类型: {event_type} "
                    f"(可选: {GROWTH_EVENT_TYPES})"
                )
            template = MEANING_TEMPLATES[event_type]
            ctx = dict(context or {})
            meaning = self._refine(
                template["meaning"], event_type, ctx,
            )
            impact = self._refine(
                template["impact"], event_type, ctx,
            )
            future = self._refine(
                template["future_effect"], event_type, ctx,
            )
            result = {
                "meaning_id": "meaning_" +
                __import__("uuid").uuid4().hex[:8],
                "event": event_type,
                "meaning": meaning,
                "impact": impact,
                "future_effect": future,
                "detail": detail,
                "mode": "rule_based",
            }
            self._interpretations.append(result)
            return dict(result)

    # ── 细化 (可解释) ────────────────────────────────────────────
    @staticmethod
    def _refine(text: str, event_type: str,
                ctx: Dict[str, Any]) -> str:
        """按上下文细化意义文本"""
        extra = ctx.get("extra")
        if not extra:
            return text
        return f"{text} ({extra})"

    # ── 查询 ─────────────────────────────────────────────────────
    def by_event(self, event_type: str) -> List[Dict[str, Any]]:
        """按事件类型查询"""
        if event_type not in GROWTH_EVENT_TYPES:
            raise MeaningError(
                f"非法事件类型: {event_type} "
                f"(可选: {GROWTH_EVENT_TYPES})"
            )
        with self._lock:
            return [
                dict(r) for r in self._interpretations
                if r["event"] == event_type
            ]

    def stats(self) -> Dict[str, Any]:
        """意义统计"""
        with self._lock:
            interpretations = list(self._interpretations)
        by_event: Dict[str, int] = {}
        for r in interpretations:
            by_event[r["event"]] = by_event.get(r["event"], 0) + 1
        return {
            "mode": "rule_based",
            "interpretation_count": len(interpretations),
            "by_event": by_event,
        }

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = len(self._interpretations)
            self._interpretations.clear()
            return n


__all__ = [
    "GROWTH_EVENT_TYPES",
    "MEANING_TEMPLATES",
    "GrowthMeaning",
    "MeaningError",
]
