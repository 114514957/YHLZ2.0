"""Safety controls tested with fake inference and temporary data only."""
import asyncio
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from tools.persona_live_safety import (
    EvaluationGuard, IsolatedRuntime, cancel_evaluation_tasks,
    endpoint_process_evidence, local_endpoint,
)

URL = 'http://127.0.0.1:18081/v1/chat/completions'

class EndpointIdentityTests(unittest.TestCase):
    def test_literal_loopback_only(self):
        for url in ['https://127.0.0.1:80/v1/chat/completions',
                    'http://example.com/v1/chat/completions',
                    'http://localhost:80/v1/chat/completions',
                    'http://user:secret@127.0.0.1/v1/chat/completions',
                    URL+'?token=secret', URL+'#x', URL+'/other']:
            with self.subTest(url=url), self.assertRaises(RuntimeError):
                local_endpoint(url)
        self.assertEqual(local_endpoint(URL)['port'], 18081)
        self.assertEqual(local_endpoint('http://[::1]:8081/v1/chat/completions')['host'], '::1')

    def proc(self, pid, argv=None):
        return SimpleNamespace(pid=pid, cmdline=lambda: argv or [
            r'C:\llama\llama-server.exe','--lora',r'C:\models\v8.gguf',
            '-m',r'C:\models\base.gguf'], create_time=lambda:123.)

    def conn(self, pid=42, port=18081, host='127.0.0.1'):
        return SimpleNamespace(pid=pid, status='LISTEN', laddr=(host,port))

    def test_binds_pid_to_requested_port_not_first_process(self):
        evidence=endpoint_process_evidence(URL, connections=[self.conn(99,8081),self.conn()], process_factory=self.proc)
        self.assertEqual(evidence['pid'],42)
        self.assertEqual(evidence['lora'],'v8.gguf')
        self.assertFalse(evidence['loaded_adapter_verified'])
        self.assertNotIn('C:\\models',str(evidence))

    def test_missing_ambiguous_and_inaccessible_pid_fail(self):
        for connections in [[],[self.conn(None)],[self.conn(1),self.conn(2)]]:
            with self.subTest(connections=connections),self.assertRaises(RuntimeError):
                endpoint_process_evidence(URL, connections=connections, process_factory=self.proc)

    def test_non_llama_and_multi_adapter_fail(self):
        for argv in [['python.exe'], ['llama-server.exe'],
                     ['llama-server.exe','--lora','a','--lora','b'],
                     ['llama-server.exe','--lora','a','--lora-scaled','b','0.5']]:
            with self.subTest(argv=argv), self.assertRaises(RuntimeError):
                endpoint_process_evidence(URL,connections=[self.conn()],process_factory=lambda pid:self.proc(pid,argv))

    def test_equal_syntax_supported(self):
        value=endpoint_process_evidence(URL,connections=[self.conn()],process_factory=lambda pid:self.proc(pid,[
            'llama-server.exe','--lora=x.gguf','--model=b.gguf']))
        self.assertEqual(value['lora'],'x.gguf')

class GuardTests(unittest.TestCase):
    def setUp(self):
        self.root=Path(tempfile.mkdtemp())
        self.guard=EvaluationGuard(self.root/'sandbox',URL,code_roots=(self.root/'code',), runtime_roots=(self.root/'runtime',))
        self.guard.active=True  # direct checks, not globally installed

    def test_sandbox_write_and_db_allowed(self):
        self.guard.check('open',(self.root/'sandbox'/'x','w',os.O_CREAT))
        self.guard.check('sqlite3.connect',(str(self.root/'sandbox'/'db'),))
        self.guard.check('sqlite3.connect',(':memory:',))

    def test_private_read_and_db_rejected(self):
        for event,args in [('open',(self.root/'private.json','r',0)),
                           ('sqlite3.connect',(str(self.root/'prod.db'),)),
                           ('sqlite3.connect',('file:prod.db?mode=ro',))]:
            with self.assertRaises(PermissionError):self.guard.check(event,args)
        with self.assertRaises(RuntimeError):self.guard.assert_clean()

    def test_only_source_files_allowed_in_code_root(self):
        self.guard.check('open',(self.root/'code'/'x.py','r',0))
        with self.assertRaises(PermissionError):self.guard.check('open',(self.root/'code'/'secret.json','r',0))
        with self.assertRaises(PermissionError):self.guard.check('open',(self.root/'code'/'x.py','w',os.O_WRONLY))

    def test_traversal_rejected(self):
        with self.assertRaises(PermissionError):self.guard.check('open',(self.root/'sandbox'/'..'/'private.json','r',0))

    def test_write_rename_targets_both_checked(self):
        with self.assertRaises(PermissionError):self.guard.check('os.rename',(self.root/'sandbox'/'a',self.root/'prod','-1','-1'))

    def test_network_only_exact_model_address(self):
        self.guard.check('socket.connect',(None,('127.0.0.1',18081)))
        for addr in [('127.0.0.1',8081),('8.8.8.8',18081),('localhost',18081)]:
            with self.assertRaises(PermissionError):self.guard.check('socket.connect',(None,addr))
        with self.assertRaises(PermissionError):self.guard.check('socket.getaddrinfo',('example.com',80))

    def test_children_links_model_import_denied(self):
        for event,args in [('subprocess.Popen',()),('os.system',()),('os.symlink',()),
                           ('import',('torch',)),('socket.bind',())]:
            with self.assertRaises(PermissionError):self.guard.check(event,args)

    def test_log_omits_secrets(self):
        with self.assertRaises(PermissionError):self.guard.check('open',(self.root/'PRIVATE_SECRET','r',0))
        self.assertNotIn('PRIVATE_SECRET',str(self.guard.violations))

    def test_inactive_guard_does_not_affect_later_work(self):
        self.guard.active=False
        self.guard.check('subprocess.Popen',())
        self.assertEqual(self.guard.violations,[])

