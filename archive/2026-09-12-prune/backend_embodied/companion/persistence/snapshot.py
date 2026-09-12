"""
YHLZ Embodied AI V6.0 - 全量快照 (Companion Snapshot)

职责:
    - 保存完整 AI 伙伴状态:
      Identity / Personality / Relationship / Experience /
      Verification / Reflection / Creative / Creative Memory
    - 结构:
      Snapshot → Version → State → Checksum

设计原则:
    - checksum (sha256) 保证完整性 (可验证)
    - 快照版本独立于 schema (可降级)
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


class SnapshotError(Exception):
    """快照操作异常"""


# 快照域白名单 (可解释)
SNAPSHOT_DOMAINS: List[str] = [
    "identity",         # 身份
    "personality",      # 人格
    "relationship",     # 关系
    "experience",       # 经历
    "verification",     # 验证
    "reflection",       # 反思
    "creative",         # 创造
    "creative_memory",  # 创造方案记忆
    "emotion",          # 情绪 (V6.1.1)
    "perception_stats", # 感知统计 (V6.4)
    "reflection_state", # 认知反思状态 (V6.5)
    "growth_state",     # 成长状态 (V6.5)
]


class CompanionSnapshot:
    """全量状态快照 (Version + State + Checksum)

    用法:
        snap = CompanionSnapshot.build(states)
        ok, reason = CompanionSnapshot.verify(snap)
    """

    def __init__(self, version: str = "9.5.0"):
        if not version:
            raise SnapshotError("版本号不能为空")
        self._lock = threading.RLock()
        self._version = str(version)

    # ── 构建 ─────────────────────────────────────────────────────
    def build(self, states: Dict[str, Any],
              now: Optional[float] = None) -> Dict[str, Any]:
        """构建全量快照

        Args:
            states: 各域状态 dict:
                {"identity": {...}, "personality": {...}, ...}

        Returns:
            {
                'snapshot_id', 'version', 'created_at',
                'checksum', 'state': {...},
            }
        """
        with self._lock:
            now = now if now is not None else time.time()
            state = {}
            for domain in SNAPSHOT_DOMAINS:
                if domain in states and states[domain] is not None:
                    state[domain] = states[domain]
            if not state:
                raise SnapshotError("无任何状态可保存")
            snapshot = {
                "snapshot_id": "snap_" + uuid.uuid4().hex[:8],
                "version": self._version,
                "created_at": now,
                "checksum": self._checksum(state),
                "state": state,
            }
            return snapshot

    # ── 校验 ─────────────────────────────────────────────────────
    def verify(self, snapshot: Dict[str, Any],
               require_domains: Optional[List[str]] = None) -> tuple:
        """校验快照完整性

        Args:
            snapshot: 快照 dict
            require_domains: 必须存在的域 (可空)

        Returns:
            (ok: bool, reason: str)
        """
        with self._lock:
            if not snapshot or not isinstance(snapshot, dict):
                return False, "快照为空或非法"
            for key in ("snapshot_id", "version", "created_at",
                        "checksum", "state"):
                if key not in snapshot:
                    return False, f"快照缺字段 {key}"
            state = snapshot.get("state", {})
            if not isinstance(state, dict) or not state:
                return False, "state 为空"
            # checksum 校验
            expected = self._checksum(state)
            if expected != snapshot.get("checksum"):
                return False, "checksum 不匹配 (数据可能损坏)"
            # 版本兼容 (非空即可, 版本号校验由 Restore 处理)
            if not str(snapshot.get("version", "")):
                return False, "快照版本为空"
            # 必需域
            if require_domains:
                missing = [
                    d for d in require_domains if d not in state
                ]
                if missing:
                    return False, f"缺失必需域 {missing}"
            return True, "快照完整"

    @staticmethod
    def _checksum(state: Dict[str, Any]) -> str:
        """sha256 校验和 (确定性序列化)"""
        canonical = json.dumps(
            state, ensure_ascii=False, sort_keys=True,
        )
        return hashlib.sha256(
            canonical.encode("utf-8"),
        ).hexdigest()

    def domains(self, snapshot: Dict[str, Any]) -> List[str]:
        """快照含有的域"""
        with self._lock:
            return list(snapshot.get("state", {}).keys())

    # ── 统计 ─────────────────────────────────────────────────────
    def stats(self) -> Dict[str, Any]:
        return {
            "mode": "rule_based",
            "version": self._version,
            "domains": list(SNAPSHOT_DOMAINS),
        }


__all__ = [
    "SNAPSHOT_DOMAINS",
    "CompanionSnapshot",
    "SnapshotError",
]
