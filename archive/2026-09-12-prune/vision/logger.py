"""
YHLZ Vision Foundation V1.0 - 视觉日志系统

职责:
    - 记录视觉采集全生命周期日志
    - 字段: 开始 / 成功 / 失败 / 耗时 / 异常原因
    - 支持内存缓冲 + 落盘
    - 支持查询与统计

设计原则:
    - 不依赖 Adapter (Adapter 仅产生帧, Logger 单独记录)
    - 线程安全
    - 可配置保留数量
    - 结构化日志 (VisionLogEntry dataclass)
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class VisionLogEntry:
    """视觉日志条目

    字段:
        timestamp:   日志时间戳
        source:      视觉来源 (screen / camera / mock)
        adapter:     适配器名
        event:       事件类型 (start / success / fail / exception)
        latency_ms:  耗时 (毫秒, start 时为 0)
        frame_id:    关联的帧 ID
        status:      帧状态 (success 时为 ok)
        error:       错误描述 (失败时)
        metadata:    附加元数据
    """
    timestamp: float = field(default_factory=time.time)
    source: str = ""
    adapter: str = ""
    event: str = ""              # start / success / fail / exception
    latency_ms: float = 0.0
    frame_id: str = ""
    status: str = ""
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "source": self.source,
            "adapter": self.adapter,
            "event": self.event,
            "latency_ms": round(self.latency_ms, 2),
            "frame_id": self.frame_id,
            "status": self.status,
            "error": self.error,
            "metadata": self.metadata,
        }


class VisionLogger:
    """视觉日志记录器

    用法:
        vlog = VisionLogger(max_entries=1000)
        vlog.log_start(source="screen", adapter="ScreenAdapter")
        # ... 采集 ...
        vlog.log_success(source="screen", adapter="ScreenAdapter",
                         frame_id=frame.id, latency_ms=latency)
        # 查询
        entries = vlog.query(source="screen", limit=10)
        stats = vlog.stats()

    特性:
        - 内存环形缓冲 (deque), 防止无限增长
        - 线程安全 (Lock)
        - 同步写入 Python logging (供文件/控制台输出)
        - 可选落盘 (save_to_file)
    """

    def __init__(self, max_entries: int = 1000, enable_logging: bool = True):
        self._lock = threading.RLock()
        self._entries: Deque[VisionLogEntry] = deque(maxlen=max_entries)
        self._max_entries = max_entries
        self._enable_logging = enable_logging  # 是否同步写入 Python logging

    def log_start(
        self,
        source: str,
        adapter: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> VisionLogEntry:
        """记录采集开始"""
        entry = VisionLogEntry(
            source=source,
            adapter=adapter,
            event="start",
            metadata=metadata or {},
        )
        self._append(entry)
        if self._enable_logging:
            logger.info(f"[Vision] 采集开始 source={source} adapter={adapter}")
        return entry

    def log_success(
        self,
        source: str,
        adapter: str,
        frame_id: str,
        latency_ms: float,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> VisionLogEntry:
        """记录采集成功"""
        entry = VisionLogEntry(
            source=source,
            adapter=adapter,
            event="success",
            latency_ms=latency_ms,
            frame_id=frame_id,
            status="ok",
            metadata=metadata or {},
        )
        self._append(entry)
        if self._enable_logging:
            logger.info(f"[Vision] 采集成功 source={source} frame={frame_id} "
                        f"latency={latency_ms:.1f}ms")
        return entry

    def log_fail(
        self,
        source: str,
        adapter: str,
        status: str,
        error: str,
        latency_ms: float = 0.0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> VisionLogEntry:
        """记录采集失败"""
        entry = VisionLogEntry(
            source=source,
            adapter=adapter,
            event="fail",
            latency_ms=latency_ms,
            status=status,
            error=error,
            metadata=metadata or {},
        )
        self._append(entry)
        if self._enable_logging:
            logger.warning(f"[Vision] 采集失败 source={source} status={status} "
                           f"error={error} latency={latency_ms:.1f}ms")
        return entry

    def log_exception(
        self,
        source: str,
        adapter: str,
        error: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> VisionLogEntry:
        """记录异常 (Adapter 未捕获的)"""
        entry = VisionLogEntry(
            source=source,
            adapter=adapter,
            event="exception",
            error=error,
            metadata=metadata or {},
        )
        self._append(entry)
        logger.error(f"[Vision] 采集异常 source={source} adapter={adapter} "
                     f"error={error}")
        return entry

    def _append(self, entry: VisionLogEntry) -> None:
        with self._lock:
            self._entries.append(entry)

    def query(
        self,
        source: Optional[str] = None,
        adapter: Optional[str] = None,
        event: Optional[str] = None,
        limit: int = 100,
    ) -> List[VisionLogEntry]:
        """查询日志条目 (按条件过滤)"""
        with self._lock:
            entries = list(self._entries)
        result = []
        for e in reversed(entries):  # 最新的在前
            if source and e.source != source:
                continue
            if adapter and e.adapter != adapter:
                continue
            if event and e.event != event:
                continue
            result.append(e)
            if len(result) >= limit:
                break
        return result

    def stats(self) -> Dict[str, Any]:
        """统计信息"""
        with self._lock:
            entries = list(self._entries)
        total = len(entries)
        if total == 0:
            return {"total": 0, "success": 0, "fail": 0, "exception": 0,
                    "success_rate": 0.0, "avg_latency_ms": 0.0}
        success = sum(1 for e in entries if e.event == "success")
        fail = sum(1 for e in entries if e.event == "fail")
        exception = sum(1 for e in entries if e.event == "exception")
        latencies = [e.latency_ms for e in entries if e.event == "success" and e.latency_ms > 0]
        avg_latency = sum(latencies) / len(latencies) if latencies else 0.0
        success_rate = (success / total * 100.0) if total else 0.0
        return {
            "total": total,
            "success": success,
            "fail": fail,
            "exception": exception,
            "success_rate": round(success_rate, 2),
            "avg_latency_ms": round(avg_latency, 2),
        }

    def clear(self) -> int:
        """清空日志, 返回清理数量"""
        with self._lock:
            n = len(self._entries)
            self._entries.clear()
        logger.info(f"[Vision] 日志已清空, 清理 {n} 条")
        return n

    def count(self) -> int:
        with self._lock:
            return len(self._entries)

    def save_to_file(self, path: str) -> int:
        """保存日志到文件 (JSON Lines)"""
        import json
        with self._lock:
            entries = list(self._entries)
        with open(path, "w", encoding="utf-8") as f:
            for e in entries:
                f.write(json.dumps(e.to_dict(), ensure_ascii=False) + "\n")
        logger.info(f"[Vision] 日志已保存到 {path}, 共 {len(entries)} 条")
        return len(entries)
