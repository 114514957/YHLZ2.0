import asyncio
import unittest
from backend.text_memory_inference_gate import TextMemoryInferenceGate, inference_gate

class TextMemoryGateTests(unittest.IsolatedAsyncioTestCase):
    async def test_foreground_overtakes_queued_background_but_not_active_request(self):
        gate=TextMemoryInferenceGate();order=[];started=asyncio.Event();release=asyncio.Event()
        async def first():
            async with gate.slot(background=True):
                order.append('bg-active');started.set();await release.wait()
        async def next_(name,background):
            async with gate.slot(background=background):order.append(name)
        task=asyncio.create_task(first());await started.wait()
        bg=asyncio.create_task(next_('bg-queued',True));fg=asyncio.create_task(next_('fg',False))
        await asyncio.sleep(0);self.assertEqual(order,['bg-active'])
        release.set();await asyncio.gather(task,bg,fg)
        self.assertEqual(order,['bg-active','fg','bg-queued'])

    async def test_cancelled_waiter_does_not_block_background(self):
        gate=TextMemoryInferenceGate()
        async with gate.slot():
            async def waiting():
                async with gate.slot():pass
            waiter=asyncio.create_task(waiting());await asyncio.sleep(0)
            self.assertEqual(gate.foreground_waiters,1)
            waiter.cancel();await asyncio.gather(waiter,return_exceptions=True)
            self.assertEqual(gate.foreground_waiters,0)
        async with gate.slot(background=True):self.assertEqual(gate.active,'background')
        self.assertEqual(gate.active,'')

    async def test_cancellation_releases_active_slot(self):
        gate=TextMemoryInferenceGate();started=asyncio.Event()
        async def work():
            async with gate.slot(background=True):started.set();await asyncio.Event().wait()
        task=asyncio.create_task(work());await started.wait();task.cancel()
        await asyncio.gather(task,return_exceptions=True)
        async with gate.slot():self.assertEqual(gate.active,'foreground')

    async def test_single_flight_under_mixed_load(self):
        gate=TextMemoryInferenceGate();active=peak=0
        async def work(i):
            nonlocal active,peak
            async with gate.slot(background=bool(i%2)):
                active+=1;peak=max(peak,active);await asyncio.sleep(0);active-=1
        await asyncio.gather(*(work(i) for i in range(50)))
        self.assertEqual(peak,1)
        self.assertEqual(gate.foreground_runs,25);self.assertEqual(gate.background_runs,25)
        self.assertIs(inference_gate(),inference_gate())

class MemoryHookGateTests(unittest.IsolatedAsyncioTestCase):
    async def test_training_switch_while_queued_prevents_provider_call(self):
        from unittest.mock import patch
        from backend.target_memory_llm import MemoryLLMService
        from backend.memory_resource_policy import MemoryWorkDeferred
        import os
        calls=[]
        class Provider:
            async def stream_chat(self,*args,**kwargs):
                calls.append(1)
                yield 'unexpected'
        gate=inference_gate()
        with patch.dict(os.environ, {'YHLZ_MEMORY_LLM_MODE':'local','YHLZ_TRAINING_ACTIVE':'0','YHLZ_FINETUNE_ACTIVE':'0'}):
            hooks=MemoryLLMService(None,local=Provider(),resource_guard=True)
            async with gate.slot():
                task=asyncio.create_task(hooks._chat_msgs(hooks.local,[{'role':'user','content':'fixture'}]))
                await asyncio.sleep(0)
                self.assertEqual(gate.background_waiters,1)
                os.environ['YHLZ_TRAINING_ACTIVE']='1'
            with self.assertRaises(MemoryWorkDeferred):await task
        self.assertEqual(calls,[])
        self.assertEqual(gate.health()['active'],'')

    async def test_memory_hooks_share_single_slot_with_foreground(self):
        from backend.target_memory_llm import MemoryLLMService
        order=[]
        class Provider:
            async def stream_chat(self,*args,**kwargs):
                order.append('memory');yield 'summary'
        hooks=MemoryLLMService(None,local=Provider())
        gate=inference_gate()
        async with gate.slot():
            job=asyncio.create_task(hooks._chat_msgs(hooks.local,[{'role':'user','content':'fixture'}]))
            await asyncio.sleep(0)
            self.assertEqual(order,[])
        self.assertEqual(await job,'summary')
        self.assertEqual(order,['memory'])

if __name__=='__main__':unittest.main()
