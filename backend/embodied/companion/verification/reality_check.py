"""
YHLZ Embodied AI V5.8 - 现实检查 (Reality Check)

职责:
    - 所有成长建议必须回答 5 问:
      1. 来源是什么?
      2. 证据是什么?
      3. 是否重复?
      4. 有没有反例?
      5. 是否值得影响未来行为?
    - 输出: 通过/不通过 + 每问检查结果 (可解释)

设计原则:
    - 纯规则检查 (禁止黑盒)
    - 防止幻觉形成事实 / 错误循环强化
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class RealityError(Exception):
    """现实检查操作异常"""


class RealityCheck:
    """现实检查器 (5 问验证)

    用法:
        checker = RealityCheck()
        result = checker.verify(source="run_goal", evidence_count=3,
                                occurrences=5, contradictions=0,
                                value=0.8)
    """

    def __init__(
        self,
        min_evidence: int = 1,
        min_occurrences: int = 3,
    ):
        if min_evidence <= 0:
            raise RealityError(
                f"min_evidence 必须 > 0, 当前: {min_evidence}"
            )
        if min_occurrences <= 0:
            raise RealityError(
                f"min_occurrences 必须 > 0, 当前: {min_occurrences}"
            )
        self._lock = threading.RLock()
        self._min_evidence = int(min_evidence)
        self._min_occurrences = int(min_occurrences)

    # ── 5 问检查 ──────────────────────────────────────────────────
    def verify(
        self,
        source: str = "",
        evidence_count: int = 0,
        occurrences: int = 1,
        contradictions: int = 0,
        value: float = 0.5,
    ) -> Dict[str, Any]:
        """执行现实检查 (5 问, 可解释)

        Returns:
            {
                'passed': bool,
                'checks': [
                    {'question': '来源是什么?', 'answer': ..., 'ok': bool},
                    ...
                ],
                'recommendation': '影响行为' | '暂不采用' | ...,
                'reason': str,
            }
        """
        with self._lock:
            checks: List[Dict[str, Any]] = [
                {
                    "question": "1. 来源是什么?",
                    "answer": source if source else "无明确来源",
                    "ok": bool(source),
                },
                {
                    "question": "2. 证据是什么?",
                    "answer": f"{evidence_count} 条证据",
                    "ok": evidence_count >= self._min_evidence,
                },
                {
                    "question": "3. 是否重复?",
                    "answer": f"出现 {occurrences} 次",
                    "ok": occurrences >= self._min_occurrences,
                },
                {
                    "question": "4. 有没有反例?",
                    "answer": f"{contradictions} 个反例",
                    "ok": contradictions == 0,
                },
                {
                    "question": "5. 是否值得影响未来行为?",
                    "answer": f"价值 {value}",
                    "ok": value >= 0.5,
                },
            ]
            ok_count = sum(1 for c in checks if c["ok"])
            passed = ok_count == len(checks)
            if passed:
                recommendation = "影响未来行为 (全部通过)"
            elif ok_count >= 3:
                recommendation = "暂不采用 (待更多证据)"
            else:
                recommendation = "拒绝采用 (证据不足或存在反例)"
            return {
                "passed": passed,
                "checks": checks,
                "ok_count": ok_count,
                "recommendation": recommendation,
                "reason": (
                    f"5 问通过 {ok_count}/5: "
                    + ("全部通过" if passed else recommendation)
                ),
            }


__all__ = [
    "RealityCheck",
    "RealityError",
]
