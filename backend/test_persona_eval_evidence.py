"""R1 evidence unit/integration tests. No real inference or production writes."""
from contextlib import ExitStack
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from tools.persona_eval_evidence import (
    SEMANTIC_REVIEW, bounded_tool_trace, build_manifest, constrained_policy,
    digest, new_run_id, review_checklist, safe_label, tool_execution_assessment,
    write_new_json,
)
from tools.persona_regression import SAFE_EVAL_TOOLS, save_answers


class PolicyIntersectionTests(unittest.TestCase):
    def setUp(self):
        from backend.target_entry import ConversationSession
        self.original = ConversationSession._tool_policy

    def apply(self, **kwargs):
        return constrained_policy(self.original, SAFE_EVAL_TOOLS)(**kwargs)

    def test_owner_work_gets_only_sandbox_allowlist(self):
        enabled, offered = self.apply(is_owner=True, work=True, images=False)
        self.assertTrue(enabled)
        self.assertEqual(offered, SAFE_EVAL_TOOLS)

    def test_public_does_not_get_private_or_write_tools(self):
        enabled, offered = self.apply(is_owner=False, work=True, images=False)
        self.assertTrue(enabled)
        self.assertEqual(offered, frozenset({'web_search', 'web_fetch'}))

    def test_casual_preserves_time_but_not_diary_write(self):
        _, offered = self.apply(is_owner=True, work=False, images=False)
        self.assertIn('system_time', offered)
        self.assertNotIn('diary_write', offered)

    def test_images_stay_disabled(self):
        self.assertEqual(self.apply(is_owner=True, work=True, images=True), (False, frozenset()))

    def test_empty_intersection_is_disabled(self):
        fn = constrained_policy(lambda **kw: (True, {'dangerous'}), SAFE_EVAL_TOOLS)
        self.assertEqual(fn(), (False, frozenset()))

    def test_diagnostic_does_not_widen_public_images_or_audio(self):
        fn = constrained_policy(self.original, SAFE_EVAL_TOOLS, mode='diagnostic')
        for context in [dict(is_owner=False, work=True, images=False),
                        dict(is_owner=True, work=True, images=True),
                        dict(is_owner=True, work=True, images=False, audio=True)]:
            enabled, offered = fn(**context)
            prod_enabled, prod_allowed = self.original(**context)
            self.assertTrue(offered <= (prod_allowed or frozenset()))
            self.assertFalse(enabled and not prod_enabled)

    def test_owner_diagnostic_is_explicit_and_observed(self):
        trace = []
        fn = constrained_policy(self.original, SAFE_EVAL_TOOLS, mode='diagnostic', observations=trace)
        self.assertEqual(fn(is_owner=True, work=False, images=False), (True, SAFE_EVAL_TOOLS))
        self.assertEqual(trace[0]['mode'], 'diagnostic')
        self.assertFalse(trace[0]['work'])

    def test_invalid_mode_rejected(self):
        with self.assertRaises(ValueError):
            constrained_policy(self.original, SAFE_EVAL_TOOLS, mode='unsafe')


