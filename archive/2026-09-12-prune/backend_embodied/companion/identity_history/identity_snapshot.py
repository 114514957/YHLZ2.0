"""
YHLZ Embodied AI V6.0 - 身份快照 (Identity Snapshot)

职责:
    - 保存 AI 伙伴成长轨迹:
      Version → Identity State → Change Reason → Approval
    - 人格变化必须"提出", 不能自动修改:
      propose_change (PROPOSED) → approve_change (APPROVED, 生效)
                              → reject_change (REJECTED)

设计原则:
    - 核心人格/使命不可自动修改 (变化必须审批)
    - 每次变化记录完整轨迹 (可回溯)
    - 纯规则, 无黑盒
    - 线程安全 (RLock)
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class IdentitySnapshotError(Exception):
    """身份快照操作异常"""


# 审批状态白名单 (可解释)
APPROVAL_STATUSES: List[str] = [
    "PROPOSED",   # 已提出 (待审批)
    "APPROVED",   # 已批准 (生效)
    "REJECTED",   # 已拒绝
]

# 不可变字段 (核心身份, 禁止变更) (可解释)
IMMUTABLE_FIELDS: List[str] = [
    "mission",        # 使命
    "core_value",     # 核心价值观
    "base_personality",  # 基础人格
]


class IdentitySnapshot:
    """身份快照器 (成长轨迹 + 变化审批)

    用法:
        snap = IdentitySnapshot()
        snap.capture(identity_state, reason="首次记录")
        proposal = snap.propose_change(new_state, reason)
        snap.approve_change(proposal_id) / reject_change(proposal_id)
    """

    def __init__(self, version: str = "9.5.0",
                 max_history: int = 200):
        if not version:
            raise IdentitySnapshotError("版本号不能为空")
        self._lock = threading.RLock()
        self._version = str(version)
        self._history: List[Dict[str, Any]] = []
        self._max = int(max_history)

    # ── 记录快照 ─────────────────────────────────────────────────
    def capture(
        self, identity_state: Dict[str, Any],
        reason: str = "", approver: str = "system",
    ) -> Dict[str, Any]:
        """记录一次身份快照 (当前状态, 无需审批)"""
        with self._lock:
            if not identity_state:
                raise IdentitySnapshotError("身份状态不能为空")
            fingerprint = self._fingerprint(identity_state)
            snap = {
                "snapshot_id": "idsnap_" + uuid.uuid4().hex[:8],
                "version": self._version,
                "identity_state": dict(identity_state),
                "fingerprint": fingerprint,
                "change_reason": reason or "状态记录",
                "approval": {
                    "status": "APPROVED",
                    "approver": approver,
                    "reason": "基准/状态记录 (无变更)",
                },
                "created_at": time.time(),
            }
            self._history.append(snap)
            if len(self._history) > self._max:
                self._history = self._history[-self._max:]
            return dict(snap)

    # ── 变化提出与审批 (人格变化不能自动修改) ────────────────────
    def propose_change(
        self, current_state: Dict[str, Any],
        proposed_state: Dict[str, Any],
        reason: str,
    ) -> Dict[str, Any]:
        """提出身份变化 (PROPOSED, 待审批)

        规则: 不可变字段 (使命/核心价值/基础人格) 禁止变更
        """
        with self._lock:
            if not reason.strip():
                raise IdentitySnapshotError("变化原因不能为空")
            immutable_changed = []
            for field in IMMUTABLE_FIELDS:
                before = current_state.get(field)
                after = proposed_state.get(field)
                if before != after:
                    immutable_changed.append(field)
            if immutable_changed:
                raise IdentitySnapshotError(
                    f"不可变字段禁止变更: {immutable_changed} "
                    f"(使命/核心价值/基础人格不可修改)"
                )
            proposal = {
                "snapshot_id": "idsnap_" + uuid.uuid4().hex[:8],
                "version": self._version,
                "identity_state": dict(proposed_state),
                "fingerprint": self._fingerprint(proposed_state),
                "change_reason": reason,
                "change_diff": self._diff_summary(
                    current_state, proposed_state,
                ),
                "approval": {
                    "status": "PROPOSED",
                    "approver": "",
                    "reason": "等待审批",
                },
                "created_at": time.time(),
            }
            self._history.append(proposal)
            if len(self._history) > self._max:
                self._history = self._history[-self._max:]
            return dict(proposal)

    def approve_change(self, snapshot_id: str,
                       approver: str = "user") -> Dict[str, Any]:
        """批准变化 (PROPOSED → APPROVED, 生效)"""
        with self._lock:
            snap = self._get(snapshot_id)
            if snap is None:
                raise IdentitySnapshotError(
                    f"快照不存在: {snapshot_id}"
                )
            if snap["approval"]["status"] != "PROPOSED":
                raise IdentitySnapshotError(
                    f"只有 PROPOSED 可批准, 当前: "
                    f"{snap['approval']['status']}"
                )
            snap["approval"]["status"] = "APPROVED"
            snap["approval"]["approver"] = approver
            snap["approval"]["reason"] = f"经 {approver} 批准"
            snap["approved_at"] = time.time()
            return dict(snap)

    def reject_change(self, snapshot_id: str,
                      reason: str = "") -> Dict[str, Any]:
        """拒绝变化 (PROPOSED → REJECTED)"""
        with self._lock:
            snap = self._get(snapshot_id)
            if snap is None:
                raise IdentitySnapshotError(
                    f"快照不存在: {snapshot_id}"
                )
            if snap["approval"]["status"] != "PROPOSED":
                raise IdentitySnapshotError(
                    f"只有 PROPOSED 可拒绝, 当前: "
                    f"{snap['approval']['status']}"
                )
            snap["approval"]["status"] = "REJECTED"
            snap["approval"]["reason"] = reason or "人工拒绝"
            snap["rejected_at"] = time.time()
            return dict(snap)

    # ── 查询 ─────────────────────────────────────────────────────
    def history(self, limit: int = 50) -> List[Dict[str, Any]]:
        """身份快照历史 (最新在前)"""
        with self._lock:
            recent = list(reversed(self._history))
            if limit > 0:
                recent = recent[:limit]
            return [dict(h) for h in recent]

    def latest(self) -> Optional[Dict[str, Any]]:
        """最新快照"""
        with self._lock:
            if not self._history:
                return None
            return dict(self._history[-1])

    def get(self, snapshot_id: str) -> Optional[Dict[str, Any]]:
        """查询快照"""
        with self._lock:
            return dict(self._get(snapshot_id)) \
                if self._get(snapshot_id) else None

    def _get(self, snapshot_id: str) -> Optional[Dict[str, Any]]:
        for h in self._history:
            if h["snapshot_id"] == snapshot_id:
                return h
        return None

    def by_approval_status(self, status: str) -> List[Dict[str, Any]]:
        """按审批状态查询"""
        if status not in APPROVAL_STATUSES:
            raise IdentitySnapshotError(
                f"非法审批状态: {status} "
                f"(可选: {APPROVAL_STATUSES})"
            )
        with self._lock:
            return [
                dict(h) for h in self._history
                if h["approval"]["status"] == status
            ]

    def stats(self) -> Dict[str, Any]:
        """身份统计"""
        with self._lock:
            history = list(self._history)
        by_approval: Dict[str, int] = {}
        for h in history:
            by_approval[h["approval"]["status"]] = by_approval.get(
                h["approval"]["status"], 0,
            ) + 1
        return {
            "mode": "rule_based",
            "snapshot_count": len(history),
            "by_approval_status": by_approval,
            "proposed_count": by_approval.get("PROPOSED", 0),
            "approved_count": by_approval.get("APPROVED", 0),
            "rejected_count": by_approval.get("REJECTED", 0),
        }

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = len(self._history)
            self._history.clear()
            return n

    # ── 内部 ─────────────────────────────────────────────────────
    @staticmethod
    def _fingerprint(state: Dict[str, Any]) -> str:
        """身份指纹 (确定性)"""
        canonical = json.dumps(
            state, ensure_ascii=False, sort_keys=True,
        )
        return hashlib.sha256(
            canonical.encode("utf-8"),
        ).hexdigest()

    @staticmethod
    def _diff_summary(before: Dict[str, Any],
                      after: Dict[str, Any]) -> List[Dict[str, Any]]:
        """变化摘要 (字段级)"""
        diffs = []
        for key in set(list(before.keys()) + list(after.keys())):
            if before.get(key) != after.get(key):
                diffs.append({
                    "field": key,
                    "before": before.get(key),
                    "after": after.get(key),
                })
        return diffs


__all__ = [
    "APPROVAL_STATUSES",
    "IMMUTABLE_FIELDS",
    "IdentitySnapshot",
    "IdentitySnapshotError",
]
