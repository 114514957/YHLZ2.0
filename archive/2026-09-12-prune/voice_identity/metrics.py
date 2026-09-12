"""
YHLZ Voice Identity System V2.3-Phase8 - Metrics 监控系统

职责:
    - 收集 Voice Identity 系统运行指标
    - 暴露 /metrics 端点 (Prometheus 文本格式)
    - 指标: clone_total / clone_success / clone_failed / clone_latency /
            quality_score / adapter_error

API:
    get_metrics() → MetricsCollector  (单例)
    record_clone(success, latency, voice_id, quality_score)
    record_adapter_error(engine, error_type)
    render_prometheus() → str  (Prometheus 文本格式)

设计原则:
    - 纯 stdlib, 无新依赖 (不强制 prometheus_client)
    - 线程安全 (threading.Lock)
    - 兼容 Prometheus 文本格式 (可直接被 scrape)
    - 低开销 (计数器/直方图, 不存储原始事件)
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class HistogramBucket:
    """直方图桶"""
    upper_bound: float
    count: int = 0


@dataclass
class MetricState:
    """指标状态"""
    # 计数器
    clone_total: int = 0
    clone_success: int = 0
    clone_failed: int = 0
    adapter_error_total: int = 0

    # 直方图 (延迟分布, 单位秒)
    latency_buckets: List[HistogramBucket] = field(default_factory=lambda: [
        HistogramBucket(0.5),    # <500ms
        HistogramBucket(1.0),    # <1s
        HistogramBucket(2.0),    # <2s
        HistogramBucket(5.0),    # <5s
        HistogramBucket(10.0),   # <10s
        HistogramBucket(30.0),   # <30s
        HistogramBucket(float('inf')),  # +Inf
    ])

    latency_sum: float = 0.0
    latency_count: int = 0

    # 质量评分分布
    quality_sum: float = 0.0
    quality_count: int = 0

    # Adapter 错误分类
    adapter_errors: Dict[str, int] = field(default_factory=dict)

    # 最后一次克隆信息
    last_clone_voice_id: Optional[str] = None
    last_clone_latency: Optional[float] = None
    last_clone_quality: Optional[float] = None
    last_clone_time: Optional[float] = None


class MetricsCollector:
    """指标收集器 (线程安全)

    使用:
        collector = get_metrics()
        collector.record_clone(success=True, latency=1.5, voice_id="v1", quality_score=0.85)
        prom_text = collector.render_prometheus()
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._state = MetricState()

    def reset(self) -> None:
        """重置所有指标 (测试用)"""
        with self._lock:
            self._state = MetricState()

    def record_clone(
        self,
        success: bool,
        latency: float,
        voice_id: Optional[str] = None,
        quality_score: Optional[float] = None,
    ) -> None:
        """记录一次克隆操作"""
        with self._lock:
            self._state.clone_total += 1
            if success:
                self._state.clone_success += 1
            else:
                self._state.clone_failed += 1

            # 延迟直方图
            self._state.latency_sum += latency
            self._state.latency_count += 1
            for bucket in self._state.latency_buckets:
                if latency <= bucket.upper_bound:
                    bucket.count += 1

            # 质量评分
            if quality_score is not None:
                self._state.quality_sum += quality_score
                self._state.quality_count += 1

            self._state.last_clone_voice_id = voice_id
            self._state.last_clone_latency = latency
            self._state.last_clone_quality = quality_score
            self._state.last_clone_time = time.time()

    def record_adapter_error(self, engine: str, error_type: str = "unknown") -> None:
        """记录 Adapter 错误"""
        with self._lock:
            self._state.adapter_error_total += 1
            key = f"{engine}:{error_type}"
            self._state.adapter_errors[key] = self._state.adapter_errors.get(key, 0) + 1

    def get_snapshot(self) -> MetricState:
        """获取指标快照 (线程安全)"""
        with self._lock:
            # 返回副本 (简化: 直接返回 state, 调用方不应修改)
            return self._state

    def render_prometheus(self) -> str:
        """渲染 Prometheus 文本格式

        返回可直接作为 /metrics 端点响应体的文本。
        """
        with self._lock:
            s = self._state
            lines: List[str] = []

            # ── HELP / TYPE ──
            lines.append("# HELP voice_clone_total Total number of voice clone operations")
            lines.append("# TYPE voice_clone_total counter")
            lines.append(f"voice_clone_total {s.clone_total}")

            lines.append("# HELP voice_clone_success Total successful voice clones")
            lines.append("# TYPE voice_clone_success counter")
            lines.append(f"voice_clone_success {s.clone_success}")

            lines.append("# HELP voice_clone_failed Total failed voice clones")
            lines.append("# TYPE voice_clone_failed counter")
            lines.append(f"voice_clone_failed {s.clone_failed}")

            lines.append("# HELP voice_clone_latency_seconds Clone latency in seconds")
            lines.append("# TYPE voice_clone_latency_seconds histogram")
            # 直方图: 各桶累积计数 + 总和 + 总数
            cumulative = 0
            for bucket in s.latency_buckets:
                cumulative = bucket.count  # 已是累积
                le = "+Inf" if bucket.upper_bound == float('inf') else str(bucket.upper_bound)
                lines.append(f'voice_clone_latency_seconds_bucket{{le="{le}"}} {cumulative}')
            lines.append(f"voice_clone_latency_seconds_sum {s.latency_sum:.4f}")
            lines.append(f"voice_clone_latency_seconds_count {s.latency_count}")

            lines.append("# HELP voice_quality_score Voice quality score (0-1)")
            lines.append("# TYPE voice_quality_score summary")
            if s.quality_count > 0:
                avg_quality = s.quality_sum / s.quality_count
                lines.append(f'voice_quality_score{{quantile="0.5"}} {avg_quality:.4f}')
            else:
                lines.append('voice_quality_score{quantile="0.5"} 0')
            lines.append(f"voice_quality_score_sum {s.quality_sum:.4f}")
            lines.append(f"voice_quality_score_count {s.quality_count}")

            lines.append("# HELP voice_adapter_error_total Total adapter errors")
            lines.append("# TYPE voice_adapter_error_total counter")
            lines.append(f"voice_adapter_error_total {s.adapter_error_total}")
            for key, count in s.adapter_errors.items():
                engine, error_type = key.split(":", 1) if ":" in key else (key, "unknown")
                lines.append(
                    f'voice_adapter_error_total{{engine="{engine}",error_type="{error_type}"}} {count}'
                )

            # 最后一次克隆信息 (gauge)
            lines.append("# HELP voice_last_clone_latency_seconds Last clone latency")
            lines.append("# TYPE voice_last_clone_latency_seconds gauge")
            if s.last_clone_latency is not None:
                lines.append(f"voice_last_clone_latency_seconds {s.last_clone_latency:.4f}")
            else:
                lines.append("voice_last_clone_latency_seconds 0")

            lines.append("# HELP voice_last_clone_quality Last clone quality score")
            lines.append("# TYPE voice_last_clone_quality gauge")
            if s.last_clone_quality is not None:
                lines.append(f"voice_last_clone_quality {s.last_clone_quality:.4f}")
            else:
                lines.append("voice_last_clone_quality 0")

            return "\n".join(lines) + "\n"


# ==================================================================
# 模块级单例
# ==================================================================

_metrics: Optional[MetricsCollector] = None
_metrics_lock = threading.Lock()


def get_metrics() -> MetricsCollector:
    """获取全局 MetricsCollector 单例"""
    global _metrics
    with _metrics_lock:
        if _metrics is None:
            _metrics = MetricsCollector()
        return _metrics


def reset_metrics() -> None:
    """重置全局单例 (测试用)"""
    global _metrics
    with _metrics_lock:
        _metrics = None


def record_clone(
    success: bool,
    latency: float,
    voice_id: Optional[str] = None,
    quality_score: Optional[float] = None,
) -> None:
    """便捷函数: 记录克隆操作"""
    get_metrics().record_clone(
        success=success, latency=latency,
        voice_id=voice_id, quality_score=quality_score,
    )


def record_adapter_error(engine: str, error_type: str = "unknown") -> None:
    """便捷函数: 记录 Adapter 错误"""
    get_metrics().record_adapter_error(engine, error_type)


def render_prometheus() -> str:
    """便捷函数: 渲染 Prometheus 文本"""
    return get_metrics().render_prometheus()
