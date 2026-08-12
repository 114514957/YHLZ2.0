"""
YHLZ Human Interaction Layer V10.1.2 - 人类协作者输入层 (Human Operator Layer)

职责:
    - 记录: 用户任务 / 用户反馈 / 协作体验 / 问题发现 / 新想法
    - Daily Feedback: Date / Task / Experience / Problem / Suggestion
    - 保存: human_feedback/

设计原则:
    - 所有输入必须经过价值判断 (不是数据堆积)
    - 用户明确提供的信息才记录 (不推断/不创造)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class HumanLayerError(Exception):
    """人类协作者层异常"""


# 记录类型 (可解释)
HUMAN_RECORD_TYPES: List[str] = [
    "task",       # 用户任务
    "feedback",   # 用户反馈
    "experience", # 协作体验
    "issue",      # 问题发现
    "idea",       # 新想法
]


class HumanOperatorLayer:
    """人类协作者输入层 (V10.1.2)

    用法:
        layer = HumanOperatorLayer()
        layer.record("task", "完成热机验收", user="老万")
        r = layer.daily_feedback(
            date="2026-08-09", task="...", experience="...",
            problem="...", suggestion="...",
        )
    """

    def __init__(
        self,
        save_dir: str = "",
        max_records: int = 2000,
        enabled: bool = True,
    ):
        if max_records <= 0:
            raise HumanLayerError(
                f"max_records 必须 > 0, 当前: {max_records}"
            )
        self._lock = threading.RLock()
        self._max_records = int(max_records)
        self._enabled = bool(enabled)
        self._save_dir = save_dir or str(
            Path(__file__).resolve().parent.parent.parent
            / "human_feedback",
        )
        Path(self._save_dir).mkdir(exist_ok=True)
        self._records: List[Dict[str, Any]] = []

    def record(
        self,
        record_type: str,
        content: str,
        user: str = "",
        source: str = "user",
    ) -> Dict[str, Any]:
        """记录用户输入 (任务/反馈/体验/问题/想法)"""
        with self._lock:
            if not self._enabled:
                return {"mode": "error_frame", "ok": False,
                        "reason": "人类协作者层停用"}
            if record_type not in HUMAN_RECORD_TYPES:
                raise HumanLayerError(
                    f"非法记录类型: {record_type} "
                    f"(可选: {HUMAN_RECORD_TYPES})"
                )
            if not str(content).strip():
                raise HumanLayerError("内容不能为空")
            record = {
                "record_id": "hr_" + uuid.uuid4().hex[:10],
                "timestamp": time.time(),
                "type": record_type,
                "content": str(content),
                "user": str(user),
                "source": str(source),
                "value_score": self._assess_value(str(content)),
            }
            self._records.append(record)
            if len(self._records) > self._max_records:
                self._records = self._records[-self._max_records:]
            self._save_daily(record)
            return {
                "mode": "rule_based", "ok": True,
                **record,
            }

    def daily_feedback(
        self,
        date: str,
        task: str = "",
        experience: str = "",
        problem: str = "",
        suggestion: str = "",
    ) -> Dict[str, Any]:
        """每日反馈 (保存 human_feedback/)"""
        with self._lock:
            if not self._enabled:
                return {"mode": "error_frame", "ok": False,
                        "reason": "人类协作者层停用"}
            entry = {
                "date": str(date),
                "task": str(task),
                "experience": str(experience),
                "problem": str(problem),
                "suggestion": str(suggestion),
                "timestamp": time.time(),
            }
            path = Path(self._save_dir) / f"feedback_{date}.json"
            entries = []
            if path.exists():
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        entries = json.load(f)
                except Exception:
                    entries = []
            entries.append(entry)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(entries, f, indent=2, ensure_ascii=False)
            logger.info(f"[HumanLayer] 每日反馈已保存: {path.name}")
            return {"mode": "rule_based", "ok": True,
                    "saved_to": str(path), "entry": entry}

    def _assess_value(self, content: str) -> int:
        """价值判断 (0-10)"""
        score = 4
        for kw in ("问题", "建议", "想法", "方案", "计划",
                   "发现", "结论", "需求"):
            if kw in content:
                score += 1
        return min(score, 10)

    def _save_daily(self, record: Dict[str, Any]) -> None:
        """按日保存 (JSONL)"""
        day = time.strftime("%Y%m%d", time.localtime(
            record["timestamp"],
        ))
        path = Path(self._save_dir) / f"records_{day}.jsonl"
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def query(
        self,
        record_type: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """查询记录 (最新在前)"""
        with self._lock:
            records = list(self._records)
        out = []
        for r in reversed(records):
            if record_type and r["type"] != record_type:
                continue
            out.append(dict(r))
            if 0 < limit <= len(out):
                break
        return out

    def stats(self) -> Dict[str, Any]:
        """统计"""
        with self._lock:
            by_type: Dict[str, int] = {}
            for r in self._records:
                by_type[r["type"]] = by_type.get(r["type"], 0) + 1
            return {
                "mode": "rule_based",
                "enabled": self._enabled,
                "total": len(self._records),
                "by_type": by_type,
                "save_dir": self._save_dir,
            }

    def clear(self) -> int:
        """清空内存记录 (测试隔离, 不删文件)"""
        with self._lock:
            n = len(self._records)
            self._records.clear()
            return n


__all__ = [
    "HUMAN_RECORD_TYPES",
    "HumanLayerError",
    "HumanOperatorLayer",
]
