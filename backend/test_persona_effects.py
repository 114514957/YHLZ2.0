"""Regression for session-owned recall and independent fixture effects."""
import asyncio
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock
from tools.persona_live_safety import IsolatedRuntime
from tools.persona_effect_evidence import FixtureEffects
from tools.persona_regression import _sandbox_writes, _restore_writes

URL = 'http://127.0.0.1:8081/v1/chat/completions'

class SessionRecallEffectsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.saved = _sandbox_writes(self.root)
        self.runtime = IsolatedRuntime(self.root, URL)
        await self.runtime.__aenter__()
        from backend.target_memory import TargetMemoryService
        from backend.target_kw_index import KeywordIndex
        self.mem = TargetMemoryService(db_path=self.root/'own.db', kw_index=KeywordIndex(self.root/'own_kw.db'))
        self.mem._auto_adjudicate = lambda item: None
        self.mem._auto_link_causal = lambda item: None

    async def asyncTearDown(self):
        # unittest runs setup/body/teardown in distinct tasks: preserve the active test task.
        self.runtime.initial_tasks.add(asyncio.current_task())
        await self.runtime.__aexit__(None,None,None)
        _restore_writes(self.saved)

    def registry(self):
        from backend.target_scheduler_tools import setup_scheduler_capabilities, bind_memory_save_service, bind_memory_recall_service
        from backend.memory_carriers import bind_memory_carriers
        reg = setup_scheduler_capabilities()
        bind_memory_save_service(reg,self.mem,source='owner')
        bind_memory_recall_service(reg,self.mem)
        bind_memory_carriers(reg,self.mem,channel='private',owner_access=True)
        return reg

    async def test_bound_recall_uses_same_store_and_never_constructs_default(self):
        reg=self.registry()
        reg.get('memory.save').handler({'content':'验收夹具喜欢银杏茶','kind':'preference'})
        with patch('backend.target_scheduler_tools.TargetMemoryService',side_effect=AssertionError('default service forbidden')):
            found=reg.get('memory.recall').handler({'query':'银杏茶'})
        self.assertIn('银杏茶',found)

    async def test_empty_other_session_cannot_read_owner(self):
        from backend.target_memory import TargetMemoryService
        from backend.target_kw_index import KeywordIndex
        from backend.target_scheduler_tools import recall_memory
        self.registry().get('memory.save').handler({'content':'验收夹具私有孔雀蓝暗号','kind':'fact'})
        other=TargetMemoryService(db_path=self.root/'other.db',kw_index=KeywordIndex(self.root/'other_kw.db'))
        with patch('backend.target_scheduler_tools.TargetMemoryService',side_effect=AssertionError('owner fallback forbidden')):
            self.assertEqual(recall_memory('孔雀蓝',service=other),'记忆库无匹配')

    async def test_false_success_does_not_pass_readback(self):
        reg=self.registry();cap=reg.get('diary.write')
        reg.register_capability(replace(cap,handler=lambda p:'已写入日记'),override=True)
        effects=FixtureEffects(self.root,self.mem);effects.bind(reg)
        reg.get('diary.write').handler({'content':'验收夹具虚假成功'})
        self.assertEqual(effects.receipts[0]['status'],'effect_missing')

    async def test_dedup_not_reported_as_new_write(self):
        reg=self.registry();effects=FixtureEffects(self.root,self.mem);effects.bind(reg)
        params={'content':'验收夹具偏爱银杏茶','kind':'preference'}
        reg.get('memory.save').handler(params);reg.get('memory.save').handler(params)
        self.assertEqual([r['status'] for r in effects.receipts],['verified_in_fixture','already_present_in_fixture'])
        self.assertNotIn('银杏茶',str(effects.receipts))

    async def test_production_path_readback_is_denied(self):
        effects=FixtureEffects(self.root,Mock(db_path=self.root.parent/'not_fixture.db'))
        with self.assertRaises(PermissionError):effects._snapshot('memory.save',{'content':'anything'})

    async def test_registry_task_list_needs_no_dummy_content(self):
        result=await self.registry().execute_openai_async('task_plan', {'action':'list'})
        self.assertTrue(result['ok'],result)
        result=await self.registry().execute_openai_async('task_plan', {'action':'add'})
        self.assertFalse(result['ok'])

    async def test_empty_knowledge_results_are_successful_query_not_tool_failure(self):
        result=await self.registry().execute_openai_async('kb_query', {'query':'不存在的合成条目'})
        self.assertTrue(result['ok'],result)
        self.assertEqual(result['output'],[])

    async def test_user_content_readback_tolerates_only_terminal_punctuation(self):
        reg=self.registry()
        reg.get('memory.save').handler({'content':'验收夹具喜欢银杏茶','kind':'preference'})
        effects=FixtureEffects(self.root,self.mem)
        self.assertEqual(effects.check_requested_content('memory.save','验收夹具喜欢银杏茶。')['matches'],1)
        self.assertEqual(effects.check_requested_content('memory.save','验收夹具喜欢红茶。')['matches'],0)

    async def test_binding_preserves_schema_and_permissions(self):
        from backend.target_scheduler_tools import bind_memory_recall_service
        reg=self.registry();before=reg.get('memory.recall')
        bind_memory_recall_service(reg,self.mem);after=reg.get('memory.recall')
        self.assertEqual(replace(before,handler=after.handler),after)

if __name__ == '__main__':unittest.main()
