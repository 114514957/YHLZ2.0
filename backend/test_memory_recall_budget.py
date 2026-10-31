"""Recall admission/lock contracts; synthetic temporary stores, no model."""
import json
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from backend.target_memory import TargetMemoryService, L2Item

class RecallBudgetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.mem = TargetMemoryService(db_path=Path(self.tmp.name)/'m.db', max_recall_results=3)
        self.mem.store_item(L2Item('a','L2','fact',5,'budget marker','ref','budget',created_at=1))
        self.row = {'id':'a','summary':'budget marker'}

    def test_limit_is_hard_cap_even_if_projection_overreturns(self):
        with patch.object(self.mem,'_recall_via_kw',return_value=[self.row]*12):
            self.assertEqual(len(self.mem.recall('budget',limit=999)),3)

    def test_optional_stage_overreturn_is_capped(self):
        with patch.object(self.mem,'_spread_hits',return_value=[self.row]*12):
            self.assertEqual(len(self.mem.recall('no-match',limit=999)),3)

    def test_expired_budget_keeps_literal_hit_but_skips_models_and_spread(self):
        self.mem._semantic_enabled = True
        self.mem.recall_budget_ms = 1
        def slow(*args):
            time.sleep(.015)
            return [self.row]
        with patch.object(self.mem,'_recall_via_kw',side_effect=slow), \
             patch.object(self.mem,'_spread_hits',side_effect=AssertionError('spread')), \
             patch.object(self.mem,'_semantic_hits',side_effect=AssertionError('semantic')):
            self.assertEqual(self.mem.recall('budget')[0]['id'],'a')
        timing = self.mem._last_recall_timing
        self.assertTrue(timing['budget_exceeded'])
        self.assertEqual(timing['semantic_skipped'],'budget')
        self.assertEqual(timing['budget_kind'],'optional-stage-admission')
        self.assertNotIn('budget marker',json.dumps(timing))

    def test_disabled_semantic_does_not_call_model(self):
        self.mem._semantic_enabled = False
        with patch.object(self.mem,'_semantic_hits',side_effect=AssertionError('model')):
            self.assertEqual(self.mem.recall('budget',spread=False)[0]['id'],'a')
        self.assertEqual(self.mem._last_recall_timing['semantic_skipped'],'disabled')

    def test_keyword_exception_degrades_to_authoritative_sql(self):
        with patch.object(self.mem,'_recall_via_kw',side_effect=sqlite3.OperationalError('secret')):
            self.assertEqual(self.mem.recall('budget',spread=False)[0]['id'],'a')
        self.assertEqual(self.mem._last_recall_timing['keyword_error'],'OperationalError')
        self.assertNotIn('secret',json.dumps(self.mem._last_recall_timing))

    def test_exclusive_lock_returns_without_five_second_wait(self):
        con = sqlite3.connect(str(self.mem.db_path))
        try:
            con.execute('PRAGMA journal_mode=DELETE')
            con.execute('BEGIN EXCLUSIVE')
            started = time.perf_counter()
            self.assertEqual(self.mem.recall('budget',spread=False),[])
            self.assertLess(time.perf_counter()-started,1.5)
        finally:
            con.rollback()
            con.close()

    def test_keyword_lock_falls_back_to_sql_without_default_wait(self):
        con = sqlite3.connect(str(self.mem._kw.db_path))
        try:
            con.execute('PRAGMA journal_mode=DELETE')
            con.execute('BEGIN EXCLUSIVE')
            started = time.perf_counter()
            self.assertEqual(self.mem.recall('budget',spread=False)[0]['id'],'a')
            self.assertLess(time.perf_counter()-started,1.5)
        finally:
            con.rollback()
            con.close()

    def test_invalid_budget_is_rejected(self):
        for value in (0,-1,float('nan'),float('inf')):
            with self.assertRaises(ValueError):
                TargetMemoryService(db_path=Path(self.tmp.name)/'bad.db',recall_budget_ms=value)

