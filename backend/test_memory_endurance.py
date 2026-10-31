"""Fault-injection contracts in temporary stores, no live microphones/models."""
import asyncio
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from backend.target_memory import TargetMemoryService, L2Item
from backend.memory_resource_policy import MemoryWorkDeferred, semantic_model_allowed
from backend import vector_memory as vm


class EnduranceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.db=self.root/'memory.db'
        self.mem=TargetMemoryService(db_path=self.db,window_turns=3,l1_scope='console')

    def append(self, count):
        for i in range(count):self.mem.append_turn(role='user',text='synthetic-'+str(i))

    async def test_corrupt_pending_bytes_never_overwritten_by_empty_queue(self):
        for payload in [b'{broken',b'[]',b'{"scope":"console","pending":[null]}']:
            self.mem._l1_path().write_bytes(payload)
            restored=TargetMemoryService(db_path=self.db,window_turns=3,l1_scope='console')
            restored.append_turn(role='user',text='new fact')
            self.assertEqual(restored._l1_path().read_bytes(),payload)
            h=restored.health();self.assertTrue(h['l1_read_blocked']);self.assertTrue(h['l1_load_error'])
            self.assertEqual(h['l1_save_error'],'blocked_by_l1_load_error')

    async def test_foreign_scope_snapshot_fails_closed(self):
        payload=json.dumps({'scope':'qq_p100000','turns':[],'pending':[]}).encode()
        self.mem._l1_path().write_bytes(payload)
        restored=TargetMemoryService(db_path=self.db,l1_scope='console')
        restored.append_turn(role='user',text='do not erase foreign cache')
        self.assertEqual(restored._l1_path().read_bytes(),payload)

    async def test_1200_turn_restart_preserves_all_pending_without_model(self):
        self.append(1200)
        restarted=TargetMemoryService(db_path=self.db,window_turns=3,l1_scope='console')
        self.assertEqual(len(restarted._pending_dropped),1197)
        self.assertEqual(restarted._pending_dropped[0]['text'],'synthetic-0')
        self.assertEqual(restarted._pending_dropped[-1]['text'],'synthetic-1196')
        self.assertEqual(restarted._turns[-1]['text'],'synthetic-1199')

    async def test_provider_timeout_can_retry_after_restart(self):
        self.append(12)
        self.mem.set_llm_hooks(SimpleNamespace(compress=AsyncMock(side_effect=TimeoutError)),None)
        await self.mem.process_summary()
        restarted=TargetMemoryService(db_path=self.db,window_turns=3,l1_scope='console')
        self.assertEqual(len(restarted._pending_dropped),9)
        restarted.set_llm_hooks(SimpleNamespace(compress=AsyncMock(return_value=('recovered summary',1))),None)
        await restarted.process_summary();self.assertEqual(len(restarted._pending_dropped),0)

    async def test_failed_atomic_replace_keeps_previous_valid_disk_snapshot(self):
        self.append(8);before=self.mem._l1_path().read_bytes()
        with patch.object(Path,'replace',side_effect=PermissionError('readonly')):
            self.mem.append_turn(role='user',text='unsaved-but-visible')
        self.assertEqual(self.mem._l1_path().read_bytes(),before)
        self.assertEqual(self.mem.health()['l1_save_error'],'PermissionError')
        self.assertEqual(self.mem._turns[-1]['text'],'unsaved-but-visible')
        self.assertTrue(self.mem._save_l1())
        restarted=TargetMemoryService(db_path=self.db,window_turns=3,l1_scope='console')
        self.assertEqual(restarted._turns[-1]['text'],'unsaved-but-visible')

    async def test_multi_channel_shared_owner_l2_isolated_l1(self):
        qq=TargetMemoryService(db_path=self.db,window_turns=3,l1_scope='qq_p100000')
        self.append(8)
        for i in range(7):qq.append_turn(role='user',text='qq-'+str(i))
        desktop=TargetMemoryService(db_path=self.db,window_turns=3,l1_scope='console')
        qq_reload=TargetMemoryService(db_path=self.db,window_turns=3,l1_scope='qq_p100000')
        self.assertTrue(all(t['text'].startswith('synthetic') for t in desktop._pending_dropped))
        self.assertTrue(all(t['text'].startswith('qq-') for t in qq_reload._pending_dropped))

    async def test_custom_store_keyword_writes_never_use_owner_catalog(self):
        from backend.target_kw_index import KeywordIndex
        other=TargetMemoryService(db_path=self.root/'group.db')
        self.mem.store_item(L2Item('same','L2','fact',5,'desktop private marker','a','desktop',created_at=1))
        other.store_item(L2Item('same','L2','fact',5,'group separate marker','b','group',created_at=1))
        self.assertNotEqual(self.mem._kw.db_path,other._kw.db_path)
        self.assertEqual(self.mem._kw.query('desktop',source='l2')[0]['summary'],'desktop private marker')
        self.assertEqual(other._kw.query('group',source='l2')[0]['summary'],'group separate marker')
        self.assertEqual(other._kw.query('desktop',source='l2'),[])

    async def test_readonly_l2_write_raises_without_destroying_prior_fact(self):
        self.mem.store_item(L2Item('old','L2','fact',5,'prior fact','old','prior',created_at=1))
        original=sqlite3.connect
        def readonly(path,*args,**kwargs):
            if str(path)==str(self.db):return original(self.db.resolve().as_uri()+'?mode=ro',uri=True)
            return original(path,*args,**kwargs)
        with patch('backend.target_memory.sqlite3.connect',side_effect=readonly):
            with self.assertRaises(sqlite3.OperationalError):
                self.mem.store_item(L2Item('new','L2','fact',5,'new fact','new','new',created_at=1))
        con=original(str(self.db))
        try:self.assertEqual(con.execute('SELECT id FROM l2_items').fetchall(),[('old',)])
        finally:con.close()


class ModelResourceTests(unittest.TestCase):
    def test_semantic_disabled_by_default_and_training_overrides_cpu(self):
        self.assertFalse(semantic_model_allowed({}))
        self.assertTrue(semantic_model_allowed({'YHLZ_MEMORY_SEMANTIC_MODE':'cpu'}))
        for key in ['YHLZ_TRAINING_ACTIVE','YHLZ_FINETUNE_ACTIVE']:
            self.assertFalse(semantic_model_allowed({'YHLZ_MEMORY_SEMANTIC_MODE':'cpu',key:'1'}))

    def test_training_refuses_even_cached_embedding_model(self):
        with patch.dict('os.environ',{'YHLZ_TRAINING_ACTIVE':'1','YHLZ_MEMORY_SEMANTIC_MODE':'cpu'}), \
             patch.object(vm,'_model',object()):
            with self.assertRaises(MemoryWorkDeferred):vm._load_model()

    def test_training_never_spawns_reranker_thread(self):
        with patch.dict('os.environ',{'YHLZ_TRAINING_ACTIVE':'1'}), \
             patch('threading.Thread',side_effect=AssertionError('model worker forbidden')):
            vm.warm_reranker()
            with self.assertRaises(RuntimeError):vm.rerank('query',['candidate'])

    def test_empty_embedding_batch_does_not_import_model(self):
        with patch.object(vm,'_load_model',side_effect=AssertionError('model forbidden')):
            self.assertEqual(vm.embed([]).shape,(0,vm.DIM))

if __name__=='__main__':unittest.main()
