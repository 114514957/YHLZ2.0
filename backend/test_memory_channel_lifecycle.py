"""Memory lifecycle regression tests: temporary databases, no live user memory."""
import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from backend.target_memory import TargetMemoryService
from backend.target_memory_llm import MemoryLLMService


class MemoryLifecycleTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "mem.db"
        self.mem = TargetMemoryService(db_path=self.db, window_turns=2)

    def append(self, *texts):
        for t in texts:
            self.mem.append_turn(role="user", text=t)

    def hook(self, fn):
        self.mem.set_llm_hooks(SimpleNamespace(compress=fn), None)

    async def test_every_overflow_is_queued(self):
        self.append("one", "two", "three", "four", "five")
        self.assertEqual([t["text"] for t in self.mem._pending_dropped],
                         ["one", "two", "three"])

    async def test_missing_provider_does_not_acknowledge(self):
        self.append("one", "two", "three")
        await self.mem.process_summary()
        self.assertTrue(self.mem._summary_pending)
        self.assertEqual(self.mem.health()["summary_backlog"], 1)

    async def test_queue_survives_restart(self):
        self.append("one", "two", "three", "four")
        restored = TargetMemoryService(db_path=self.db, window_turns=2)
        self.assertEqual(restored._pending_dropped, self.mem._pending_dropped)
        self.assertTrue(restored._summary_pending)

    async def test_new_turn_during_compression_is_not_erased(self):
        started, release = asyncio.Event(), asyncio.Event()
        async def compress(turns, prev=""):
            started.set()
            await release.wait()
            return "saved one", 1
        self.hook(compress)
        self.append("one", "two", "three")
        task = asyncio.create_task(self.mem.process_summary())
        await started.wait()
        self.append("four")
        release.set()
        await task
        self.assertEqual(self.mem._pending_dropped, [{"role": "user", "text": "two"}])
        self.assertTrue(self.mem._summary_pending)

    async def test_concurrent_compress_is_single_flight(self):
        started, release = asyncio.Event(), asyncio.Event()
        calls = []
        async def compress(turns, prev=""):
            calls.append(turns)
            started.set()
            await release.wait()
            return "saved", 1
        self.hook(compress)
        self.append("one", "two", "three")
        task = asyncio.create_task(self.mem.process_summary())
        await started.wait()
        await self.mem.process_summary()
        release.set()
        await task
        self.assertEqual(len(calls), 1)

    async def test_provider_failure_is_retryable(self):
        self.hook(AsyncMock(side_effect=RuntimeError("synthetic failure")))
        self.append("one", "two", "three")
        await self.mem.process_summary()
        self.assertEqual(self.mem.health()["summary_failures"], 1)
        self.assertTrue(self.mem._summary_pending)
        self.hook(AsyncMock(return_value=("saved", 1)))
        await self.mem.process_summary()
        self.assertFalse(self.mem._summary_pending)

    async def test_cancellation_preserves_pending(self):
        started = asyncio.Event()
        async def compress(turns, prev=""):
            started.set()
            await asyncio.Event().wait()
        self.hook(compress)
        self.append("one", "two", "three")
        task = asyncio.create_task(self.mem.process_summary())
        await started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(self.mem._summary_pending)
        self.assertFalse(self.mem._summary_running)

    async def test_empty_summary_is_not_success(self):
        self.hook(AsyncMock(return_value=("  ", 1)))
        self.append("one", "two", "three")
        await self.mem.process_summary()
        self.assertTrue(self.mem._summary_pending)

    async def test_legacy_compressor_signature_supported(self):
        async def compress(turns):
            return "legacy saved", 1
        self.hook(compress)
        self.append("one", "two", "three")
        await self.mem.process_summary()
        self.assertEqual(self.mem._summary, "legacy saved")
        self.assertFalse(self.mem._summary_pending)

    async def test_internal_type_error_does_not_call_twice(self):
        fn = AsyncMock(side_effect=TypeError("provider bug"))
        self.hook(fn)
        self.append("one", "two", "three")
        await self.mem.process_summary()
        self.assertEqual(fn.call_count, 1)
        self.assertTrue(self.mem._summary_pending)

    async def test_bounded_batches_keep_remaining_work(self):
        self.mem.summary_batch_size = 2
        self.append("one", "two", "three", "four", "five")
        fn = AsyncMock(return_value=("saved", 1))
        self.hook(fn)
        await self.mem.process_summary()
        self.assertEqual(len(fn.call_args.args[0]), 2)
        self.assertEqual(self.mem.health()["summary_backlog"], 1)
        await self.mem.process_summary()
        self.assertEqual(self.mem._summary_version, 2)
        self.assertFalse(self.mem._summary_pending)

    async def test_scopes_share_db_but_not_short_memory(self):
        a = TargetMemoryService(db_path=self.db, l1_scope="console")
        b = TargetMemoryService(db_path=self.db, l1_scope="qq_p42")
        a.append_turn(role="user", text="synthetic console-only context")
        c = TargetMemoryService(db_path=self.db, l1_scope="qq_p42")
        self.assertEqual(a.db_path, b.db_path)
        self.assertNotEqual(a._l1_path(), b._l1_path())
        self.assertFalse(c._turns)

    async def test_scopes_are_path_safe_and_do_not_collide(self):
        a = TargetMemoryService(db_path=self.db, l1_scope="../a/b")
        b = TargetMemoryService(db_path=self.db, l1_scope=".._a_b")
        self.assertEqual(a._l1_path().parent, self.db.parent)
        self.assertNotEqual(a._l1_path(), b._l1_path())

    async def test_scope_does_not_import_legacy_shared_cache(self):
        self.append("synthetic private context")
        scoped = TargetMemoryService(db_path=self.db, l1_scope="console")
        self.assertFalse(scoped._turns)
        self.assertTrue(self.mem._l1_path().exists())

    async def test_malformed_cache_fails_closed(self):
        for payload in [[], {"version": "invalid"}, {"turns": [1, {}, {"role": "system", "text": "bad"}]}]:
            self.mem._l1_path().write_text(json.dumps(payload), encoding="utf-8")
            restored = TargetMemoryService(db_path=self.db)
            self.assertFalse(restored._turns)

    async def test_save_error_is_observable_and_does_not_discard(self):
        with patch.object(Path, "replace", side_effect=PermissionError):
            self.append("one", "two", "three")
        self.assertEqual(self.mem.health()["l1_save_error"], "PermissionError")
        self.assertTrue(self.mem._summary_pending)
        self.assertFalse(list(self.db.parent.glob("*.tmp")))

    async def test_history_reload_does_not_duplicate_backlog(self):
        history = [{"role": "user", "content": str(i)} for i in range(6)]
        self.mem.restore_history(history)
        before = list(self.mem._pending_dropped)
        self.mem.restore_history(history)
        self.assertEqual(self.mem._pending_dropped, before)
        self.assertEqual(len(before), 4)

    async def test_matching_history_preserves_compressed_summary(self):
        history = [{"role": "user", "content": str(i)} for i in range(4)]
        self.mem.restore_history(history)
        self.hook(AsyncMock(return_value=("saved history", 1)))
        await self.mem.process_summary()
        self.mem.restore_history(history)
        self.assertEqual(self.mem._summary, "saved history")
        self.assertFalse(self.mem._summary_pending)

    async def test_identical_tail_different_archive_does_not_reuse_summary(self):
        first = [{"role": "user", "content": x} for x in ["private old", "same", "tail"]]
        second = [{"role": "user", "content": x} for x in ["different old", "same", "tail"]]
        self.mem.restore_history(first)
        self.hook(AsyncMock(return_value=("first summary", 1)))
        await self.mem.process_summary()
        self.mem.restore_history(second)
        self.assertEqual(self.mem._summary, "")
        self.assertEqual(self.mem._pending_dropped[0]["text"], "different old")

    async def test_history_digest_survives_restart_and_append(self):
        self.append("one", "two", "three")
        self.hook(AsyncMock(return_value=("saved one", 1)))
        await self.mem.process_summary()
        restored = TargetMemoryService(db_path=self.db, window_turns=2)
        restored.restore_history([{"role": "user", "content": x} for x in ["one", "two", "three"]])
        self.assertEqual(restored._summary, "saved one")
        self.assertFalse(restored._summary_pending)

    async def test_archive_binding_is_invalidated_by_new_messages(self):
        self.append("a", "b", "c")
        history=[{"role":"user","content":x} for x in ["b","c"]]
        self.mem.bind_archive(history)
        self.assertTrue(self.mem._archive_digest)
        self.append("d")
        self.assertFalse(self.mem._archive_digest)
        self.mem.restore_history(history)
        self.assertEqual([t["text"] for t in self.mem._turns],["b","c"])
        self.assertFalse(self.mem._pending_dropped)

    async def test_candidate_cannot_promote_or_spoof_source(self):
        fn = AsyncMock(return_value=[{"summary": "synthetic claim", "importance": 99,
                                     "tier": "L3", "source": "owner", "protected": 1}])
        self.mem.set_llm_hooks(SimpleNamespace(candidates=fn), None)
        items = await self.mem.submit_candidates(text="test", transcript="test",
                                                 source="群聊", evidence_ref="qq:test")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].tier, "L2")
        self.assertEqual(items[0].source, "群聊")
        self.assertEqual(items[0].protected, 0)
        self.assertEqual(items[0].importance, 10)
        self.assertEqual(self.mem.health()["l2_items"], 0)  # not approved/stored yet

    async def test_malformed_candidates_are_ignored(self):
        fn = AsyncMock(return_value=[None, "bad", {"summary": "bad", "importance": []},
                                     {"summary": []}, {"summary": " "}, {"summary": "good"}])
        self.mem.set_llm_hooks(SimpleNamespace(candidates=fn), None)
        items = await self.mem.submit_candidates(text="test", transcript="test")
        self.assertEqual([x.summary for x in items], ["good"])

    async def test_llm_empty_result_does_not_pretend_old_summary_is_new(self):
        svc = MemoryLLMService(None, local=object())
        with patch.object(svc, "_chat_msgs", AsyncMock(return_value="")):
            with self.assertRaises(RuntimeError):
                await svc.compress([{"role": "user", "text": "new"}], prev="old")

    async def test_llm_transport_failure_not_acknowledged(self):
        svc = MemoryLLMService(None, local=object())
        with patch.object(svc, "_chat_msgs", AsyncMock(side_effect=RuntimeError)):
            with self.assertRaises(RuntimeError):
                await svc.compress([{"role": "user", "text": "new"}], prev="old")

    async def test_window_configuration_is_validated(self):
        with self.assertRaises(ValueError):
            TargetMemoryService(db_path=self.db, window_turns=0)


if __name__ == "__main__":
    unittest.main()
