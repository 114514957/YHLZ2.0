"""
YHLZ Embodied AI V5.8 - 经验验证器 (Experience Verifier)

职责:
    - 经验状态机: UNKNOWN → PENDING → PROBABLE → CONFIRMED / REJECTED
    - 状态转移规则 (可解释):
      - 新经验 → UNKNOWN
      - 有证据 → PENDING
      - 重复出现 + 一致 → PROBABLE
      - 多次验证通过 → CONFIRMED (进入长期成长参考)
      - 反例/矛盾 → REJECTED

设计原则:
    - 只有 CONFIRMED 经验才能进入长期成长参考
    - 纯规则验证 (禁止黑盒)
    - 可回溯: 状态转移记录
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class VerifierError(Exception):
    """经验验证操作异常"""


# 经验状态 (可解释)
VERIFICATION_STATUSES: List[str] = [
    "UNKNOWN",    # 未验证 (新经验)
    "PENDING",    # 待验证 (有证据)
    "PROBABLE",   # 可能 (重复出现 + 一致)
    "CONFIRMED",  # 已确认 (可进入长期成长参考)
    "REJECTED",   # 已拒绝 (反例/矛盾)
]

# 状态转移 (可解释)
VERIFICATION_TRANSITIONS: Dict[str, List[str]] = {
    "UNKNOWN": ["PENDING", "REJECTED"],
    "PENDING": ["PROBABLE", "REJECTED"],
    "PROBABLE": ["CONFIRMED", "REJECTED"],
    "CONFIRMED": ["REJECTED"],     # 新反例 → 降级拒绝
    "REJECTED": ["PENDING"],       # 新证据 → 重新待验证
}


class VerificationState:
    """经验验证状态

    Attributes:
        experience_id:  关联经历 ID
        status:         当前状态
        verifications:  验证次数
        confirmations:  确认次数
        rejections:     拒绝次数
        last_change:    最后变更时间
        history:        状态转移历史
    """

    def __init__(self, experience_id: str):
        self.experience_id = experience_id
        self.status = "UNKNOWN"
        self.verifications = 0
        self.confirmations = 0
        self.rejections = 0
        self.last_change = time.time()
        self.history: List[Dict[str, Any]] = []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "experience_id": self.experience_id,
            "status": self.status,
            "verifications": self.verifications,
            "confirmations": self.confirmations,
            "rejections": self.rejections,
            "last_change": self.last_change,
            "history": list(self.history),
        }


class ExperienceVerifier:
    """经验验证器 (状态机)

    用法:
        verifier = ExperienceVerifier()
        state = verifier.verify("exp_1", evidence_count=2,
                                contradictions=0)
        confirmed = verifier.confirmed_ids()
    """

    def __init__(self, confirm_threshold: int = 2,
                 reject_threshold: int = 2):
        if confirm_threshold <= 0:
            raise VerifierError(
                f"confirm_threshold 必须 > 0, 当前: {confirm_threshold}"
            )
        if reject_threshold <= 0:
            raise VerifierError(
                f"reject_threshold 必须 > 0, 当前: {reject_threshold}"
            )
        self._lock = threading.RLock()
        self._states: Dict[str, VerificationState] = {}
        self._confirm_threshold = int(confirm_threshold)
        self._reject_threshold = int(reject_threshold)

    # ── 验证 ──────────────────────────────────────────────────────
    def verify(
        self,
        experience_id: str,
        evidence_count: int = 1,
        contradictions: int = 0,
        source_reliable: bool = True,
    ) -> Dict[str, Any]:
        """执行一次验证 (规则驱动, 可解释)

        Args:
            experience_id: 经历 ID
            evidence_count: 本次验证的证据数
            contradictions: 本次发现的反例数
            source_reliable: 信息来源是否可靠

        Returns:
            更新后的验证状态
        """
        with self._lock:
            state = self._states.setdefault(
                experience_id, VerificationState(experience_id),
            )
            state.verifications += 1
            before = state.status
            if contradictions > 0 or not source_reliable:
                state.rejections += 1
                if state.rejections >= self._reject_threshold:
                    self._transition(state, "REJECTED",
                                     "反例/不可靠来源")
                else:
                    self._transition(state, "PENDING",
                                     "发现反例, 重新验证")
            elif evidence_count > 0:
                state.confirmations += 1
                if state.status in ("UNKNOWN", "REJECTED"):
                    # 新证据: 从未知/拒绝回到待验证
                    self._transition(state, "PENDING", "新证据出现")
                elif state.status == "PENDING":
                    self._transition(state, "PROBABLE", "重复出现")
                elif state.status in ("PROBABLE", "CONFIRMED"):
                    if state.confirmations >= self._confirm_threshold:
                        self._transition(state, "CONFIRMED",
                                         "多次验证通过")
                    else:
                        self._transition(state, "PROBABLE", "持续一致")
            return state.to_dict()

    def _transition(self, state: VerificationState, new_status: str,
                    reason: str) -> None:
        """状态转移 (记录历史)"""
        before = state.status
        allowed = VERIFICATION_TRANSITIONS.get(state.status, [])
        if new_status not in allowed:
            new_status = "PENDING"  # 兜底: 回到待验证
        state.status = new_status
        state.last_change = time.time()
        state.history.append({
            "from": before,
            "to": new_status,
            "reason": reason,
            "timestamp": state.last_change,
        })

    # ── 查询 ──────────────────────────────────────────────────────
    def get(self, experience_id: str) -> Optional[Dict[str, Any]]:
        """查询验证状态"""
        with self._lock:
            state = self._states.get(experience_id)
            return state.to_dict() if state else None

    def by_status(self, status: str) -> List[Dict[str, Any]]:
        """按状态查询"""
        if status not in VERIFICATION_STATUSES:
            raise VerifierError(
                f"非法状态: {status} (可选: {VERIFICATION_STATUSES})"
            )
        with self._lock:
            return [
                s.to_dict() for s in self._states.values()
                if s.status == status
            ]

    def confirmed_ids(self) -> List[str]:
        """已确认经历 ID (可进入长期成长参考)"""
        with self._lock:
            return [
                s.experience_id for s in self._states.values()
                if s.status == "CONFIRMED"
            ]

    def rejected_ids(self) -> List[str]:
        """已拒绝经历 ID"""
        with self._lock:
            return [
                s.experience_id for s in self._states.values()
                if s.status == "REJECTED"
            ]

    def stats(self) -> Dict[str, Any]:
        """验证统计"""
        with self._lock:
            states = list(self._states.values())
        by_status: Dict[str, int] = {}
        for s in states:
            by_status[s.status] = by_status.get(s.status, 0) + 1
        return {
            "mode": "rule_based",
            "total": len(states),
            "by_status": by_status,
            "confirmed": by_status.get("CONFIRMED", 0),
            "rejected": by_status.get("REJECTED", 0),
            "pending": by_status.get("PENDING", 0),
            "confirm_threshold": self._confirm_threshold,
            "reject_threshold": self._reject_threshold,
        }

    # ── 生命周期 ──────────────────────────────────────────────────
    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = len(self._states)
            self._states.clear()
            return n


__all__ = [
    "ExperienceVerifier",
    "VERIFICATION_STATUSES",
    "VERIFICATION_TRANSITIONS",
    "VerificationState",
    "VerifierError",
]
