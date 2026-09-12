"""
YHLZ Embodied AI V6.5 - 认知矛盾检测器 (Cognitive Contradiction Detector)

职责:
    - 检测内部冲突: 新经验 vs 旧知识 vs Identity
    - 输出: {conflict, type, severity, reason}

矛盾类型 (可解释):
    - identity_conflict:   与核心身份冲突
    - knowledge_conflict:  与已有知识冲突
    - value_conflict:      与价值观冲突

设计原则:
    - 纯规则检测 (无黑盒)
    - severity 0~1 (严重度)
    - 可解释 (reason)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ContradictionError(Exception):
    """认知矛盾操作异常"""


# 矛盾类型 (可解释)
CONTRADICTION_TYPES: List[str] = [
    "identity_conflict",    # 身份冲突
    "knowledge_conflict",   # 知识冲突
    "value_conflict",       # 价值观冲突
]

# 身份关键字段 (可解释)
IDENTITY_FIELDS: List[str] = [
    "mission", "core_value", "base_personality",
]

# 价值观关键词 (可解释)
VALUE_KEYWORDS: List[str] = [
    "可靠", "诚信", "安全", "尊重", "负责",
]


class CognitiveContradictionDetector:
    """认知矛盾检测器

    用法:
        detector = CognitiveContradictionDetector()
        result = detector.detect(new_experience,
                                 identity_state,
                                 known_experiences)
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._results: List[Dict[str, Any]] = []

    # ── 检测主入口 ───────────────────────────────────────────────
    def detect(
        self,
        new_experience: Dict[str, Any],
        identity_state: Optional[Dict[str, Any]] = None,
        known_experiences: Optional[List[Dict[str, Any]]] = None,
        now: Optional[float] = None,
    ) -> Dict[str, Any]:
        """检测新经验与旧知识/身份的矛盾

        Args:
            new_experience: 新经验 (trigger/lesson/result)
            identity_state: 身份状态 (mission/core_value/...)
            known_experiences: 已有经历

        Returns:
            {
                'conflict_id', 'conflict': bool, 'type',
                'severity', 'reason', 'mode',
            }
        """
        with self._lock:
            now = now if now is not None else time.time()
            identity = identity_state or {}
            known = known_experiences or []
            text = " ".join([
                str(new_experience.get("trigger", "")),
                str(new_experience.get("lesson", "")),
                str(new_experience.get("result", "")),
            ])
            # 1. Identity 冲突 (文本涉及身份字段名或修改信号)
            field_names = {
                "mission": "使命",
                "core_value": "核心价值观",
                "base_personality": "基础人格",
            }
            for field in IDENTITY_FIELDS:
                if field_names.get(field, field) in text or \
                        f"修改{field}" in text:
                    return self._finish(
                        True, "identity_conflict", 0.9,
                        f"与核心身份 '{field}' 冲突", now,
                    )
            # 2. 知识冲突 (同类触发器相反结果)
            for exp in known:
                if exp.get("trigger") == new_experience.get(
                    "trigger",
                ) and str(exp.get("result", "")).find("成功") >= 0 \
                        and str(new_experience.get(
                            "result", "")).find("失败") >= 0:
                    return self._finish(
                        True, "knowledge_conflict", 0.7,
                        f"与已有经历 '{exp.get('trigger')}' "
                        f"结果相反", now,
                    )
            # 3. 价值观冲突
            for kw in VALUE_KEYWORDS:
                if f"不{kw}" in text or f"违背{kw}" in text:
                    return self._finish(
                        True, "value_conflict", 0.8,
                        f"涉及违背价值观 '{kw}'", now,
                    )
            return self._finish(
                False, "", 0.0, "无冲突", now,
            )

    def _finish(self, conflict: bool, ctype: str,
                severity: float, reason: str,
                now: float) -> Dict[str, Any]:
        """完成检测 (记录历史)"""
        result = {
            "conflict_id": "cnd_" + uuid.uuid4().hex[:8],
            "conflict": conflict,
            "type": ctype if conflict else "",
            "severity": severity,
            "reason": reason,
            "mode": "rule_based",
            "checked_at": now,
        }
        self._results.append(result)
        return dict(result)

    # ── 查询 ─────────────────────────────────────────────────────
    def stats(self) -> Dict[str, Any]:
        """检测统计"""
        with self._lock:
            results = list(self._results)
        conflicts = sum(1 for r in results if r["conflict"])
        by_type: Dict[str, int] = {}
        for r in results:
            if r["conflict"]:
                by_type[r["type"]] = by_type.get(r["type"], 0) + 1
        return {
            "mode": "rule_based",
            "check_count": len(results),
            "conflict_count": conflicts,
            "by_type": by_type,
        }

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = len(self._results)
            self._results.clear()
            return n


__all__ = [
    "CONTRADICTION_TYPES",
    "CognitiveContradictionDetector",
    "ContradictionError",
]
