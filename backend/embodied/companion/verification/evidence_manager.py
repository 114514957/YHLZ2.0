"""
YHLZ Embodied AI V5.8 - 证据管理器 (Evidence Manager)

职责:
    - 保存经验依据: 每条重要经验关联 来源事件 / 时间 / 结果 / 证据
    - 证据查询: 按经验 ID / 来源

设计原则:
    - 可回溯: 所有验证都有证据支撑
    - 只存元数据与摘要 (不存完整聊天)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class EvidenceError(Exception):
    """证据管理操作异常"""


class EvidenceManager:
    """证据管理器

    用法:
        mgr = EvidenceManager()
        eid = mgr.add(experience_id="exp_1", source="run_goal",
                      result="success", evidence="位置匹配")
        evidence = mgr.for_experience("exp_1")
    """

    def __init__(self, max_evidence: int = 500):
        if max_evidence <= 0:
            raise EvidenceError(
                f"max_evidence 必须 > 0, 当前: {max_evidence}"
            )
        self._lock = threading.RLock()
        self._records: List[Dict[str, Any]] = []
        self._max_evidence = int(max_evidence)

    def add(
        self,
        experience_id: str,
        source: str = "",
        result: str = "",
        evidence: str = "",
        timestamp: Optional[float] = None,
    ) -> str:
        """添加证据 (返回证据 ID)"""
        eid = "ev_" + uuid.uuid4().hex[:8]
        entry = {
            "evidence_id": eid,
            "experience_id": experience_id,
            "source": source,
            "result": result,
            "evidence": evidence,
            "timestamp": timestamp if timestamp is not None
            else time.time(),
        }
        with self._lock:
            self._records.append(entry)
            if len(self._records) > self._max_evidence:
                self._records = self._records[-self._max_evidence:]
        return eid

    def for_experience(self, experience_id: str) -> List[Dict[str, Any]]:
        """某经验的全部证据"""
        with self._lock:
            return [
                dict(r) for r in self._records
                if r["experience_id"] == experience_id
            ]

    def count_for(self, experience_id: str) -> int:
        """某经验证据数"""
        with self._lock:
            return sum(
                1 for r in self._records
                if r["experience_id"] == experience_id
            )

    def total(self) -> int:
        """证据总数"""
        with self._lock:
            return len(self._records)

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = len(self._records)
            self._records.clear()
            return n


__all__ = [
    "EvidenceError",
    "EvidenceManager",
]
