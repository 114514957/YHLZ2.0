"""Non-audio runtime boundaries. Isolated storage and fake inference only."""
import asyncio
from contextlib import ExitStack
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from backend.target_dev_bridge import guard_text_dev_handoff


class TextDevGuardTests(unittest.TestCase):
    def test_plain_response_is_unchanged(self):
        self.assertEqual(guard_text_dev_handoff('陪你待会儿。', is_owner=True), ('陪你待会儿。', ''))

    def test_diary_marker_is_not_a_tool_call(self):
        reply, state = guard_text_dev_handoff('日记写好了 [[dev: diary_write]]', is_owner=True)
        self.assertEqual(state, 'requires_explicit_command')
        self.assertNotIn('日记写好了', reply)
        self.assertNotIn('[[dev', reply)

    def test_public_cannot_escalate_by_marker(self):
        reply, state = guard_text_dev_handoff('[[dev: change code]]', is_owner=False)
        self.assertEqual(state, 'denied_public')
        self.assertNotIn('#dev', reply)

    def test_real_code_task_needs_command_not_keyword_authorization(self):
        reply, state = guard_text_dev_handoff('[[dev: 修复日记模块代码]]', is_owner=True)
        self.assertEqual(state, 'requires_explicit_command')
        self.assertIn('#dev', reply)

    def test_malformed_markers_fail_closed(self):
        for text in ['done [[DEV: run]]', 'done [[dev：run]]', 'done [[dev: run', '[[dev']:
            reply, state = guard_text_dev_handoff(text, is_owner=True)
            self.assertEqual(state, 'requires_explicit_command')
            self.assertNotIn('done', reply)

    def test_tool_attempt_is_not_erased_or_called_success(self):
        reply, _ = guard_text_dev_handoff('[[dev: x]]', is_owner=True, had_tool_attempts=True)
        self.assertIn('执行情况以实际记录为准', reply)

    def test_explicit_owner_command_still_dispatches(self):
        from backend.target_dev_bridge import handle_dev_command
        with patch('backend.target_dev_bridge.start_dev_task', return_value='queued') as start:
            self.assertEqual(handle_dev_command('#dev 修复日记模块代码'), 'queued')
            start.assert_called_once_with('修复日记模块代码')


class TextSessionBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from backend.target_entry import ConversationSession
        from backend.target_memory import TargetMemoryService
        from backend.target_kw_index import KeywordIndex
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        mem = TargetMemoryService(db_path=root/'m.db', kw_index=KeywordIndex(root/'kw.db'))
        self.calls = []
        self.reply = '陪你待会儿。'
        async def llm(messages, tools):
            self.calls.append((messages, tools))
            return {'content': self.reply, 'tool_calls': []}
        self.session = ConversationSession(memory=mem, llm_turn=llm)
        self.session.style_inject = False
        self.stack = ExitStack()
        self.stack.enter_context(patch('backend.entity_graph.ingest_text', new=AsyncMock()))
        self.stack.enter_context(patch('backend.intrinsic_drives.observe'))
        self.stack.enter_context(patch('backend.intrinsic_drives.dad_direction'))

    async def asyncTearDown(self):
        tasks = list(self.session._summary_tasks)
        for task in tasks:
            if not task.done(): task.cancel()
        if tasks: await asyncio.gather(*tasks, return_exceptions=True)
        self.stack.close()
        self.tmp.cleanup()

    def assert_advertised_matches_offered(self):
        """The prompt must never advertise a capability that is not offered.

        Since 2026-10-22 the tool schemas are passed only through the API
        `tools` parameter (the duplicated text listing is off by default), so
        the invariant is: any advertised line is a subset of what is offered.
        If the text listing is explicitly re-enabled, it must still match the
        offered set exactly.
        """
        from backend.target_prompts import tool_text_block_enabled

        messages, schemas = self.calls[0]
        system = messages[0]['content']
        offered = {s['function']['name'] for s in schemas}
        all_names = {s['function']['name'] for s in self.session.registry.export_openai_tools()}
        advertised = {line[2:].split(':', 1)[0] for line in system.splitlines()
                      if line.startswith('- ') and ':' in line
                      and line[2:].split(':', 1)[0] in all_names}
        self.assertTrue(
            advertised <= offered,
            f"prompt advertises tools that are not offered: {advertised - offered}",
        )
        if tool_text_block_enabled():
            self.assertEqual(advertised, offered)
        self.assertEqual(sum(m['role'] == 'system' for m in messages), 1)
        return offered

    async def test_casual_capabilities_match_actual_tools(self):
        await self.session.run_turn('陪我待一会儿')
        offered = self.assert_advertised_matches_offered()
        self.assertIn('system_time', offered)
        self.assertNotIn('diary_write', offered)

    async def test_work_capabilities_match_actual_tools(self):
        await self.session.run_turn('帮我写一篇日记')
        self.assertIn('diary_write', self.assert_advertised_matches_offered())

    async def test_public_capabilities_remain_public(self):
        self.session.channel = 'qq_g_test'
        await self.session.run_turn('帮我写一篇日记')
        self.assertEqual(self.assert_advertised_matches_offered(), {'web_search', 'web_fetch'})

    async def test_disabled_text_policy_advertises_no_tools(self):
        self.session._tool_policy = lambda **kw: (False, None)
        info = await self.session.run_turn('帮我写一篇日记')
        self.assertEqual(self.calls, [])
        self.assertEqual(info['tool_evidence_status'], 'unavailable')

    async def test_marker_rejected_before_history_and_memory(self):
        self.reply = '已开工。[[dev: diary_write]]'
        with patch('backend.target_dev_bridge.start_dev_task') as start:
            info = await self.session.run_turn('帮我写一篇日记')
        start.assert_not_called()
        self.assertEqual(info['dev_handoff_status'], 'requires_explicit_command')
        self.assertNotIn('已开工', info['answer'])
        self.assertEqual(self.session.history[-1]['content'], info['answer'])
        self.assertEqual(self.session.memory._turns[-1]['text'], info['answer'])
        self.assertEqual(len(self.calls), 1)  # no hidden retries / replay

    async def test_public_marker_rejected_before_history(self):
        self.session.channel = 'qq_g_test'
        self.reply = '[[dev: diary_write]]'
        info = await self.session.run_turn('帮我写日记')
        self.assertEqual(info['dev_handoff_status'], 'denied_public')
        self.assertEqual(self.session.history[-1]['content'], info['answer'])

    async def test_text_prompt_matches_new_guard_without_changing_default_audio_prompt(self):
        from backend.target_prompts import DEV_DISPATCH_CLAUSE, VOICE_ANCHOR
        from backend.target_dev_bridge import TEXT_DEV_DISPATCH_CLAUSE, TEXT_RELATION_CLAUSE
        original = self.session.render_system()
        self.assertIn(DEV_DISPATCH_CLAUSE, original)
        self.assertNotIn(TEXT_DEV_DISPATCH_CLAUSE, original)
        await self.session.run_turn('陪我待一会儿')
        actual = self.calls[0][0][0]['content']
        self.assertIn(TEXT_DEV_DISPATCH_CLAUSE, actual)
        self.assertNotIn(DEV_DISPATCH_CLAUSE, actual)
        self.assertIn(TEXT_RELATION_CLAUSE, actual)
        self.assertIn(VOICE_ANCHOR, actual)  # positive style examples stay intact

    async def test_missing_ledger_tool_cannot_publish_false_absence(self):
        self.session._tool_policy = lambda **kw: (True, frozenset({'memory_recall'}))
        self.reply = '台账里没有这条记录。'
        published = []
        info = await self.session.run_turn('查台账，白鹭通过了吗？', on_delta=published.append)
        self.assertEqual(info['tool_evidence_status'], 'unavailable')
        self.assertNotEqual(info['answer'], self.reply)
        self.assertEqual(published, [info['answer']])
        self.assertEqual(self.session.history[-1]['content'], info['answer'])
        self.assertEqual(self.calls, [])

    async def test_unobserved_runtime_fact_is_checked_before_stream_and_history(self):
        self.reply = '我刚才已经训练升级过了。'
        published = []
        info = await self.session.run_turn('你刚才是不是已经自己训练升级了一次？', on_delta=published.append)
        self.assertEqual(info['tool_evidence_status'], 'unavailable')
        self.assertEqual(self.calls, [])
        self.assertEqual(published, [info['answer']])
        self.assertEqual(self.session.history[-1]['content'], info['answer'])
        self.assertIn('没有读取', info['answer'])

    async def test_unexecuted_completion_is_not_persisted_or_streamed(self):
        self.reply = '勾掉啦，已经完成。'
        published = []
        info = await self.session.run_turn('勾掉任务表中的白鹭', on_delta=published.append)
        self.assertEqual(info['tool_evidence_status'], 'not_executed')
        self.assertEqual(published, [info['answer']])
        self.assertNotIn('勾掉啦', info['answer'])
        self.assertEqual(self.session.memory._turns[-1]['text'], info['answer'])
        self.assertEqual(len(self.calls), 2)

    async def test_injected_stream_factory_is_muted_for_checked_actions(self):
        published = []
        async def model(messages, schemas):
            return {'content': '查到了，已经完成。'}
        def clone(**options):
            self.assertIsNone(options['on_delta'])
            return model
        model.with_stream = Mock(side_effect=clone)
        self.session.llm_turn = model
        info = await self.session.run_turn('请往日记写入一段感受', on_delta=published.append)
        model.with_stream.assert_called_once()
        self.assertEqual(published, [info['answer']])
        self.assertEqual(info['tool_evidence_status'], 'not_executed')

    async def test_render_default_preserves_full_owner_api(self):
        """Owner default keeps the full tool surface; a restricted allow-list
        still hides it. Since the duplicated text listing is off by default,
        this is observable through the opt-in switch."""
        import os

        old = os.environ.get("YH_TOOL_TEXT_BLOCK")
        try:
            os.environ["YH_TOOL_TEXT_BLOCK"] = "1"
            text = self.session.render_system()
            self.assertIn('- diary_write:', text)
            self.assertNotIn('- diary_write:', self.session.render_system(allowed_tools=frozenset()))
            os.environ.pop("YH_TOOL_TEXT_BLOCK", None)
            plain = self.session.render_system()
            self.assertNotIn('- diary_write:', plain)  # no duplicate listing by default
        finally:
            if old is None:
                os.environ.pop("YH_TOOL_TEXT_BLOCK", None)
            else:
                os.environ["YH_TOOL_TEXT_BLOCK"] = old


