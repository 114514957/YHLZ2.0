"""Daemon-loop ownership of bounded background voice writeback tasks."""
from __future__ import annotations
import asyncio
from collections import deque

class VoiceTaskSupervisor:
    def __init__(self, *, timeout_s=60.0, capacity=4):
        self.timeout_s = timeout_s
        self.capacity = capacity
        self.tasks = set()
        self.records = deque(maxlen=64)
        self.closed = False
        self._running = set()
        self._foreground = 0
        self._idle = asyncio.Event()
        self._idle.set()

    def submit(self, coroutine, *, label="voice_writeback"):
        if self.closed or len(self.tasks) >= self.capacity:
            coroutine.close()
            self.records.append({"label": label, "status": "rejected"})
            return None
        started = False
        async def run():
            nonlocal started
            started = True
            status = "completed"
            try:
                async def execute():
                    await self._idle.wait()
                    self._running.add(asyncio.current_task())
                    try:
                        return await coroutine
                    finally:
                        self._running.discard(asyncio.current_task())
                result = await asyncio.wait_for(execute(), self.timeout_s)
                if isinstance(result, str):
                    status = result
            except asyncio.TimeoutError:
                status = "timeout"
            except asyncio.CancelledError:
                status = "cancelled"
                raise
            except Exception:
                status = "failed"
            finally:
                coroutine.close()
                self.records.append({"label": label, "status": status})
        task = asyncio.create_task(run())
        self.tasks.add(task)
        def finished(task):
            self.tasks.discard(task)
            if not started:
                coroutine.close()
                self.records.append({"label": label, "status": "cancelled"})
        task.add_done_callback(finished)
        return task

    def enter_foreground(self):
        self._foreground += 1
        self._idle.clear()
        for task in list(self._running):
            task.cancel()

    def leave_foreground(self):
        self._foreground = max(0, self._foreground - 1)
        if not self._foreground:
            self._idle.set()

    async def shutdown(self):
        self.closed = True
        tasks = list(self.tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    def snapshot(self):
        return {"pending": len(self.tasks), "closed": self.closed, "recent": list(self.records)}
