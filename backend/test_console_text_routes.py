"""Real text HTTP handlers + daemon handoff + isolated session; no listening socket."""
import asyncio
from contextlib import ExitStack
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

from backend.console_server import ConsoleHandler
from backend.target_daemon import DaemonRuntime
from backend.target_entry import ConversationSession
from backend.target_memory import TargetMemoryService
from backend.target_kw_index import KeywordIndex


class ConsoleTextRoutesTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.stack = ExitStack()
        self.stack.enter_context(patch('backend.target_entry.SESSIONS_DIR', self.root/'sessions'))
        self.stack.enter_context(patch('backend.entity_graph.ingest_text', new=AsyncMock()))
        self.stack.enter_context(patch('backend.intrinsic_drives.observe'))
        self.stack.enter_context(patch('backend.intrinsic_drives.dad_direction'))
        self.enter = self.stack.enter_context(patch('backend.gpu_lock.chat_enter', return_value=True))
        self.exit = self.stack.enter_context(patch('backend.gpu_lock.chat_exit'))
        self.model = AsyncMock(return_value={'content': '元亨收到了。', 'tool_calls': []})
        async def model(messages, tools):
            return await self.model(messages, tools)
        memory = TargetMemoryService(db_path=self.root/'memory.db',
                                     kw_index=KeywordIndex(self.root/'kw.db'), l1_scope='console')
        self.session = ConversationSession(memory=memory, llm_turn=model, channel='console')
        self.session.style_inject = False
        # Do not invoke the production constructor or start its worker threads.
        self.runtime = object.__new__(DaemonRuntime)
        self.runtime._loop = asyncio.get_running_loop()
        self.runtime._session = Mock(return_value=self.session)
        self.runtime._maybe_consolidate = Mock()
        self.runtime._run_due_plans = Mock()

    async def asyncTearDown(self):
        tasks = list(self.session._summary_tasks)
        for task in tasks:
            if not task.done(): task.cancel()
        if tasks: await asyncio.gather(*tasks, return_exceptions=True)
        self.stack.close()
        self.tmp.cleanup()

    def handler(self, path, body=b''):
        handler = object.__new__(ConsoleHandler)
        handler.runtime = self.runtime
        handler.path = path
        handler.headers = {'Content-Length': str(len(body))}
        handler.rfile = io.BytesIO(body)
        handler.wfile = io.BytesIO()
        handler.send_response = Mock()
        handler.send_header = Mock()
        handler.end_headers = Mock()
        return handler

    async def post(self, text):
        handler = self.handler('/talk', json.dumps({'text': text}).encode())
        await asyncio.to_thread(handler.console_do_POST)
        return handler

    def frames(self, handler):
        return [json.loads(line[6:]) for line in handler.wfile.getvalue().decode().splitlines()
                if line.startswith('data: ')]

    async def test_text_to_daemon_session_history_and_saved_archive(self):
        handler = await self.post('路由夹具打个招呼')
        frames = self.frames(handler)
        self.assertEqual(frames[0].get("type"), "state")
        self.assertEqual(frames[0].get("value"), "thinking")
        # 段5（0635）：thinking 事件现带 request_id（断连后取结果用）
        self.assertIn("request_id", frames[0])
        done = [f for f in frames if f['type']=='turn_done']
        self.assertEqual(done[0]['text'], '元亨收到了。')
        self.assertEqual(frames[-1], {'type': 'state', 'value': 'idle'})
        history = self.handler('/history')
        history.console_do_GET()
        messages = json.loads(history.wfile.getvalue())['messages']
        self.assertEqual(messages[-1]['content'], done[0]['text'])
        self.assertTrue((self.root/'sessions'/'console.json').is_file())
        self.runtime._maybe_consolidate.assert_called_once_with('console')
        self.runtime._run_due_plans.assert_called_once()
        self.exit.assert_called_once()

    async def test_unexecuted_write_is_corrected_before_sse_and_history(self):
        self.model.return_value = {'content': '保存好了。', 'tool_calls': []}
        handler = await self.post('请调用记忆工具保存这条偏好：路由夹具喜欢银杏茶。')
        frames = self.frames(handler)
        done = next(f for f in frames if f['type']=='turn_done')
        self.assertNotEqual(done['text'], '保存好了。')
        self.assertIn('还没有完成', done['text'])
        self.assertEqual(self.session.history[-1]['content'], done['text'])
        self.assertNotIn('保存好了。', ''.join(f.get('delta','') for f in frames))
        self.assertEqual(self.session.memory.recall('路由夹具'), [])

    async def test_injected_text_provider_binds_per_request_stream(self):
        callbacks = []
        class Provider:
            async def __call__(self, messages, tools):
                raise AssertionError('unbound provider used')
            def with_stream(self, **options):
                callbacks.append(options['on_delta'])
                async def bound(messages, tools):
                    options['on_delta']('元亨')
                    await asyncio.sleep(0)
                    options['on_delta']('在这里。')
                    return {'content': '元亨在这里。', 'tool_calls': []}
                return bound
        self.session.llm_turn = Provider()
        for _ in range(2):
            handler = await self.post('打个招呼')
            frames = self.frames(handler)
            self.assertEqual([f['delta'] for f in frames if f['type']=='delta'], ['元亨', '在这里。'])
            self.assertEqual(next(f['text'] for f in frames if f['type']=='turn_done'), '元亨在这里。')
        self.assertEqual(len(callbacks), 2)
        self.assertIsNot(callbacks[0], callbacks[1])

    async def test_empty_text_never_enters_model(self):
        handler = await self.post('  ')
        handler.send_response.assert_called_once_with(400)
        self.model.assert_not_called()
        self.exit.assert_called_once()

    async def test_invalid_json_releases_lock(self):
        handler = self.handler('/talk', b'{bad')
        handler.console_do_POST()
        handler.send_response.assert_called_once_with(400)
        self.exit.assert_called_once()
        self.model.assert_not_called()

    async def test_busy_rejects_without_session_call(self):
        self.enter.return_value = False
        handler = await self.post('fixture')
        handler.send_response.assert_called_once_with(409)
        self.runtime._session.assert_not_called()
        self.exit.assert_not_called()

    async def test_failure_sends_error_and_idle_without_false_completion(self):
        self.runtime.console_turn_stream = Mock(side_effect=TimeoutError('synthetic timeout'))
        handler = await self.post('fixture')
        frames = self.frames(handler)
        self.assertEqual([f['type'] for f in frames], ['state', 'error', 'state'])
        self.assertEqual(frames[-1]['value'], 'idle')
        self.exit.assert_called_once()

    async def test_emotion_route_returns_text_classification(self):
        handler = self.handler('/emotion?text=hello')
        handler.console_do_GET()
        result = json.loads(handler.wfile.getvalue())
        self.assertIn('emotion', result)
        self.model.assert_not_called()

    async def test_existing_popup_asset_is_served(self):
        handler = self.handler('/chat_popup.html')
        handler.console_do_GET()
        self.assertIn(b'/talk', handler.wfile.getvalue())
        self.assertIn(b'turn_done', handler.wfile.getvalue())


if __name__ == '__main__': unittest.main()
