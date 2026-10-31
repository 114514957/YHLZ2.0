"""Retry, transaction and inference scheduling regressions using temporary data."""
import asyncio
from contextlib import closing
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from backend.target_entry import ConversationSession
from backend.target_memory import TargetMemoryService, L2Item
from backend.text_memory_inference_gate import inference_gate


class ReviewRetryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.memory = TargetMemoryService(db_path=Path(self.tmp.name)/'memory.db')
        self.memory._vec_upsert = Mock(); self.memory._sync_kw = Mock()
        self.session = object.__new__(ConversationSession)
        self.session.memory = self.memory
        self.session._reviewing = False
        self.session._turn_count = 6
        self.session._last_reviewed = 0
        self.session._review_retry_at = 0
        self.session._review_failures = 0
        self.session.channel = 'console'
        self.session.history = [{'role':'user','content':'合成记录：周五整理蓝色卡片'}]*4
        self.session.reflect = AsyncMock(return_value={'insights':0,'reason':'ok'})
        self.policy = SimpleNamespace(llm_enabled=True)
        self.patcher = patch('backend.memory_resource_policy.load_memory_resource_policy', return_value=self.policy)
        self.patcher.start(); self.addCleanup(self.patcher.stop)

    def extractor(self, *, result=None, status='validated_empty', error=None):
        fn = AsyncMock(side_effect=error, return_value=[] if result is None else result)
        hook = SimpleNamespace(candidates=fn, last_candidate_status=status)
        self.memory.set_llm_hooks(hook, None)
        return hook

    def candidate(self, name='one'):
        return L2Item(name, 'L2', 'fact', 6, '合成事实'+name, name, '合成', created_at=1)

    def count(self):
        with closing(sqlite3.connect(str(self.memory.db_path))) as con:
            return con.execute('SELECT count(*) FROM l2_items').fetchone()[0]

    async def test_invalid_empty_candidate_is_retryable_but_valid_empty_is_acknowledged(self):
        self.extractor(status='invalid_output')
        result = await self.session.review_once('auto')
        self.assertFalse(result['acknowledged']); self.assertEqual(self.session._last_reviewed, 0)
        self.assertEqual(result['candidate_status'], 'invalid_output')
        self.assertEqual(result['retry_after_s'], 5)
        self.extractor()
        self.assertEqual((await self.session.review_once('auto'))['reason'], 'retry-backoff')
        self.assertTrue((await self.session.review_once('manual'))['acknowledged'])
        self.assertEqual(self.session._last_reviewed, 6)
        self.assertEqual(self.session._review_retry_at, 0)

    async def test_missing_hook_and_provider_failure_are_observable(self):
        self.assertFalse((await self.session.review_once())['acknowledged'])
        self.assertEqual(self.memory.last_candidate_status, 'extractor_unavailable')
        self.extractor(error=RuntimeError('synthetic'))
        result = await self.session.review_once()
        self.assertEqual(result['candidate_status'], 'provider_error')
        self.assertFalse(result['acknowledged'])

    async def test_summary_backlog_prevents_acknowledgement(self):
        self.extractor(); self.memory._summary_pending = True
        result = await self.session.review_once()
        self.assertEqual(result['summary'], 'pending'); self.assertFalse(result['acknowledged'])

    async def test_new_turn_during_review_is_not_acknowledged(self):
        started, release = asyncio.Event(), asyncio.Event()
        async def extract(context):
            self.assertNotIn('新一轮', context['transcript'])
            started.set(); await release.wait(); return []
        self.memory.set_llm_hooks(SimpleNamespace(candidates=extract), None)
        task = asyncio.create_task(self.session.review_once())
        await started.wait()
        self.session._turn_count = 7
        self.session.history.append({'role':'user','content':'新一轮'})
        release.set(); result = await task
        self.assertTrue(result['acknowledged']); self.assertEqual(self.session._last_reviewed, 6)

    async def test_cancelled_review_releases_singleflight_without_checkpoint(self):
        started = asyncio.Event()
        async def extract(context):
            started.set(); await asyncio.Event().wait()
        self.memory.set_llm_hooks(SimpleNamespace(candidates=extract), None)
        task = asyncio.create_task(self.session.review_once()); await started.wait(); task.cancel()
        with self.assertRaises(asyncio.CancelledError): await task
        self.assertFalse(self.session._reviewing); self.assertEqual(self.session._last_reviewed, 0)

    async def test_reflection_failure_keeps_review_retryable(self):
        self.extractor(); self.session.reflect.return_value = {'insights':0,'reason':'save-failed'}
        self.assertFalse((await self.session.review_once())['acknowledged'])

    async def test_background_retry_delay_is_capped(self):
        self.extractor(status='invalid_output')
        self.session._review_failures = 1000
        self.assertEqual((await self.session.review_once())['retry_after_s'], 300)

    async def test_invalid_or_fallback_judge_does_not_commit_candidates(self):
        for verdict, state in [({'importance':6,'status':'active'}, 'provider_error_fallback'),
                               ({'importance':True,'status':'active'}, 'validated')]:
            judge = SimpleNamespace(adjudicate=AsyncMock(return_value=verdict), last_judge_status=state)
            self.memory.set_llm_hooks(None, judge)
            with self.assertRaises(ValueError): await self.memory.adjudicate_async([self.candidate()])
            self.assertEqual(self.count(), 0)
            self.assertEqual(self.memory.health()['adjudication_status'], 'unconfirmed')

    async def test_failure_of_second_judge_does_not_commit_first_item(self):
        judge = SimpleNamespace(adjudicate=AsyncMock(side_effect=[{'importance':6,'status':'active'}, TimeoutError()]))
        self.memory.set_llm_hooks(None, judge)
        with self.assertRaises(TimeoutError):
            await self.memory.adjudicate_async([self.candidate(), self.candidate('two')])
        self.assertEqual(self.count(), 0)

    async def test_no_writer_lock_is_held_while_second_judge_waits(self):
        started, release = asyncio.Event(), asyncio.Event(); calls = 0
        async def judge(item):
            nonlocal calls
            calls += 1
            if calls == 2:
                started.set(); await release.wait()
            return {'importance':6,'status':'active'}
        self.memory.set_llm_hooks(None, SimpleNamespace(adjudicate=judge))
        task = asyncio.create_task(self.memory.adjudicate_async([self.candidate(),self.candidate('two')]))
        try:
            await started.wait()
            with closing(sqlite3.connect(str(self.memory.db_path), timeout=0)) as con, con:
                con.execute('CREATE TABLE independent_writer (id INTEGER)')
        finally:
            release.set(); await task
        self.assertEqual(self.count(), 2)
        self.assertEqual(self.memory.last_adjudication_status, 'validated_committed')

    async def test_storage_failure_rolls_back_entire_batch(self):
        self.memory.set_llm_hooks(None, SimpleNamespace(adjudicate=AsyncMock(return_value={'importance':6,'status':'active'})))
        real_connect = sqlite3.connect
        class FailingConnection(sqlite3.Connection):
            def execute(self, query, *args, **kwargs):
                if query.startswith('INSERT INTO l2_fts'): raise sqlite3.OperationalError('synthetic disk failure')
                return super().execute(query, *args, **kwargs)
        def connect(*args, **kwargs):
            return real_connect(*args, factory=FailingConnection, **kwargs)
        with patch('backend.target_memory.sqlite3.connect', side_effect=connect):
            with self.assertRaises(sqlite3.OperationalError): await self.memory.adjudicate_async([self.candidate()])
        self.assertEqual(self.count(),0)
        self.assertEqual(self.memory.last_adjudication_status, 'storage_failed')

    def reflection_session(self, content):
        self.session.llm_turn = AsyncMock(return_value={'content':content})
        self.session.registry = SimpleNamespace(execute_openai_async=AsyncMock(return_value={'ok':True,'output':'已保存'}))
        return self.session

    async def test_reflection_preserves_decision_type_and_rejects_conflicting_json(self):
        session = self.reflection_session('[{"text":"合成项目决定周五整理卡片","kind":"decision"}]')
        result = await ConversationSession.reflect(session)
        self.assertEqual(result['insights'],1)
        session.registry.execute_openai_async.assert_awaited_once_with('memory_save',{'content':'合成项目决定周五整理卡片','kind':'decision'})
        session.llm_turn.return_value={'content':'[{"text":"合成项目决定周五整理卡片"}] [{"text":"另一份矛盾的项目记录"}]'}
        self.assertEqual((await ConversationSession.reflect(session))['reason'], 'bad-json')
        self.assertEqual(session.registry.execute_openai_async.await_count,1)

    async def test_reflection_rechecks_policy_after_waiting_for_inference_slot(self):
        session = self.reflection_session('[]'); gate = inference_gate()
        async with gate.slot():
            task = asyncio.create_task(ConversationSession.reflect(session))
            for _ in range(20):
                if gate.background_waiters: break
                await asyncio.sleep(0)
            self.assertEqual(gate.background_waiters,1)
            self.policy.llm_enabled = False
        self.assertEqual((await task)['reason'], 'resource-deferred')
        session.llm_turn.assert_not_awaited()

    async def test_reflection_cancel_releases_gate(self):
        session = self.reflection_session('[]'); started = asyncio.Event()
        async def model(*args):
            started.set(); await asyncio.Event().wait()
        session.llm_turn = model
        task = asyncio.create_task(ConversationSession.reflect(session)); await started.wait(); task.cancel()
        with self.assertRaises(asyncio.CancelledError): await task
        self.assertEqual(inference_gate().active,'')

    async def test_entity_extraction_rechecks_policy_after_queue(self):
        from backend import entity_graph
        gate = inference_gate(); llm = AsyncMock(return_value={'content':'[]'})
        async with gate.slot():
            task = asyncio.create_task(entity_graph.extract_triples('合成实体', llm))
            for _ in range(20):
                if gate.background_waiters: break
                await asyncio.sleep(0)
            self.assertEqual(gate.background_waiters, 1)
            self.policy.llm_enabled = False
        self.assertEqual(await task, []); llm.assert_not_awaited()

    async def test_skill_learning_rechecks_policy_without_marking_seen(self):
        from backend import target_scheduler_tools as tools
        gate = inference_gate(); llm = AsyncMock(return_value={'content':'{}'})
        uses = [{'name':'web_search','ok':True},{'name':'kb_add','ok':True}]
        with patch.object(tools, '_SKILL_SEEN', Path(self.tmp.name)/'seen.json'):
            async with gate.slot():
                task = asyncio.create_task(tools.skill_learn('合成任务',uses,'完成',llm))
                for _ in range(20):
                    if gate.background_waiters: break
                    await asyncio.sleep(0)
                self.assertEqual(gate.background_waiters,1)
                self.policy.llm_enabled = False
            self.assertEqual(await task,''); llm.assert_not_awaited()
            self.assertFalse(tools._SKILL_SEEN.exists())

    async def test_skill_failure_can_retry_and_concurrent_success_deduplicates(self):
        from backend import target_scheduler_tools as tools
        llm = AsyncMock(side_effect=[TimeoutError(), {'content':'{"name":"合成技能","trigger":"合成触发","steps":"合成步骤"}'}])
        uses = [{'name':'web_search','ok':True},{'name':'kb_add','ok':True}]
        with patch.object(tools, '_SKILL_SEEN', Path(self.tmp.name)/'seen.json'), \
             patch.object(tools, '_PROJECT_ROOT', Path(self.tmp.name)):
            self.assertEqual(await tools.skill_learn('合成任务',uses,'完成',llm),'')
            self.assertFalse(tools._SKILL_SEEN.exists())
            results = await asyncio.gather(*(tools.skill_learn('合成任务',uses,'完成',llm) for _ in range(2)))
            self.assertEqual(sum(bool(x) for x in results), 1)
            self.assertTrue(Path(next(x for x in results if x)).exists())
            self.assertEqual(llm.await_count, 2)

if __name__ == '__main__': unittest.main()
