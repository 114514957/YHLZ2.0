import asyncio, os, tempfile, unittest
from pathlib import Path
from unittest.mock import AsyncMock
from backend.memory_resource_policy import load_memory_resource_policy, build_memory_hooks, DeferredMemoryHooks, MemoryWorkDeferred
from backend.target_memory import TargetMemoryService

class ResourcePolicyTests(unittest.TestCase):
 def test_disabled_by_default_and_training_wins(self):
  p=load_memory_resource_policy({}); self.assertEqual(p.mode,"disabled")
  p=load_memory_resource_policy({"YHLZ_MEMORY_LLM_MODE":"local","YHLZ_TRAINING_ACTIVE":"1"}); self.assertEqual(p.mode,"disabled"); self.assertEqual(p.reason,"training-active")
 def test_no_implicit_provider(self):
  hooks,j,p=build_memory_hooks(load_memory_resource_policy({})); self.assertIsInstance(hooks,DeferredMemoryHooks); self.assertEqual(p.mode,"disabled")
class MemoryResourceIntegration(unittest.IsolatedAsyncioTestCase):
 async def test_disabled_keeps_backlog(self):
  d=Path(tempfile.mkdtemp()); m=TargetMemoryService(db_path=d/'m.db',window_turns=2); h,_,pol=build_memory_hooks(load_memory_resource_policy({})); m.set_resource_policy(pol);m.set_llm_hooks(h,h)
  for i in range(4): m.append_turn(role='user',text=f'long {i}')
  await m.process_summary(); self.assertEqual(m.health()['summary_backlog'],2); self.assertEqual(m.health()['resource_mode'],'disabled')
 async def test_summary_write_failure_restores_prefix(self):
  d=Path(tempfile.mkdtemp()); m=TargetMemoryService(db_path=d/'m.db',window_turns=1); h,_,_=build_memory_hooks(load_memory_resource_policy({}))
  class H:
   async def compress(self,dropped,prev=''): return ('new summary',1)
  m.set_llm_hooks(H(),H()); m.append_turn(role='user',text='a'); m.append_turn(role='user',text='b')
  m._save_l1=lambda: False
  await m.process_summary(); self.assertTrue(m.health()['summary_pending']); self.assertEqual(m.health()['summary_backlog'],1)
 if __name__=='__main__': unittest.main()
