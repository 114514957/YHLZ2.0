"""
YHLZ Embodied AI V4.3 - 目标回放系统 (Goal Replay)

职责:
    - 保存完整目标轨迹 (GoalTrace): goal / plan / executed actions / feedback /
      analysis / event timeline / final state
    - replay_goal: 回放 (Step N: Observe → Action → Feedback)
    - compare_goals: 目标对比 (步骤数量 / 失败位置 / 时间 / 最终结果)
    - export_goal_trace: 轨迹导出 (JSON / Structured Text, 供验收 / Debug / 复盘)

设计原则:
    - 轨迹不可变: 记录后不可修改, 保证复盘可信
    - 数据独立存储: 绝不写入 Agent Memory
    - 线程安全 (RLock)
    - 可重置 (测试隔离)
"""
from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional

logger = logging.getLogger(__name__)


class GoalReplayError(Exception):
    """目标回放操作异常"""


@dataclass
class GoalStep:
    """目标单步记录

    Attributes:
        step_index:    步骤序号 (从 1 开始)
        action:        执行动作 (dict)
        feedback:      行动反馈 (dict, None=无)
        analysis:      反馈分析 (dict, None=无)
        observed_state: 动作前观察到的状态 (dict)
        result:        动作结果状态 (EmbodiedStatus 值)
        timestamp:     记录时间
    """
    step_index: int = 0
    action: Dict[str, Any] = field(default_factory=dict)
    feedback: Optional[Dict[str, Any]] = None
    analysis: Optional[Dict[str, Any]] = None
    observed_state: Optional[Dict[str, Any]] = None
    result: str = ""
    timestamp: float = field(default_factory=lambda: 0.0)

    @property
    def is_failure(self) -> bool:
        """本步是否为失败 (feedback.result == failure)"""
        return bool(self.feedback and self.feedback.get("result") == "failure")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_index": self.step_index,
            "action": self.action,
            "feedback": self.feedback,
            "analysis": self.analysis,
            "observed_state": self.observed_state,
            "result": self.result,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "GoalStep":
        return cls(
            step_index=int(d.get("step_index", 0)),
            action=dict(d.get("action", {}) or {}),
            feedback=d.get("feedback"),
            analysis=d.get("analysis"),
            observed_state=d.get("observed_state"),
            result=d.get("result", ""),
            timestamp=float(d.get("timestamp", 0.0)),
        )