class BackgroundResourceTests(unittest.IsolatedAsyncioTestCase):
    async def test_entity_graph_does_not_build_provider_during_training(self):
        from backend import entity_graph
        with patch.dict('os.environ',{'YHLZ_TRAINING_ACTIVE':'1','YHLZ_MEMORY_LLM_MODE':'local'}), \
             patch.object(entity_graph,'_local_llm',side_effect=AssertionError('provider')):
            self.assertEqual(await entity_graph.extract_triples('synthetic entity and relation'),[])

    async def test_skill_learning_does_not_call_main_llm_during_training(self):
        from backend.target_scheduler_tools import skill_learn
        from unittest.mock import AsyncMock
        llm = AsyncMock(side_effect=AssertionError('provider'))
        with patch.dict('os.environ',{'YHLZ_TRAINING_ACTIVE':'1','YHLZ_MEMORY_LLM_MODE':'local'}):
            await skill_learn('很好，记住这个方法',[{'ok':True,'name':'file_read'},{'ok':True,'name':'file_list'}],'done',llm)
        llm.assert_not_called()

class SessionBackgroundTests(unittest.IsolatedAsyncioTestCase):
    async def test_training_defers_reflection_review_and_group_extraction(self):
        from backend.target_entry import ConversationSession
        from unittest.mock import AsyncMock
        with tempfile.TemporaryDirectory() as td:
            llm=AsyncMock(side_effect=AssertionError('background model forbidden'))
            mem=TargetMemoryService(db_path=Path(td)/'memory.db')
            session=ConversationSession(memory=mem,llm_turn=llm,channel='console')
            session.history=[{'role':'user','content':'synthetic'}]*8
            with patch.dict('os.environ',{'YHLZ_TRAINING_ACTIVE':'1','YHLZ_MEMORY_LLM_MODE':'local'}):
                self.assertEqual((await session.reflect())['reason'],'resource-deferred')
                self.assertEqual((await session.review_once())['reason'],'resource-deferred')
                session.channel='qq_g123'
                self.assertEqual(await session._promote_group('synthetic','synthetic'),0)
            llm.assert_not_called()
            self.assertFalse(session._reviewing)

    async def test_completed_background_tasks_are_released_on_text_sessions(self):
        from backend.target_entry import ConversationSession
        from unittest.mock import AsyncMock
        import asyncio
        with tempfile.TemporaryDirectory() as td:
            session=ConversationSession(memory=TargetMemoryService(db_path=Path(td)/'memory.db'),llm_turn=AsyncMock())
            loop=asyncio.get_running_loop()
            done=[loop.create_future() for _ in range(1200)]
            for future in done: future.set_result(None)
            failed=loop.create_future(); failed.set_exception(ValueError('private exception'))
            pending=loop.create_future()
            session._summary_tasks=done+[failed,pending]
            session._prune_background_tasks()
            self.assertEqual(session._summary_tasks,[pending])
            self.assertEqual(session._background_error,'ValueError')
            pending.cancel()

    async def test_owner_reflection_uses_carrier_evidence(self):
        from backend.target_entry import ConversationSession
        from backend.memory_carriers import CarrierEvidence
        from types import SimpleNamespace
        from unittest.mock import AsyncMock
        with tempfile.TemporaryDirectory() as td:
            mem=TargetMemoryService(db_path=Path(td)/'memory.db')
            llm=AsyncMock(return_value={'content':'[{"text":"用户偏好先验证再保存事实"}]'})
            session=ConversationSession(memory=mem,llm_turn=llm,channel='console')
            session.history=[{'role':'user','content':'synthetic'}]*4
            with patch('backend.memory_resource_policy.load_memory_resource_policy',return_value=SimpleNamespace(llm_enabled=True)):
                result=await session.reflect()
            self.assertEqual(result['insights'],1)
            events=CarrierEvidence(mem.db_path).list()
            self.assertEqual(events[0]['carrier'],'memory')
            self.assertEqual(events[0]['state'],'committed')

    async def test_public_reflection_never_saves_private_insights(self):
        from backend.target_entry import ConversationSession
        from unittest.mock import AsyncMock
        with tempfile.TemporaryDirectory() as td:
            llm=AsyncMock(side_effect=AssertionError('private reflection'))
            session=ConversationSession(memory=TargetMemoryService(db_path=Path(td)/'m.db'),llm_turn=llm,channel='qq_g123')
            session.history=[{'role':'user','content':'synthetic'}]*8
            self.assertEqual((await session.reflect())['reason'],'public-channel')
            llm.assert_not_called()