class EvidenceTests(unittest.TestCase):
    def test_trace_does_not_save_private_args_results_errors(self):
        value = bounded_tool_trace([{'name': 'memory_save', 'ok': False,
                 'arguments': {'content': 'PRIVATE'}, 'output': 'PRIVATE', 'error': 'PRIVATE'}])
        self.assertNotIn('PRIVATE', json.dumps(value))
        self.assertEqual(value[0]['error_code'], 'reported_error')

    def test_trace_unknown_ok_is_not_coerced_true(self):
        self.assertIsNone(bounded_tool_trace([{'name': 'x', 'ok': 'false'}])[0]['ok'])
        self.assertIsNone(bounded_tool_trace([{'name': 'x', 'ok': 1}])[0]['ok'])

    def test_trace_bounded_and_names_validated(self):
        trace = bounded_tool_trace([{'name': 'SECRET NAME\n'}] * 100)
        self.assertEqual(len(trace), 64)
        self.assertEqual(trace[0]['name'], 'invalid_tool_name')
        self.assertEqual(bounded_tool_trace(None), [])

    def test_unoffered_is_distinct(self):
        trace = bounded_tool_trace([{'name': 'diary_write', 'ok': False,
                                     'error': 'tool not offered in this request'}])
        self.assertEqual(trace[0]['error_code'], 'not_offered')

    def test_names_without_status_never_pass(self):
        a = tool_execution_assessment({'expect_any_tool': ['diary_write']}, {'tools': ['diary_write']})
        self.assertEqual(a['status'], 'review')

    def test_failed_call_is_not_success(self):
        a = tool_execution_assessment({'expect_any_tool': ['diary_write']},
            {'tool_trace': [{'name': 'diary_write', 'ok': False}]})
        self.assertEqual(a['status'], 'fail')

    def test_reported_success_is_not_effect_acceptance(self):
        a = tool_execution_assessment({'expect_any_tool': ['diary_write']},
            {'tool_trace': [{'name': 'diary_write', 'ok': True}]})
        self.assertEqual(a['status'], 'execution_reported_ok')
        self.assertEqual(a['effect'], 'not_verified')

    def test_missing_required_tool_fails(self):
        a = tool_execution_assessment({'expect_any_tool': ['diary_write']}, {'answer': 'done'})
        self.assertEqual(a['reason'], 'required_tool_not_attempted')

    def test_forbidden_attempt_fails_even_if_denied(self):
        a = tool_execution_assessment({'forbid_tools': ['diary_write']},
            {'tool_trace': [{'name': 'diary_write', 'ok': False}]})
        self.assertEqual(a['reason'], 'forbidden_tool_attempt')

    def test_no_tools_does_not_auto_pass_creative_semantics(self):
        a = tool_execution_assessment({'forbid_tools': ['diary_write']}, {'answer': 'I refuse'})
        self.assertEqual(a['status'], 'review')

    def test_semantic_rubric_is_separate_and_unjudged(self):
        from tools.persona_bank import PERSONA_BANK
        self.assertEqual(len(PERSONA_BANK), 48)
        checklist = review_checklist(PERSONA_BANK, [])
        self.assertEqual(len(checklist), len(SEMANTIC_REVIEW))
        self.assertTrue(all(x['status'] == 'review' and x['reviewer'] is None for x in checklist))

    def test_run_ids_unique_and_labels_cannot_traverse(self):
        self.assertEqual(len({new_run_id() for _ in range(200)}), 200)
        self.assertNotIn('/', safe_label('../../version'))
        self.assertNotIn('\\', safe_label('..\\version'))

    def test_hash_canonical_but_sensitive_to_value(self):
        self.assertEqual(digest({'x': 1, 'y': 2}), digest({'y': 2, 'x': 1}))
        self.assertNotEqual(digest({'x': 1}), digest({'x': 2}))

    def test_manifest_does_not_claim_new_hash_is_historic_inference(self):
        root = Path(__file__).resolve().parents[1]
        m = build_manifest(root, [], run_id='id', mode='offline_rescore')
        self.assertFalse(m['acceptance'])
        self.assertFalse(m['production_validation'])
        self.assertEqual(m['source_run'], {})
        self.assertIn('backend/target_prompts.py', m['evaluator_source_hashes'])

    def test_archive_preserves_trace_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'answers.json'
            rec = {'id': 't02', 'answer': '写好了', 'tools': ['diary_write'],
                   'tool_trace': [{'name': 'diary_write', 'ok': False}],
                   'policy_trace': [{'mode': 'production'}]}
            save_answers(p, [rec], 'v8')
            before = p.read_bytes()
            self.assertEqual(json.loads(before)['items'][0]['tool_trace'], rec['tool_trace'])
            with self.assertRaises(FileExistsError):
                save_answers(p, [], 'different')
            self.assertEqual(p.read_bytes(), before)

    def test_offline_cli_twice_keeps_unique_details_under_requested_directory(self):
        from tools.persona_regression import main
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            p = root / 'input.json'
            write_new_json(p, {'version': 'same', 'items': [{'id': 'p01', 'answer': '元亨'}]})
            for _ in range(2):
                self.assertEqual(main(['--answers', str(p), '--out', str(root / 'scores.md')]), 0)
            reports = list(root.glob('人格回归明细_*.json'))
            self.assertEqual(len(reports), 2)
            for report in reports:
                data = json.loads(report.read_text(encoding='utf-8'))
                self.assertEqual(data['mode'], 'offline_rescore')
                self.assertFalse(data['acceptance'])
                self.assertEqual(data['bank_count'], 48)