@dataclass
class GoalTrace:
    """完整目标轨迹 (Goal Replay 数据源)

    Attributes:
        trace_id:      轨迹唯一 ID
        goal_id:       目标 ID
        goal:          目标快照 (dict)
        plan:          计划动作序列 (List[Dict])
        steps:         执行步骤 (GoalStep 列表)
        event_timeline: 目标期间事件时间线 (List[Dict])
        final_state:   最终环境状态 (dict, None=无)
        final_status:  最终状态 (EmbodiedStatus 值)
        success:       是否成功
        failures:      失败计数
        iterations:    迭代次数
        environment:   执行环境名
        suggestions:   规划前置策略建议 (V4.3)
        started_at:    开始时间
        ended_at:      结束时间
        duration_ms:   总耗时 (毫秒)
    """
    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    goal_id: str = ""
    goal: Dict[str, Any] = field(default_factory=dict)
    plan: List[Dict[str, Any]] = field(default_factory=list)
    steps: List[GoalStep] = field(default_factory=list)
    event_timeline: List[Dict[str, Any]] = field(default_factory=list)
    final_state: Optional[Dict[str, Any]] = None
    final_status: str = ""
    success: bool = False
    failures: int = 0
    iterations: int = 0
    environment: str = ""
    suggestions: List[Dict[str, Any]] = field(default_factory=list)
    started_at: float = field(default_factory=lambda: 0.0)
    ended_at: float = field(default_factory=lambda: 0.0)
    duration_ms: float = 0.0

    @property
    def step_count(self) -> int:
        return len(self.steps)

    @property
    def failure_positions(self) -> List[int]:
        """失败位置: 失败步骤的序号列表"""
        return [s.step_index for s in self.steps if s.is_failure]

    # ── 场景分段 (V4.4 P1: 跨场景 Goal Replay) ────────────────────
    def scene_segments(self) -> List[Dict[str, Any]]:
        """事件时间线场景分段: 按环境切换切分 (跨场景回放)

        规则:
            - metadata.event == 'environment_switch' (RESET 事件) → 新段开始 (to 场景)
            - 其他事件按 metadata.environment / metadata.scene 分组
            - 无环境元数据 → 归入轨迹默认环境

        Returns:
            [{'scene': 'room', 'environment': 'mock', 'start_index': 0,
              'end_index': 3, 'event_count': 4}, ...]
        """
        default_env = self.environment or ""
        segments: List[Dict[str, Any]] = []
        current_scene: Optional[str] = None
        current_env: str = default_env
        start = 0
        count = 0
        for i, ev in enumerate(self.event_timeline):
            md = ev.get("metadata") or {}
            if md.get("event") == "environment_switch":
                new_scene = str(md.get("to") or current_scene or default_env)
                if current_scene is not None:
                    segments.append({
                        "scene": current_scene,
                        "environment": current_env,
                        "start_index": start,
                        "end_index": i - 1,
                        "event_count": count,
                    })
                current_scene = new_scene
                current_env = str(md.get("to") or default_env)
                start = i
                count = 1
                continue
            env = md.get("environment") or md.get("scene") or default_env
            if current_scene is None:
                current_scene = env
                current_env = env
                count = 1
            elif env != current_scene:
                segments.append({
                    "scene": current_scene,
                    "environment": current_env,
                    "start_index": start,
                    "end_index": i - 1,
                    "event_count": count,
                })
                current_scene = env
                current_env = env
                start = i
                count = 1
            else:
                count += 1
        if current_scene is not None:
            segments.append({
                "scene": current_scene,
                "environment": current_env,
                "start_index": start,
                "end_index": len(self.event_timeline) - 1,
                "event_count": count,
            })
        return segments

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "goal_id": self.goal_id,
            "goal": self.goal,
            "plan": self.plan,
            "steps": [s.to_dict() for s in self.steps],
            "event_timeline": self.event_timeline,
            "final_state": self.final_state,
            "final_status": self.final_status,
            "success": self.success,
            "failures": self.failures,
            "iterations": self.iterations,
            "environment": self.environment,
            "suggestions": self.suggestions,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "duration_ms": round(self.duration_ms, 2),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "GoalTrace":
        return cls(
            trace_id=d.get("trace_id", uuid.uuid4().hex),
            goal_id=d.get("goal_id", ""),
            goal=dict(d.get("goal", {}) or {}),
            plan=list(d.get("plan", []) or []),
            steps=[GoalStep.from_dict(s) for s in (d.get("steps") or [])],
            event_timeline=list(d.get("event_timeline", []) or []),
            final_state=d.get("final_state"),
            final_status=d.get("final_status", ""),
            success=bool(d.get("success", False)),
            failures=int(d.get("failures", 0)),
            iterations=int(d.get("iterations", 0)),
            environment=d.get("environment", ""),
            suggestions=list(d.get("suggestions", []) or []),
            started_at=float(d.get("started_at", 0.0)),
            ended_at=float(d.get("ended_at", 0.0)),
            duration_ms=float(d.get("duration_ms", 0.0)),
        )

    # ── 回放输出 (Step N: Observe → Action → Feedback) ────────────
    def replay_dict(self) -> Dict[str, Any]:
        """结构化回放: 逐步 Observe / Action / Feedback + 场景分段"""
        steps = []
        for s in self.steps:
            steps.append({
                "step": s.step_index,
                "observe": s.observed_state,
                "action": s.action,
                "feedback": s.feedback,
                "analysis": s.analysis,
                "result": s.result,
            })
        return {
            "goal_id": self.goal_id,
            "environment": self.environment,
            "steps": steps,
            "scene_segments": self.scene_segments(),
            "final_status": self.final_status,
            "success": self.success,
            "final_state": self.final_state,
        }

    def replay_text(self) -> str:
        """文本回放 (Step 1: Observe / Action / Feedback)"""
        lines = [f"目标回放: {self.goal_id} (环境: {self.environment})"]
        lines.append(f"描述: {(self.goal or {}).get('description', '')}")
        for s in self.steps:
            lines.append(f"Step {s.step_index}:")
            obj_count = len((s.observed_state or {}).get("objects", [])) if s.observed_state else 0
            lines.append(
                f"  Observe: objects={obj_count} "
                f"location={(s.observed_state or {}).get('location', {})}"
            )
            a = s.action or {}
            lines.append(
                f"  Action: {a.get('action_type', '')} target={a.get('target', '')} "
                f"parameters={a.get('parameters', {})}"
            )
            fb = s.feedback or {}
            lines.append(f"  Feedback: {fb.get('result', '')} change={fb.get('environment_change', {})}")
        lines.append(f"最终结果: {self.final_status} success={self.success} "
                     f"步骤数={self.step_count} 失败={self.failures} 耗时={self.duration_ms:.1f}ms")
        return "\n".join(lines)

    def export_text(self) -> str:
        """结构化文本导出 (验收 / Debug / 复盘)"""
        lines = [
            "=" * 60,
            "YHLZ Embodied Goal Trace Export",
            "=" * 60,
            f"trace_id: {self.trace_id}",
            f"goal_id: {self.goal_id}",
            f"environment: {self.environment}",
            f"goal: {json.dumps(self.goal, ensure_ascii=False)}",
            f"plan: {json.dumps(self.plan, ensure_ascii=False)}",
            f"suggestions: {json.dumps(self.suggestions, ensure_ascii=False)}",
            f"steps: {self.step_count}",
            f"failures: {self.failures} (positions={self.failure_positions})",
            f"final_status: {self.final_status}",
            f"success: {self.success}",
            f"duration_ms: {self.duration_ms:.2f}",
            f"started_at: {self.started_at}",
            f"ended_at: {self.ended_at}",
            "-" * 60,
        ]
        for s in self.steps:
            lines.append(f"Step {s.step_index}:")
            a = s.action or {}
            fb = s.feedback or {}
            an = s.analysis or {}
            lines.append(f"  action: {json.dumps(a, ensure_ascii=False)}")
            lines.append(f"  feedback: {json.dumps(fb, ensure_ascii=False)}")
            lines.append(f"  analysis: {json.dumps(an, ensure_ascii=False)}")
        lines.append("-" * 60)
        lines.append(f"scene_segments: {json.dumps(self.scene_segments(), ensure_ascii=False)}")
        lines.append(f"event_timeline: {json.dumps(self.event_timeline, ensure_ascii=False)}")
        lines.append(f"final_state: {json.dumps(self.final_state, ensure_ascii=False)}")
        lines.append("=" * 60)
        return "\n".join(lines)


