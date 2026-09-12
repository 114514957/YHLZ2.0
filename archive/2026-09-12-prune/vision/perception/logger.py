"""
YHLZ Vision Perception V1.0 - 感知日志系统

职责:
    - 记录感知处理全生命周期日志
    - 字段: 开始 / 成功 / 失败 / 耗时 / 异常原因 / Provider 名
    - 支持内存缓冲 + 落盘
    - 支持查询与统计

设计原则:
    - 不依赖 Adapter (Adapter 仅产生结果, Logger 单独记录)
    - 线程安全
    - 可配置保留数量
    - 结构化日志 (PerceptionLogEntry dataclass)

与 VisionLogger 的关系:
    - 独立日志系统 (不与 VisionLogger 共享)
    - 但字段风格保持一致, 便于运维统一查询
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
class PerceptionLogEntry:
    """感知日志条目

    字段:
        timestamp:   日志时间戳
        source:      感知来源 (ocr / detection / mock / combined)
        adapter:     适配器名
        provider:    底层 Provider 名 (paddleocr / tesseract / yolo / mock)
        event:       事件类型 (start / success / fail / exception)
        latency_ms:  耗时 (毫秒, start 时为 0)
        result_id:    关联的 PerceptionResult.id
        status:       结果状态 (success 时为 ok)
        object_count: 检测到的对象数
        text_count:   识别到的文本数
        confidence:   平均置信度
        error:        错误描述 (失败时)
        metadata:     附加元数据
    """
    timestamp: float = field(default_factory=time.time)
    source: str = ""
    adapter: str = ""
    provider: str = ""
    event: str = ""              # start / success / fail / exception
    latency_ms: float = 0.0
    result_id: str = ""
    status: str = ""
    object_count: int = 0
    text_count: int = 0
    confidence: float = 0.0
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "source": self.source,
            "adapter": self.adapter,
            "provider": self.provider,
            "event": self.event,
            "latency_ms": round(self.latency_ms, 2),
            "result_id": self.result_id,
            "status": self.status,
            "object_count": self.object_count,
            "text_count": self.text_count,
            "confidence": round(self.confidence, 4),
            "error": self.error,
            "metadata": self.metadata,
        }


class PerceptionLogger:
    """感知日志记录器

    用法:
        plog = PerceptionLogger(max_entries=1000)
        plog.log_start(source="ocr", adapter="OCRAdapter")
        # ... 处理 ...
        plog.log_success(source="ocr", adapter="OCRAdapter",
                        result_id=result.id, latency_ms=latency,
                        text_count=len(result.text))
        # 查询
        entries = plog.query(source="ocr", limit=10)
        stats = plog.stats()

    特性:
        - 内存环形缓冲 (deque), 防止无限增长
        - 线程安全 (Lock)
        - 同步写入 Python logging (供文件/控制台输出)
        - 可选落盘 (save_to_file)
    """

    def __init__(self, max_entries: int = 1000, enable_logging: bool = True):
        self._lock = threading.RLock()
        self._entries: Deque[PerceptionLogEntry] = deque(maxlen=max_entries)
        self._max_entries = max_entries
        self._enable_logging = enable_logging

    def log_start(
        self,
        source: str,
        adapter: str,
        provider: str = "unknown",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> PerceptionLogEntry:
        """记录处理开始"""
        entry = PerceptionLogEntry(
            source=source,
            adapter=adapter,
            provider=provider,
            event="start",
            metadata=metadata or {},
        )
        self._append(entry)
        if self._enable_logging:
            logger.info(
                f"[Perception] 处理开始 source={source} adapter={adapter} provider={provider}"
            )
        return entry

    def log_success(
        self,
        source: str,
        adapter: str,
        result_id: str,
        latency_ms: float,
        provider: str = "unknown",
        object_count: int = 0,
        text_count: int = 0,
        confidence: float = 0.0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> PerceptionLogEntry:
        """记录处理成功"""
        entry = PerceptionLogEntry(
            source=source,
            adapter=adapter,
            provider=provider,
            event="success",
            latency_ms=latency_ms,
            result_id=result_id,
            status="ok",
            object_count=object_count,
            text_count=text_count,
            confidence=confidence,
            metadata=metadata or {},
        )
        self._append(entry)
        if self._enable_logging:
            logger.info(
                f"[Perception] 处理成功 source={source} result={result_id} "
                f"objects={object_count} texts={text_count} latency={latency_ms:.1f}ms"
            )
        return entry

    def log_fail(
        self,
        source: str,
        adapter: str,
        status: str,
        error: str,
        latency_ms: float = 0.0,
        provider: str = "unknown",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> PerceptionLogEntry:
        """记录处理失败"""
        entry = PerceptionLogEntry(
            source=source,
            adapter=adapter,
            provider=provider,
            event="fail",
            latency_ms=latency_ms,
            status=status,
            error=error,
            metadata=metadata or {},
        )
        self._append(entry)
        if self._enable_logging:
            logger.warning(
                f"[Perception] 处理失败 source={source} status={status} "
                f"error={error} latency={latency_ms:.1f}ms"
            )
        return entry

    def log_exception(
        self,
        source: str,
        adapter: str,
        error: str,
        provider: str = "unknown",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> PerceptionLogEntry:
        """记录异常 (Adapter 未捕获的)"""
        entry = PerceptionLogEntry(
            source=source,
            adapter=adapter,
            provider=provider,
            event="exception",
            error=error,
            metadata=metadata or {},
        )
        self._append(entry)
        logger.error(
            f"[Perception] 处理异常 source={source} adapter={adapter} "
            f"provider={provider} error={error}"
        )
        return entry

    def _append(self, entry: PerceptionLogEntry) -> None:
        with self._lock:
            self._entries.append(entry)

    def query(
        self,
        source: Optional[str] = None,
        adapter: Optional[str] = None,
        provider: Optional[str] = None,
        event: Optional[str] = None,
        limit: int = 100,
    ) -> List[PerceptionLogEntry]:
        """查询日志条目 (按条件过滤)"""
        with self._lock:
            entries = list(self._entries)
        result = []
        for e in reversed(entries):  # 最新的在前
            if source and e.source != source:
                continue
            if adapter and e.adapter != adapter:
                continue
            if provider and e.provider != provider:
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
            return {
                "total": 0, "success": 0, "fail": 0, "exception": 0,
                "success_rate": 0.0, "avg_latency_ms": 0.0,
                "total_objects": 0, "total_texts": 0,
            }
        success = sum(1 for e in entries if e.event == "success")
        fail = sum(1 for e in entries if e.event == "fail")
        exception = sum(1 for e in entries if e.event == "exception")
        latencies = [e.latency_ms for e in entries if e.event == "success" and e.latency_ms > 0]
        avg_latency = sum(latencies) / len(latencies) if latencies else 0.0
        success_rate = (success / total * 100.0) if total else 0.0
        total_objects = sum(e.object_count for e in entries if e.event == "success")
        total_texts = sum(e.text_count for e in entries if e.event == "success")
        return {
            "total": total,
            "success": success,
            "fail": fail,
            "exception": exception,
            "success_rate": round(success_rate, 2),
            "avg_latency_ms": round(avg_latency, 2),
            "total_objects": total_objects,
            "total_texts": total_texts,
        }

    def clear(self) -> int:
        """清空日志, 返回清理数量"""
        with self._lock:
            n = len(self._entries)
            self._entries.clear()
        logger.info(f"[Perception] 日志已清空, 清理 {n} 条")
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
        logger.info(f"[Perception] 日志已保存到 {path}, 共 {len(entries)} 条")
        return len(entries)


__all__ = ["PerceptionLogEntry", "PerceptionLogger"]