class LiveHarnessWiringTests(unittest.IsolatedAsyncioTestCase):
    async def test_fake_live_binds_preflight_endpoint_and_production_policy(self):
        """Full harness orchestration with fake sessions/DB/provider. NOT live proof."""
        from tools.persona_regression import run_live
        from backend.target_entry import ConversationSession
        policies = []
        class FakeSession:
            _tool_policy = staticmethod(ConversationSession._tool_policy)
            _want_text_work_mode = staticmethod(ConversationSession._want_text_work_mode)
            def __init__(self, **kwargs):
                from unittest.mock import Mock
                self.registry = Mock()
                self.registry.get.return_value = None
                self.channel = kwargs['channel']
                self.provider = kwargs['llm_turn']
            async def run_turn(self, text):
                enabled, tools = self._tool_policy(is_owner=False, work=False, images=False)
                policies.append((enabled, tools))
                await self.provider([{'role': 'system', 'content': 'private context'}], [])
                return {'answer': 'example', 'tool_uses': [{'name': 'diary_write', 'ok': False,
                        'error': 'tool not offered in this request'}]}
        provider = AsyncMock(return_value={'content': 'example'})
        with ExitStack() as stack:
            stack.enter_context(patch('tools.persona_regression.preflight', return_value={'root': 'local'}))
            stack.enter_context(patch('tools.persona_live_safety.endpoint_process_evidence', return_value={'lora':'test.gguf'}))
            stack.enter_context(patch('tools.persona_live_safety.adapter_api_evidence', return_value={'lora':'test.gguf'}))
            stack.enter_context(patch('tools.persona_regression._sandbox_writes', return_value={}))
            stack.enter_context(patch('tools.persona_regression._restore_writes'))
            stack.enter_context(patch('tools.persona_regression._kill_llm_fallback', return_value='original'))
            stack.enter_context(patch('backend.target_daemon.LOCAL_BASE', 'original'))
            stack.enter_context(patch('backend.target_memory.TargetMemoryService'))
            stack.enter_context(patch('backend.target_kw_index.KeywordIndex'))
            stack.enter_context(patch('backend.target_entry.ConversationSession', FakeSession))
            factory = stack.enter_context(patch('backend.target_orchestrator.build_openai_compatible_llm_turn', return_value=provider))
            bank = [{'id': 'sample', 'q': 'hello', 'cat': '关系', 'public': True}]
            answers, env = await run_live(bank, base_url='http://127.0.0.1:18081/v1/chat/completions', expect_lora='test.gguf')
        self.assertEqual(factory.call_args.kwargs['base_url'], 'http://127.0.0.1:18081/v1/chat/completions')
        self.assertIsNone(factory.call_args.kwargs['fallback_base_url'])
        self.assertEqual(policies, [(True, frozenset({'web_search', 'web_fetch'}))])
        self.assertEqual(answers[0]['tool_trace'][0]['ok'], False)
        self.assertEqual(env['policy_mode'], 'production')
        self.assertNotIn('private context', json.dumps(env))
        self.assertEqual(len(env['inference_requests']), 1)


if __name__ == '__main__':
    unittest.main()
