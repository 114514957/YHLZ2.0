"""Bounded scheduling, timeout, cancellation and training-safe contracts."""
import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from backend.target_memory import TargetMemoryService
from backend.memory_summary_scheduler import MemorySummaryScheduler

class SchedulerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.mem=TargetMemoryService(db_path=Path(self.tmp.name)/'mem.db',window_turns=1,summary_batch_size=2)
        for i in range(10):self.mem.append_turn(role='user',text=str(i))
        self.mem.set_llm_hooks(SimpleNamespace(compress=AsyncMock(return_value=('summary',1))),None)
        self.clock=100.
        self.worker=MemorySummaryScheduler(self.mem,batches_per_wake=2,allowed=lambda:True,clock=lambda:self.clock)

    async def test_single_flight(self):
        started=asyncio.Event();release=asyncio.Event()
        async def compress(*a,**k): started.set();await release.wait();return ('summary',1)
        self.mem.set_llm_hooks(SimpleNamespace(compress=compress),None)
        first=self.worker.kick();await started.wait()
        for _ in range(100):self.assertIs(self.worker.kick(),first)
        release.set();await first
        self.assertEqual(self.worker.wakes,1)

    async def test_bounded_drain_and_next_wake(self):
        await self.worker.kick();self.assertEqual(len(self.mem._pending_dropped),5)
        await self.worker.kick();self.assertEqual(len(self.mem._pending_dropped),1)
        await self.worker.kick();self.assertEqual(len(self.mem._pending_dropped),0)
        self.assertIsNone(self.worker.kick());self.assertEqual(self.worker.batches,5)

    async def test_provider_failure_backs_off_without_discard(self):
        self.mem.set_llm_hooks(SimpleNamespace(compress=AsyncMock(side_effect=TimeoutError)),None)
        await self.worker.kick();self.assertEqual(len(self.mem._pending_dropped),9)
        self.assertIsNone(self.worker.kick());self.assertEqual(self.worker.failures,1)
        self.clock=102.;await self.worker.kick();self.assertEqual(self.worker.failures,2)
        self.assertEqual(self.worker.next_eligible,106.)

    async def test_success_resets_backoff(self):
        self.mem.set_llm_hooks(SimpleNamespace(compress=AsyncMock(side_effect=TimeoutError)),None)
        await self.worker.kick();self.clock=102.
        self.mem.set_llm_hooks(SimpleNamespace(compress=AsyncMock(return_value=('ok',1))),None)
        await self.worker.kick();self.assertEqual(self.worker.failures,0)

    async def test_timeout_releases_summary_and_retains_raw(self):
        async def compress(*a,**k):await asyncio.Event().wait()
        self.mem.set_llm_hooks(SimpleNamespace(compress=compress),None)
        self.worker.timeout_s=.01
        await self.worker.kick()
        self.assertEqual(self.worker.last_error,'TimeoutError')
        self.assertFalse(self.mem._summary_running)
        self.assertEqual(len(self.mem._pending_dropped),9)

    async def test_close_cancels_without_losing_backlog(self):
        started=asyncio.Event()
        async def compress(*a,**k):started.set();await asyncio.Event().wait()
        self.mem.set_llm_hooks(SimpleNamespace(compress=compress),None)
        self.worker.kick();await started.wait();await self.worker.close()
        self.assertFalse(self.mem._summary_running);self.assertEqual(len(self.mem._pending_dropped),9)

    async def test_disabled_does_not_spawn_task(self):
        self.worker.allowed=lambda:False
        self.assertIsNone(self.worker.kick());self.mem._extractor.compress.assert_not_awaited()

    async def test_training_marker_overrides_local_opt_in(self):
        worker=MemorySummaryScheduler(self.mem)
        with patch.dict('os.environ',{'YHLZ_MEMORY_LLM_MODE':'local','YHLZ_TRAINING_ACTIVE':'1'}):
            self.assertIsNone(worker.kick())
        self.mem._extractor.compress.assert_not_awaited()

    async def test_mid_wake_resource_pause_stops_next_batch(self):
        async def compress(*a,**k):self.worker.allowed=lambda:False;return ('ok',1)
        self.mem.set_llm_hooks(SimpleNamespace(compress=compress),None)
        await self.worker.kick();self.assertEqual(len(self.mem._pending_dropped),7)
        self.assertEqual(self.worker.batches,1)

    async def test_disk_failure_not_acknowledged_or_spin_retried(self):
        with patch.object(self.mem,'_save_l1',return_value=False):await self.worker.kick()
        self.assertEqual(len(self.mem._pending_dropped),9)
        self.assertEqual(self.worker.last_error,'l1_persist_failed')
        self.assertIsNone(self.worker.kick())

    async def test_idle_gate_defers_and_arms_retry(self):
        """A summary must not evict the prompt cache right after a turn."""
        idle={'s':0.0}
        worker=MemorySummaryScheduler(self.mem,batches_per_wake=2,allowed=lambda:True,
                                      clock=lambda:self.clock,
                                      idle_gate=lambda:idle['s'],min_idle_s=90)
        worker._armed=object()          # pretend a retry is already queued
        self.assertIsNone(worker.kick())
        self.assertEqual(worker.deferred_idle,1)
        self.mem._extractor.compress.assert_not_awaited()
        self.assertFalse(self.mem._summary_running)

        idle['s']=120.0
        first=worker.kick()
        self.assertIsNotNone(first)
        await first
        self.assertEqual(worker.wakes,1)
        self.assertEqual(worker.deferred_idle,1)

    async def test_idle_gate_absent_keeps_old_behaviour(self):
        worker=MemorySummaryScheduler(self.mem,batches_per_wake=1,allowed=lambda:True,
                                      clock=lambda:self.clock,min_idle_s=90)
        self.assertIsNotNone(worker.kick())   # no gate supplied -> no idle wait

if __name__=='__main__':unittest.main()
