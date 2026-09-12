"""
YHLZ Embodied AI V6.1.1 - 成长节律 (Growth Rhythm)

职责:
    - 让成长从"人工调用"升级为"自动节律"
    - 流程:
      Handle → Event Capture → Growth Track → Threshold Check
      → Memory Consolidation → Reflection Trigger → Snapshot

自动行为 (全部审计):
    - handle 联动: 任务完成自动 track_event
      (experience_added / task_completed / relationship_change)
    - 经验验证完成: 自动 experience_confirmed
    - 自动整理: 经验数达阈值 / 距上次整理超天数 (ConsolidationScheduler)
    - 自动反思: 整理后触发 (配置开关)
    - 自动快照: 每日一次 (配置开关)

自主成长边界:
    - 允许: 自动记录 / 自动整理 / 自动生成报告
    - 禁止: 自动改变人格 / 目标 / 核心价值 / 高风险行为

设计原则:
    - 自动行为必须可审计 (禁止静默)
    - 纯规则 (无黑盒)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, Optional

from backend.embodied.companion.rhythm.consolidation_scheduler import (
    ConsolidationScheduler,
)
from backend.embodied.companion.rhythm.growth_trigger import (
    GrowthTrigger,
)
from backend.embodied.companion.rhythm.rhythm_audit import (
    RhythmAudit,
)

logger = logging.getLogger(__name__)


class RhythmError(Exception):
    """成长节律操作异常"""


class GrowthRhythm:
    """成长节律器 (自动采集 + 自动整理 + 自动快照)

    用法:
        rhythm = GrowthRhythm(
            continuity=engine, emotion=emotion_engine,
            config={...},
        )
        rhythm.on_handle(request, response)
    """

    def __init__(
        self,
        continuity=None,
        emotion=None,
        enabled: bool = True,
        config: Optional[Dict[str, Any]] = None,
    ):
        cfg = dict(config or {})
        self._lock = threading.RLock()
        self._enabled = bool(enabled)
        self._continuity = continuity
        self._emotion = emotion
        # 触发阈值
        self._consolidate_threshold = int(cfg.get(
            "companion_rhythm_consolidate_threshold", 20,
        ))
        self._consolidate_days = int(cfg.get(
            "companion_rhythm_consolidate_days", 7,
        ))
        self._daily_snapshot = bool(cfg.get(
            "companion_rhythm_daily_snapshot", True,
        ))
        self._auto_reflection = bool(cfg.get(
            "companion_rhythm_auto_reflection", True,
        ))
        self._trigger = GrowthTrigger(
            consolidate_threshold=self._consolidate_threshold,
            consolidate_days=self._consolidate_days,
        )
        self._scheduler = ConsolidationScheduler(
            trigger=self._trigger, default_days=self._consolidate_days,
        )
        self._audit = RhythmAudit()
        self._last_snapshot: float = 0.0
        self._last_reflect: float = 0.0
        self._snapshot_count = 0
        self._capture_count = 0
        self._reflection_count = 0

    # ── Handle 联动 (事件采集) ──────────────────────────────────
    def on_handle(self, request: Optional[Dict[str, Any]] = None,
                  response: Optional[Dict[str, Any]] = None,
                  now: Optional[float] = None) -> Dict[str, Any]:
        """handle 完成后自动采集成长事件

        Args:
            request: 请求 (可空)
            response: handle 响应 (可空, 含 aggregated)

        Returns:
            {
                'captured': [...], 'consolidated', 'snapshot_taken',
                'reflection_triggered', 'mode',
            }
        """
        with self._lock:
            if not self._enabled:
                return {"mode": "rule_based", "enabled": False}
            now = now if now is not None else time.time()
            captured: List[str] = []
            # 1. 事件采集 (experience_added / task_completed)
            if self._continuity is not None:
                try:
                    self._continuity.track_event(
                        "experience_added",
                        detail="handle 联动: 任务完成产生经历",
                        meta={"request_intent": (
                            (request or {}).get("intent", "")
                            if request else ""
                        )},
                    )
                    captured.append("experience_added")
                    self._continuity.track_event(
                        "task_completed",
                        detail="handle 联动: 任务完成",
                    )
                    captured.append("task_completed")
                except Exception as e:
                    logger.warning(f"[Rhythm] 事件采集失败: {e}")
                    self._audit.record(action="error",
                                       detail=f"采集失败: {e}")
            # 2. 情绪联动 (按任务结果)
            if self._emotion is not None and response is not None:
                try:
                    agg = response.get("aggregated", {})
                    ok = agg.get("ok_count", 0)
                    total = agg.get("total", 0)
                    if total > 0:
                        if ok == total:
                            self._emotion.update("success")
                        elif ok == 0:
                            self._emotion.update("failure")
                except Exception as e:
                    logger.warning(f"[Rhythm] 情绪联动失败: {e}")
            # 3. 阈值检查 + 自动整理
            consolidated = self._auto_consolidate(now)
            # 4. 自动快照 (每日一次)
            snapshot_taken = self._auto_snapshot(now)
            # 5. 反思触发
            reflection_triggered = self._auto_reflect(now)
            self._capture_count += len(captured)
            for c in captured:
                self._audit.record(action="capture", detail=c)
            return {
                "mode": "rule_based",
                "captured": captured,
                "consolidated": consolidated,
                "snapshot_taken": snapshot_taken,
                "reflection_triggered": reflection_triggered,
            }

    # ── 自动整理 ─────────────────────────────────────────────────
    def _auto_consolidate(self, now: float) -> bool:
        """阈值检查 → 自动整理"""
        experience_count = 0
        if self._continuity is not None and \
                self._continuity._experience is not None:
            try:
                experience_count = self._continuity._experience.stats()[
                    "total"]
            except Exception as e:
                logger.warning(f"[Rhythm] 读取经历数失败: {e}")
        result = self._scheduler.tick(
            experience_count=experience_count,
            consolidate_fn=self._consolidate_callback,
            now=now,
        )
        if result["triggered"] and result["consolidated"]:
            self._audit.record(
                action="consolidate",
                detail="; ".join(
                    r["reason"] for r in result["reasons"]
                    if r["triggered"]
                ),
            )
            return True
        if not result["triggered"]:
            self._audit.record(
                action="skip", detail="整理条件未达",
            )
        return False

    def _consolidate_callback(self) -> Dict[str, Any]:
        """整理回调 (经 ContinuityEngine)"""
        if self._continuity is None:
            return {"mode": "rule_based", "note": "无连续引擎"}
        return self._continuity.consolidate()

    # ── 自动快照 ─────────────────────────────────────────────────
    def _auto_snapshot(self, now: float) -> bool:
        """每日一次自动快照"""
        if not self._daily_snapshot:
            return False
        if self._last_snapshot > 0 and \
                (now - self._last_snapshot) < 86400.0:
            return False
        if self._continuity is None:
            return False
        path = self._continuity._path
        if not path:
            self._audit.record(
                action="skip", detail="未配置持久化路径, 跳过自动快照",
            )
            return False
        try:
            self._continuity.save(path)
            self._last_snapshot = now
            self._snapshot_count += 1
            self._audit.record(
                action="snapshot", detail="每日自动快照",
            )
            return True
        except Exception as e:
            logger.warning(f"[Rhythm] 自动快照失败: {e}")
            self._audit.record(action="error",
                               detail=f"快照失败: {e}")
            return False

    # ── 反思触发 ─────────────────────────────────────────────────
    def _auto_reflect(self, now: float) -> bool:
        """整理后反思触发 (每天至多一次)"""
        if not self._auto_reflection:
            return False
        if self._continuity is None:
            return False
        # 距上次反思不足 1 天 → 跳过
        if self._last_reflect > 0 and \
                (now - self._last_reflect) < 86400.0:
            return False
        try:
            refl = self._continuity._reflection
            if refl is None:
                return False
            records = []
            if self._continuity._experience is not None:
                records = [
                    r.to_dict()
                    for r in self._continuity._experience._store.all()
                ]
            refl.reflect(records)
            self._last_reflect = now
            self._reflection_count += 1
            self._audit.record(
                action="reflection", detail="自动反思触发",
            )
            return True
        except Exception as e:
            logger.warning(f"[Rhythm] 反思触发失败: {e}")
            self._audit.record(action="error",
                               detail=f"反思失败: {e}")
            return False

    # ── 手动触发 ─────────────────────────────────────────────────
    def run_cycle(self, request=None, response=None) -> Dict[str, Any]:
        """手动运行完整节律循环"""
        return self.on_handle(request, response)

    # ── 查询 ─────────────────────────────────────────────────────
    def stats(self) -> Dict[str, Any]:
        """节律统计"""
        with self._lock:
            return {
                "mode": "rule_based",
                "enabled": self._enabled,
                "capture_count": self._capture_count,
                "consolidate_count": self._scheduler.stats()[
                    "run_count"],
                "snapshot_count": self._snapshot_count,
                "reflection_count": self._reflection_count,
                "thresholds": self._trigger.thresholds(),
                "daily_snapshot": self._daily_snapshot,
                "auto_reflection": self._auto_reflection,
            }

    def audit_report(self, limit: int = 100) -> Dict[str, Any]:
        """节律审计报告"""
        return self._audit.report(limit=limit)

    def scheduler_stats(self) -> Dict[str, Any]:
        """整理调度统计"""
        return self._scheduler.stats()

    def clear(self) -> Dict[str, Any]:
        """清空 (测试隔离)"""
        with self._lock:
            n_audit = self._audit.clear()
            n_sched = self._scheduler.clear()
            self._last_snapshot = 0.0
            self._snapshot_count = 0
            self._capture_count = 0
            self._reflection_count = 0
            self._last_reflect = 0.0
            return {"audit": n_audit, "scheduler": n_sched}


__all__ = [
    "GrowthRhythm",
    "RhythmError",
]
