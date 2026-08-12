"""
YHLZ Embodied AI V9.0 - 问题发现引擎 (Question Discovery Engine)

职责:
    - 从观察 (知识缺口/用户需求/长期目标/未解决问题)
      发现值得探索的问题
    - 输出: {question, importance, reason, expected_value}

原则 (主动探索):
    - 探索必须有目标 (回答为什么/解决什么/产生什么价值)
    - 无目标不探索

设计原则:
    - 纯规则发现 (可解释)
    - importance 加权可解释
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

from backend.embodied.companion.research_engine.observation import (
    OBSERVATION_TYPES,
    ObservationLayer,
)

logger = logging.getLogger(__name__)


class QuestionError(Exception):
    """问题发现操作异常"""


# 观察类型 → importance 权重 (可解释)
IMPORTANCE_WEIGHTS: Dict[str, float] = {
    "user_need": 0.9,        # 用户需求 (最高)
    "long_term_goal": 0.8,   # 长期目标
    "unresolved": 0.7,       # 未解决问题
    "knowledge_gap": 0.6,    # 知识缺口
}


class QuestionDiscoveryEngine:
    """问题发现引擎 (观察 → 问题)

    用法:
        engine = QuestionDiscoveryEngine(layer=layer)
        questions = engine.discover()
    """

    def __init__(
        self,
        layer: Optional[ObservationLayer] = None,
        enabled: bool = True,
        max_questions: int = 10,
    ):
        if max_questions <= 0:
            raise QuestionError(
                f"max_questions 必须 > 0, 当前: "
                f"{max_questions}"
            )
        self._lock = threading.RLock()
        self._layer = layer or ObservationLayer()
        self._enabled = bool(enabled)
        self._max = int(max_questions)
        self._questions: list = []

    # ── 发现主入口 ───────────────────────────────────────────────
    def discover(
        self,
        now: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """从观察发现问题

        Returns:
            问题列表 (按 importance 降序)
        """
        with self._lock:
            now = now if now is not None else time.time()
            if not self._enabled:
                return []
            questions: List[Dict[str, Any]] = []
            for obs in self._layer.observations(limit=100):
                q = self._build_question(obs, now)
                if q is not None:
                    questions.append(q)
            # 按 importance 降序
            questions.sort(
                key=lambda q: q["importance"],
                reverse=True,
            )
            kept = questions[:self._max]
            self._questions.extend(kept)
            return [dict(q) for q in kept]

    # ── 问题构建 (可解释) ───────────────────────────────────────
    def _build_question(
        self, obs: Dict[str, Any],
        now: float,
    ) -> Optional[Dict[str, Any]]:
        """单观察 → 问题"""
        content = str(obs.get("content", "")).strip()
        if not content:
            return None
        obs_type = str(obs.get("type", "knowledge_gap"))
        importance = IMPORTANCE_WEIGHTS.get(
            obs_type, 0.6,
        )
        # 期望价值 (可解释)
        expected_value = self._expected_value(obs_type)
        reason = (
            f"来自{obs_type}: '{content[:30]}' 值得探索, "
            f"可{expected_value}"
        )
        return {
            "question_id": "qs_" + uuid.uuid4().hex[:8],
            "question": f"如何解决: {content}",
            "importance": round(importance, 4),
            "reason": reason,
            "expected_value": expected_value,
            "observation_id": obs.get(
                "observation_id", "",
            ),
            "created_at": now,
        }

    @staticmethod
    def _expected_value(obs_type: str) -> str:
        """期望价值"""
        if obs_type == "user_need":
            return "直接提升用户体验"
        if obs_type == "long_term_goal":
            return "推进长期目标"
        if obs_type == "unresolved":
            return "解决遗留问题"
        return "填补知识缺口"

    # ── 查询 ─────────────────────────────────────────────────────
    def stats(self) -> Dict[str, Any]:
        """问题发现统计"""
        with self._lock:
            return {
                "mode": "rule_based",
                "enabled": self._enabled,
                "question_count": len(self._questions),
                "observation_count":
                    self._layer.stats()["observation_count"],
                "weights": dict(IMPORTANCE_WEIGHTS),
            }

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = len(self._questions)
            self._questions.clear()
            return n


__all__ = [
    "IMPORTANCE_WEIGHTS",
    "QuestionDiscoveryEngine",
    "QuestionError",
]