class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_cleanup_joins_tasks_before_restore(self):
        from backend import target_style
        original=target_style.STYLE_COUNTS
        root=Path(tempfile.mkdtemp())
        observed=[]
        async with IsolatedRuntime(root,URL) as runtime:
            async def worker():
                try:await asyncio.sleep(10)
                finally:
                    observed.append(target_style.STYLE_COUNTS)
                    target_style.STYLE_COUNTS.write_text('fixture',encoding='utf-8')
            task=asyncio.create_task(worker())
            await asyncio.sleep(0)
        self.assertTrue(task.cancelled())
        self.assertEqual(observed,[(root/'style.json').resolve()])
        self.assertEqual(target_style.STYLE_COUNTS,original)
        self.assertFalse(runtime.guard.active)

    async def test_error_restores_environment(self):
        from backend import target_style
        original=target_style.STYLE_COUNTS
        with self.assertRaises(ValueError):
            async with IsolatedRuntime(Path(tempfile.mkdtemp()),URL):
                raise ValueError('expected')
        self.assertEqual(target_style.STYLE_COUNTS,original)

    async def test_swallowed_violation_invalidates_run(self):
        root=Path(tempfile.mkdtemp())
        with self.assertRaises(RuntimeError):
            async with IsolatedRuntime(root,URL):
                try:(root.parent/'not-permitted.txt').read_text()
                except PermissionError:pass

    async def test_real_session_fake_inference_has_no_private_io(self):
        from tools.persona_regression import run_live
        identity={'lora':'test.gguf'}
        with patch('tools.persona_regression.preflight',return_value={}), \
             patch('tools.persona_live_safety.endpoint_process_evidence',return_value=identity), \
             patch('tools.persona_live_safety.adapter_api_evidence',return_value=identity), \
             patch('backend.target_orchestrator.build_openai_compatible_llm_turn',return_value=AsyncMock(return_value={'role':'assistant','content':'我是元亨。'})):
            from tools.persona_bank import PERSONA_BANK
            answers,env=await run_live(PERSONA_BANK,base_url=URL,expect_lora='test.gguf')
        self.assertEqual(len(answers), 48)
        self.assertEqual(env['isolation']['guard_violations'],[])
        self.assertFalse(env['acceptance'])



class MultiTurnHarnessTests(unittest.IsolatedAsyncioTestCase):
    async def test_followup_retains_history_and_splits_evidence(self):
        from tools.persona_regression import run_live
        calls=[]
        async def fake(messages,schemas):
            calls.append([dict(m) for m in messages])
            return {'role':'assistant','content':'验收回答'}
        identity={'lora':'test.gguf'}
        with patch('tools.persona_regression.preflight',return_value={}), \
             patch('tools.persona_live_safety.endpoint_process_evidence',return_value=identity), \
             patch('tools.persona_live_safety.adapter_api_evidence',return_value=identity), \
             patch('backend.target_orchestrator.build_openai_compatible_llm_turn',return_value=fake):
            answers,env=await run_live([{'id':'first','cat':'fixture','q':'我是路过的旅人',
                'public':True,'followups':[{'id':'second','q':'刚才我说了什么？'}]}],base_url=URL,expect_lora='test.gguf')
        self.assertEqual([a['id'] for a in answers],['first','second'])
        self.assertEqual([r['id'] for r in env['inference_requests']],['first','second'])
        self.assertTrue(any('路过的旅人' in str(m.get('content')) for m in calls[1][1:]))
        self.assertEqual([len(a['policy_trace']) for a in answers],[1,1])
        self.assertTrue(all(not a['tools'] for a in answers))


class OptionalTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_optional_transport_uses_asyncio_without_directory_scan(self):
        import sys
        from httpcore._synchronization import current_async_library
        root=Path(tempfile.mkdtemp())
        with patch('importlib.util.find_spec',return_value=None):
            async with IsolatedRuntime(root,URL):
                self.assertIsNone(sys.modules.get('sniffio'))
                for _ in range(3):
                    self.assertEqual(current_async_library(),'asyncio')


class NativeToolSandboxTests(unittest.IsolatedAsyncioTestCase):
    async def test_native_writes_execute_in_isolation(self):
        from tools.persona_regression import run_live
        import json
        cases=[
            ('memory_save', {'content':'验收夹具喜欢蓝色','kind':'preference'}),
            ('diary_write', {'content':'验收夹具：今天看见云。'}),
            ('task_plan', {'content':'验收夹具：整理笔记'}),
            ('schedule_plan', {'action':'add','name':'验收夹具提醒','time':'10:00','cadence':'daily','steps':'回看笔记'}),
            ('kb_add', {'summary':'验收夹具知识条目内容','category':'tech','content':'仅用于测试'}),
            ('memory_recall', {'query':'验收夹具'}),
            ('kb_query', {'query':'验收夹具'}),
            ('diary_list', {}),
            ('system_time', {}),
        ]
        for tool,args in cases:
            with self.subTest(tool=tool):
                async def fake(messages, schemas):
                    if messages[-1]['role']=='tool':
                        return {'role':'assistant','content':'按执行结果回复。'}
                    if tool == 'kb_query':
                        from backend.yuanheng_kb import kb_add
                        kb_add('验收夹具知识条目内容',category='tech')
                    return {'role':'assistant','content':'','tool_calls':[{'id':'fixture',
                            'type':'function','function':{'name':tool,'arguments':json.dumps(args,ensure_ascii=False)}}]}
                with patch('tools.persona_regression.preflight',return_value={}), \
                     patch('tools.persona_live_safety.endpoint_process_evidence',return_value={'lora':'x.gguf'}), \
                     patch('tools.persona_live_safety.adapter_api_evidence',return_value={'lora':'x.gguf'}), \
                     patch('backend.target_orchestrator.build_openai_compatible_llm_turn',return_value=fake):
                    answers, env=await run_live([{'id':tool,'q':'安排验收夹具任务','cat':'工具遵循'}],base_url=URL,expect_lora='x.gguf')
                self.assertEqual(env['isolation']['guard_violations'],[])
                self.assertEqual(answers[0]['tools'],[tool])
                self.assertTrue(answers[0]['tool_trace'][0]['ok'],answers[0])
                if tool in {'memory_save','diary_write','task_plan','schedule_plan','kb_add'}:
                    self.assertEqual(answers[0]['effect_receipts'][0]['status'], 'verified_in_fixture', answers[0])

class AdapterApiTests(unittest.TestCase):
    def test_enabled_single_adapter_verified(self):
        import json
        from unittest.mock import MagicMock
        from tools.persona_live_safety import adapter_api_evidence
        response=MagicMock()
        response.__enter__.return_value.read.return_value=json.dumps([{'path':r'C:\\models\\v8.gguf','scale':1.0,'id':0}]).encode()
        with patch('urllib.request.build_opener') as build:
            build.return_value.open.return_value=response
            result=adapter_api_evidence(URL,'v8.gguf')
        self.assertTrue(result['loaded_adapter_verified'])
        self.assertNotIn('models',str(result))

    def test_disabled_or_wrong_adapter_refused(self):
        import json
        from unittest.mock import MagicMock
        from tools.persona_live_safety import adapter_api_evidence
        for values in [[],[{'path':'v8.gguf','scale':0,'id':0}],
                       [{'path':'other.gguf','scale':1,'id':0}],
                       [{'path':'v8.gguf','scale':1,'id':0}]*2]:
            response=MagicMock()
            response.__enter__.return_value.read.return_value=json.dumps(values).encode()
            with patch('urllib.request.build_opener') as build:
                build.return_value.open.return_value=response
                with self.assertRaises(RuntimeError):adapter_api_evidence(URL,'v8.gguf')


if __name__ == "__main__":
    unittest.main()