class GoalTraceStore:
    """目标轨迹存储 (按 goal_id 索引, 保留最近轨迹)

    用法:
        store = GoalTraceStore(max_traces=100)
        store.add(trace)
        trace = store.get("goal-xxx")
        store.save_to_file(path) / store.load_from_file(path)
    """

    def __init__(self, max_traces: int = 100):
        if max_traces <= 0:
            raise GoalReplayError(f"max_traces 必须 > 0, 当前: {max_traces}")
        self._lock = threading.RLock()
        self._traces: Deque[GoalTrace] = deque(maxlen=max_traces)
        self._by_goal: Dict[str, GoalTrace] = {}
        self._max_traces = max_traces

    # ── 记录 ──────────────────────────────────────────────────────
    def add(self, trace: GoalTrace) -> str:
        """保存轨迹, 返回 trace_id"""
        if trace is None:
            raise GoalReplayError("轨迹不能为 None")
        with self._lock:
            # 容量已满: 先清理最旧轨迹的 goal_id 索引 (与 deque 淘汰同步)
            if len(self._traces) >= self._max_traces and self._traces:
                oldest = self._traces[0]
                if self._by_goal.get(oldest.goal_id) is oldest:
                    del self._by_goal[oldest.goal_id]
            self._traces.append(trace)
            self._by_goal[trace.goal_id] = trace
        return trace.trace_id

    # ── 查询 ──────────────────────────────────────────────────────
    def get(self, goal_id: str) -> Optional[GoalTrace]:
        """按 goal_id 查询最近轨迹 (None=未找到)"""
        with self._lock:
            return self._by_goal.get(goal_id)

    def get_by_trace_id(self, trace_id: str) -> Optional[GoalTrace]:
        with self._lock:
            for t in reversed(self._traces):
                if t.trace_id == trace_id:
                    return t
        return None

    def all(self, limit: int = 100) -> List[GoalTrace]:
        with self._lock:
            traces = list(self._traces)
        return traces[-limit:] if limit > 0 else traces

    def count(self) -> int:
        with self._lock:
            return len(self._traces)

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            traces = list(self._traces)
        success = sum(1 for t in traces if t.success)
        return {
            "total": len(traces),
            "success_count": success,
            "success_rate": round(success / len(traces), 4) if traces else 0.0,
            "total_steps": sum(t.step_count for t in traces),
            "total_failures": sum(t.failures for t in traces),
        }

    # ── 持久化 (JSONL) ────────────────────────────────────────────
    def save_to_file(self, path: str) -> int:
        with self._lock:
            traces = list(self._traces)
        with open(path, "w", encoding="utf-8") as f:
            for t in traces:
                f.write(json.dumps(t.to_dict(), ensure_ascii=False) + "\n")
        logger.info(f"[GoalTrace] 已保存到 {path}, 共 {len(traces)} 条")
        return len(traces)

    def load_from_file(self, path: str) -> int:
        if not os.path.isfile(path):
            return 0
        loaded = 0
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    trace = GoalTrace.from_dict(json.loads(line))
                    self.add(trace)
                    loaded += 1
                except (json.JSONDecodeError, TypeError, GoalReplayError) as e:
                    logger.warning(f"[GoalTrace] 跳过坏行: {e}")
        logger.info(f"[GoalTrace] 已从 {path} 加载 {loaded} 条")
        return loaded

    # ── 生命周期 ──────────────────────────────────────────────────
    def clear(self) -> int:
        with self._lock:
            n = len(self._traces)
            self._traces.clear()
            self._by_goal.clear()
        logger.info(f"[GoalTrace] 轨迹已清空, 清理 {n} 条")
        return n

    @property
    def max_traces(self) -> int:
        with self._lock:
            return self._max_traces


__all__ = ["GoalStep", "GoalTrace", "GoalTraceStore", "GoalReplayError"]