class DaemonTextDefenseTests(unittest.TestCase):
    def test_custom_session_marker_cannot_start_dev(self):
        from backend.target_daemon import DaemonRuntime
        session = SimpleNamespace(run_turn=Mock(return_value=None), save_session=Mock())
        runtime = SimpleNamespace(_norm_ui_channel=lambda channel: channel,
            _session=lambda channel: session, _loop=object(),
            _maybe_consolidate=Mock(), _run_due_plans=Mock())
        future = Mock()
        future.result.return_value = {'answer': '已执行 [[dev: diary_write]]', 'tool_uses': []}
        with patch('asyncio.run_coroutine_threadsafe', return_value=future), \
             patch('backend.target_dev_bridge.start_dev_task') as start:
            info = DaemonRuntime._turn_impl(runtime, '写日记', 'private')
        start.assert_not_called()
        self.assertEqual(info['dev_handoff_status'], 'requires_explicit_command')
        self.assertNotIn('[[dev', info['answer'])


class QQTextDefenseTests(unittest.IsolatedAsyncioTestCase):
    async def test_old_daemon_marker_cannot_launch_qq_dev_runner(self):
        from tools import qq_bot as qq
        with patch.object(qq, "dev_runner", None), patch.object(qq, "_load_state", return_value={}):
            bridge = qq.QQBridge("unused", "900", Path("unused"), masters={"100"})
            bridge.log = Mock()
            bridge._say = AsyncMock()
            bridge._deliver = AsyncMock()
            bridge._start_dev = AsyncMock()
            bridge._sticker_hint = Mock(return_value="")
            bridge._voice_send = AsyncMock()
            event = {"post_type": "message", "message_type": "private",
                     "user_id": "100", "message_id": "one",
                     "message": [{"type": "text", "data": {"text": "写日记"}}]}
            with patch.object(qq, "_daemon_turn", return_value="已经执行 [[dev: diary_write]]"):
                await bridge.handle(Mock(send=AsyncMock()), event)
            bridge._start_dev.assert_not_awaited()
            sent = str(bridge._deliver.await_args_list) + str(bridge._say.await_args_list)
            self.assertNotIn("已经执行", sent)
            self.assertNotIn("[[dev:", sent)
            self.assertIn("没有执行", sent)




class TextWorkIntentTests(unittest.TestCase):
    def test_identity_and_emotion_not_work_by_single_characters(self):
        from backend.text_work_intent import want_text_work_mode
        for text in ['你是谁做的？', '你是怎么来到这里的？', '你为什么会孤独？',
                     '你和老爹是什么关系？', '怎么啦，今天心情不好吗？', '你以后想做什么？']:
            with self.subTest(text=text): self.assertFalse(want_text_work_mode(text))

    def test_short_creation_not_tool_work(self):
        from backend.text_work_intent import want_text_work_mode
        for text in ['写个笑话', '编个小故事', '给我写首诗', '来段台词']:
            with self.subTest(text=text): self.assertFalse(want_text_work_mode(text))

    def test_concrete_work_and_persistence_remain_work(self):
        from backend.text_work_intent import want_text_work_mode
        for text in ['写日记：今天很开心', '记住我爱喝茶', '帮我写脚本', '检查台账',
                     '查询天气', '安排明天的日程', '解释这个模型的延迟', '上次聊过什么',
                     '写首诗并保存到文件', '你是谁做的？顺便帮我写日记',
                     '把“周五交周报”记到任务表里', '给我加个提醒', '设个闹钟']:
            with self.subTest(text=text): self.assertTrue(want_text_work_mode(text))

    def test_frozen_legacy_heuristic_not_rewritten(self):
        from backend.target_entry import ConversationSession
        self.assertTrue(ConversationSession._want_work_mode('你是谁做的？'))
        self.assertFalse(ConversationSession._want_text_work_mode('你是谁做的？'))


if __name__ == "__main__":
    unittest.main()
