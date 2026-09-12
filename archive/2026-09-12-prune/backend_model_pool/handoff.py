"""
YHLZ Model Pool Router V10.1.3 - 模型交接协议 (Model Handoff Memory)

职责:
    - 模型切换时的上下文交接: 用户/项目/任务/已完成/结论/约束/下一步
    - 主体连续性保护: 所有模型必须加载 User Identity Anchor /
      YHLZ Project Context / Collaboration Rules / Current Task Context

设计原则:
    - 模型变化, 元亨连续
    - 交接记录可回放
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class HandoffError(Exception):
    """模型交接异常"""


class ModelHandoff:
    """模型交接协议 (V10.1.3)

    用法:
        h = ModelHandoff()
        hoff = h.create(
            from_model="qwen-turbo", to_model="deepseek-chat",
            user="老万", project="YHLZ", task="热机验收",
            completed="...", conclusion="...", constraints="...",
            next_step="...",
        )
        ctx = h.context_for_model("deepseek-chat")
    """

    def __init__(self, max_records: int = 200,
                 enabled: bool = True):
        if max_records <= 0:
            raise HandoffError(
                f"max_records 必须 > 0, 当前: {max_records}"
            )
        self._lock = threading.RLock()
        self._max_records = int(max_records)
        self._enabled = bool(enabled)
        self._records: List[Dict[str, Any]] = []

    def create(
        self,
        from_model: str,
        to_model: str,
        user: str = "",
        project: str = "",
        task: str = "",
        completed: str = "",
        conclusion: str = "",
        constraints: str = "",
        next_step: str = "",
    ) -> Dict[str, Any]:
        """创建交接记录"""
        with self._lock:
            if not self._enabled:
                return {"mode": "error_frame", "ok": False,
                        "reason": "模型交接协议停用"}
            record = {
                "handoff_id": "ho_" + uuid.uuid4().hex[:10],
                "timestamp": time.time(),
                "from_model": str(from_model),
                "to_model": str(to_model),
                "user": str(user),
                "project": str(project),
                "task": str(task),
                "completed": str(completed),
                "conclusion": str(conclusion),
                "constraints": str(constraints),
                "next_step": str(next_step),
            }
            self._records.append(record)
            if len(self._records) > self._max_records:
                self._records = self._records[-self._max_records:]
            logger.info(
                f"[ModelPool] 交接 {from_model} → {to_model} "
                f"(task={task[:30]})"
            )
            return dict(record)

    def context_for_model(
        self,
        model_id: str,
    ) -> Dict[str, Any]:
        """为指定模型生成主体连续性上下文

        Returns:
            {
                'mode', 'model_id',
                'identity_anchor_loaded': bool,
                'handoff': 最近交接记录 (若有),
            }
        """
        with self._lock:
            latest = None
            for r in reversed(self._records):
                if r["to_model"] == model_id:
                    latest = dict(r)
                    break
            return {
                "mode": "rule_based",
                "ok": True,
                "model_id": str(model_id),
                "identity_anchor_loaded": True,
                "handoff": latest,
            }

    def history(
        self,
        model_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """交接历史 (最新在前)"""
        with self._lock:
            records = list(self._records)
        out = []
        for r in reversed(records):
            if model_id and r["to_model"] != model_id and \
                    r["from_model"] != model_id:
                continue
            out.append(dict(r))
            if 0 < limit <= len(out):
                break
        return out

    def stats(self) -> Dict[str, Any]:
        """统计"""
        with self._lock:
            return {
                "mode": "rule_based",
                "enabled": self._enabled,
                "total_handoffs": len(self._records),
            }

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = len(self._records)
            self._records.clear()
            return n


__all__ = [
    "HandoffError",
    "ModelHandoff",
]
