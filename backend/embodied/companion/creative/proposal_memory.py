"""
YHLZ Embodied AI V5.9 - 方案记忆 (Proposal Memory)

职责:
    - 解决 Proposal 生命周期管理
    - 保存: Proposal → Decision → Execution → Result → Experience
    - 状态机 (可解释):
        PENDING  → APPROVED / REJECTED
        APPROVED → EXECUTED / REJECTED
        EXECUTED → COMPLETED / FAILED
        COMPLETED / FAILED 为终态 (形成新经验)
    - JSONL 持久化 (重启不丢失)

设计原则:
    - Proposal 只提出, 不执行 (执行必须经审批)
    - 执行结果形成新经验 (experience_id 关联, 闭环)
    - 生命周期全程可回溯
    - 线程安全 (RLock)
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class MemoryError(Exception):
    """方案记忆操作异常"""


# 方案状态白名单 (可解释)
PROPOSAL_STATUSES: List[str] = [
    "PENDING",    # 待审批
    "APPROVED",   # 已批准 (可执行)
    "REJECTED",   # 已拒绝
    "EXECUTED",   # 已执行
    "COMPLETED",  # 完成 (成功, 终态)
    "FAILED",     # 失败 (终态)
]

# 状态转移 (可解释)
PROPOSAL_TRANSITIONS: Dict[str, List[str]] = {
    "PENDING": ["APPROVED", "REJECTED"],
    "APPROVED": ["EXECUTED", "REJECTED"],
    "EXECUTED": ["COMPLETED", "FAILED"],
    "REJECTED": [],
    "COMPLETED": [],
    "FAILED": [],
}


class ProposalMemory:
    """方案记忆 (生命周期管理 + 持久化)

    用法:
        memory = ProposalMemory()
        memory.save(proposal_dict)
        memory.approve(pid) / reject / execute / record_result
        memory.save_to_file(path) / load_from_file(path)
    """

    def __init__(self, max_records: int = 100,
                 persist_path: str = ""):
        if max_records <= 0:
            raise MemoryError(
                f"max_records 必须 > 0, 当前: {max_records}"
            )
        self._lock = threading.RLock()
        self._records: Dict[str, Dict[str, Any]] = {}
        self._max = int(max_records)
        self._persist_path = str(persist_path)

    # ── 保存 (Proposal 进入记忆) ─────────────────────────────────
    def save(self, proposal: Dict[str, Any]) -> Dict[str, Any]:
        """保存方案 (状态 PENDING)"""
        with self._lock:
            pid = proposal.get("proposal_id", "")
            if not pid:
                raise MemoryError("方案缺 proposal_id")
            if len(self._records) >= self._max and pid not in self._records:
                raise MemoryError("方案记忆已达上限")
            entry = dict(proposal)
            entry.setdefault("status", "PENDING")
            entry.setdefault("lifecycle", [])
            if not entry.get("lifecycle"):
                entry["lifecycle"] = [{
                    "event": "saved",
                    "to": entry["status"],
                    "reason": "方案进入记忆",
                    "timestamp": time.time(),
                }]
            self._records[pid] = entry
            return dict(entry)

    def update_proposal(self, proposal_id: str,
                        fields: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """更新方案字段 (如模拟结果)"""
        with self._lock:
            rec = self._records.get(proposal_id)
            if rec is None:
                return None
            rec.update(fields)
            return dict(rec)

    # ── 生命周期 (Decision → Execution → Result) ─────────────────
    def approve(self, proposal_id: str,
                approver: str = "user") -> Dict[str, Any]:
        """批准 (PENDING → APPROVED)"""
        return self._transition(proposal_id, "APPROVED",
                                f"经 {approver} 批准")

    def reject(self, proposal_id: str,
               reason: str = "") -> Dict[str, Any]:
        """拒绝 (PENDING/APPROVED → REJECTED)"""
        return self._transition(proposal_id, "REJECTED",
                                reason or "人工/系统拒绝")

    def execute(self, proposal_id: str) -> Dict[str, Any]:
        """执行 (APPROVED → EXECUTED, 仅批准后可执行)"""
        return self._transition(proposal_id, "EXECUTED",
                                "方案执行中")

    def record_result(
        self, proposal_id: str, success: bool,
        result: str = "", experience_id: str = "",
    ) -> Dict[str, Any]:
        """记录结果 (EXECUTED → COMPLETED/FAILED, 形成新经验)"""
        with self._lock:
            rec = self._records.get(proposal_id)
            if rec is None:
                raise MemoryError(f"方案不存在: {proposal_id}")
            if rec["status"] != "EXECUTED":
                raise MemoryError(
                    f"只有 EXECUTED 方案可记录结果, "
                    f"当前: {rec['status']}"
                )
            new_status = "COMPLETED" if success else "FAILED"
            self._transition_locked(rec, new_status,
                                    f"结果: {result or ('成功' if success else '失败')}")
            rec["result"] = result
            rec["success"] = success
            if experience_id:
                rec["experience_id"] = experience_id
            rec["result_recorded_at"] = time.time()
            return dict(rec)

    def _transition(self, proposal_id: str, new_status: str,
                    reason: str) -> Dict[str, Any]:
        """通用状态转移"""
        with self._lock:
            rec = self._records.get(proposal_id)
            if rec is None:
                raise MemoryError(f"方案不存在: {proposal_id}")
            return self._transition_locked(rec, new_status, reason)

    def _transition_locked(self, rec: Dict[str, Any],
                           new_status: str, reason: str) -> Dict[str, Any]:
        """状态转移 (记录 lifecycle)"""
        allowed = PROPOSAL_TRANSITIONS.get(rec["status"], [])
        if new_status not in allowed:
            raise MemoryError(
                f"方案状态 {rec['status']} 不能转移到 {new_status} "
                f"(可选: {allowed})"
            )
        rec["status"] = new_status
        now = time.time()
        rec["lifecycle"] = rec.setdefault("lifecycle", []) + [{
            "event": new_status.lower(),
            "to": new_status,
            "reason": reason,
            "timestamp": now,
        }]
        if new_status == "APPROVED":
            rec["approved_at"] = now
            rec["approver"] = (
                reason.replace("经 ", "").replace(" 批准", "")
                if reason.startswith("经 ") else ""
            )
        elif new_status == "EXECUTED":
            rec["executed_at"] = now
        elif new_status == "REJECTED":
            rec["rejected_at"] = now
            rec["reason"] = reason
        return dict(rec)

    # ── 查询 ──────────────────────────────────────────────────────
    def get(self, proposal_id: str) -> Optional[Dict[str, Any]]:
        """查询方案"""
        with self._lock:
            rec = self._records.get(proposal_id)
            return dict(rec) if rec else None

    def by_status(self, status: str) -> List[Dict[str, Any]]:
        """按状态查询"""
        if status not in PROPOSAL_STATUSES:
            raise MemoryError(
                f"非法状态: {status} (可选: {PROPOSAL_STATUSES})"
            )
        with self._lock:
            return [
                dict(r) for r in self._records.values()
                if r["status"] == status
            ]

    def lifecycle(self, proposal_id: str) -> List[Dict[str, Any]]:
        """方案生命周期事件"""
        with self._lock:
            rec = self._records.get(proposal_id)
            if rec is None:
                raise MemoryError(f"方案不存在: {proposal_id}")
            return [dict(e) for e in rec.get("lifecycle", [])]

    def stats(self) -> Dict[str, Any]:
        """方案记忆统计"""
        with self._lock:
            records = list(self._records.values())
        by_status: Dict[str, int] = {}
        for r in records:
            by_status[r["status"]] = by_status.get(r["status"], 0) + 1
        return {
            "mode": "rule_based",
            "total": len(records),
            "by_status": by_status,
            "approved": by_status.get("APPROVED", 0),
            "rejected": by_status.get("REJECTED", 0),
            "executed": by_status.get("EXECUTED", 0),
            "completed": by_status.get("COMPLETED", 0),
            "failed": by_status.get("FAILED", 0),
        }

    # ── 持久化 (JSONL) ───────────────────────────────────────────
    def save_to_file(self, path: str = "") -> int:
        """持久化到 JSONL 文件

        Args:
            path: 文件路径 (空 → 用初始化 persist_path)

        Returns:
            写入条数
        """
        with self._lock:
            records = [dict(r) for r in self._records.values()]
        target = path or self._persist_path
        if not target:
            raise MemoryError("未指定持久化路径")
        try:
            os.makedirs(os.path.dirname(os.path.abspath(target)),
                        exist_ok=True)
            with open(target, "w", encoding="utf-8") as f:
                for r in records:
                    f.write(json.dumps(
                        r, ensure_ascii=False,
                    ) + "\n")
            logger.info(f"[ProposalMemory] 已持久化 {len(records)} 条到 {target}")
            return len(records)
        except OSError as e:
            raise MemoryError(f"持久化失败: {e}")

    def load_from_file(self, path: str = "") -> int:
        """从 JSONL 加载

        Args:
            path: 文件路径 (空 → 用初始化 persist_path)

        Returns:
            加载条数
        """
        target = path or self._persist_path
        if not target:
            raise MemoryError("未指定持久化路径")
        if not os.path.exists(target):
            raise MemoryError(f"持久化文件不存在: {target}")
        loaded = 0
        try:
            with open(target, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if rec.get("proposal_id"):
                        self._records[rec["proposal_id"]] = rec
                        loaded += 1
        except OSError as e:
            raise MemoryError(f"加载失败: {e}")
        logger.info(f"[ProposalMemory] 已加载 {loaded} 条从 {target}")
        return loaded

    # ── 生命周期 ──────────────────────────────────────────────────
    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = len(self._records)
            self._records.clear()
            return n


__all__ = [
    "PROPOSAL_STATUSES",
    "PROPOSAL_TRANSITIONS",
    "MemoryError",
    "ProposalMemory",
]
