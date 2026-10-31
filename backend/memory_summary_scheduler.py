"""Single-flight bounded L1 draining. Never starts a model or an idle timer.

A wake drains at most four batches. Failure backs off across subsequent wakes;
the pending queue is durable, not discarded. This is an event-driven supervisor,
not a promise of autonomous processing while the owner has disabled models.

Idle gating (2026-10-22): the local model shares one llama slot with the
conversation, so compressing right after a turn would evict the prompt cache we
just warmed. Callers pass ``idle_gate`` (seconds since the last turn) and
``min_idle_s``; a wake that arrives too early arms a one-shot retry instead of
running. The scheduler still owns no timer of its own — ``arm()`` borrows the
caller's loop.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Callable

from backend.memory_resource_policy import load_memory_resource_policy


def _model_allowed() -> bool:
    policy = load_memory_resource_policy()
    return bool(policy.llm_enabled or policy.summary_enabled)


class MemorySummaryScheduler:
    def __init__(self, service: Any, *, batches_per_wake: int = 4,
                 timeout_s: float = 45, clock: Callable = time.monotonic,
                 allowed: Callable | None = None,
                 idle_gate: Callable | None = None,
                 min_idle_s: float = 0.0):
        if batches_per_wake < 1 or timeout_s <= 0:
            raise ValueError("positive scheduler bounds required")
        self.service = service
        self.batches_per_wake = min(int(batches_per_wake), 16)
        self.timeout_s = float(timeout_s)
        self.clock = clock
        self.allowed = allowed or _model_allowed
        self.idle_gate = idle_gate
        self.min_idle_s = max(0.0, float(min_idle_s))
        self.task = None
        self.failures = 0
        self.next_eligible = 0.0
        self.wakes = self.deferred = self.deferred_idle = self.batches = 0
        self.last_error = ""
        self._armed = None

    def kick(self):
        if self.task is not None and not self.task.done():
            return self.task
        if not self.service._pending_dropped or self.clock() < self.next_eligible:
            return None
        if self.idle_gate is not None and self.min_idle_s > 0:
            try:
                idle = float(self.idle_gate())
            except Exception:
                idle = 0.0
            if idle < self.min_idle_s:
                self.deferred_idle += 1
                self.arm()
                return None
        if not self.allowed() or getattr(self.service, "_l1_read_blocked", False):
            self.deferred += 1
            return None
        self.task = asyncio.get_running_loop().create_task(self._run())
        self.wakes += 1
        return self.task

    def arm(self, *, delay_s: float | None = None) -> None:
        """Retry once after the idle window; borrows the caller's loop."""
        if self._armed is not None:
            return
        delay = self.min_idle_s if delay_s is None else float(delay_s)
        if delay <= 0:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._armed = loop.call_later(delay, self._on_armed)

    def _on_armed(self) -> None:
        self._armed = None
        try:
            self.kick()
        except Exception as exc:  # pragma: no cover - defensive
            self.last_error = type(exc).__name__

    def _failed(self, error: str):
        self.failures += 1
        self.last_error = error
        self.next_eligible = self.clock() + min(300, 2 ** min(self.failures, 9))

    async def _run(self):
        try:
            for _ in range(self.batches_per_wake):
                if not self.allowed():
                    self.deferred += 1
                    return
                before = len(self.service._pending_dropped)
                if not before:
                    return
                await asyncio.wait_for(self.service.process_summary(), self.timeout_s)
                after = len(self.service._pending_dropped)
                if after >= before:
                    self._failed(self.service._summary_error or "no_progress")
                    return
                self.batches += 1
                self.failures = 0
                self.last_error = ""
                self.next_eligible = 0.0
        except asyncio.CancelledError:
            self.last_error = "CancelledError"
            raise
        except Exception as exc:
            self._failed(type(exc).__name__)

    async def close(self):
        if self.task is not None and not self.task.done():
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass

    def health(self):
        return {"running": bool(self.task is not None and not self.task.done()),
                "wakes": self.wakes, "batches": self.batches, "deferred": self.deferred,
                "deferred_idle": self.deferred_idle, "min_idle_s": self.min_idle_s,
                "failures": self.failures, "last_error": self.last_error,
                "backoff_remaining_s": max(0.0, self.next_eligible - self.clock()),
                "batches_per_wake": self.batches_per_wake,
                "armed": self._armed is not None,
                "background_idle_timer": False}
