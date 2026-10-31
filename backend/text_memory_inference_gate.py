"""One inference slot per event loop for cooperating text/memory callers.

Foreground waiters take precedence over queued background batches. An already
running request finishes normally: this does not assert server-side preemption,
coordinate other processes, or change any frozen voice path.
"""
from __future__ import annotations
import asyncio
from contextlib import asynccontextmanager


class TextMemoryInferenceGate:
    def __init__(self):
        self.condition = asyncio.Condition()
        self.active = ''
        self.foreground_waiters = 0
        self.background_waiters = 0
        self.foreground_runs = self.background_runs = 0

    @asynccontextmanager
    async def slot(self, *, background=False):
        acquired = False
        kind = 'background' if background else 'foreground'
        counter = kind + '_waiters'
        async with self.condition:
            setattr(self, counter, getattr(self, counter) + 1)
            try:
                await self.condition.wait_for(lambda: not self.active and
                    (not background or self.foreground_waiters == 0))
                self.active = kind
                acquired = True
                if background:
                    self.background_runs += 1
                else:
                    self.foreground_runs += 1
            finally:
                setattr(self, counter, getattr(self, counter) - 1)
                self.condition.notify_all()
        try:
            yield
        finally:
            if acquired:
                async with self.condition:
                    self.active = ''
                    self.condition.notify_all()

    def health(self):
        return {'scope': 'cooperating_text_memory_same_event_loop',
                'active': self.active, 'foreground_waiters': self.foreground_waiters,
                'background_waiters': self.background_waiters,
                'foreground_runs': self.foreground_runs, 'background_runs': self.background_runs,
                'server_preemption': False}


def inference_gate():
    # Store on the loop rather than WeakKeyDictionary: Condition may itself
    # retain a bound loop, defeating a weak-key global map's collection.
    loop = asyncio.get_running_loop()
    gate = getattr(loop, '_yhlz_text_memory_gate', None)
    if gate is None:
        gate = TextMemoryInferenceGate()
        setattr(loop, '_yhlz_text_memory_gate', gate)
    return gate
