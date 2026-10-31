"""Execution, action and output boundaries for explicit text operations."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from backend.text_tool_contract import text_tool_contract
from backend.target_orchestrator import TurnOrchestrator, ToolUse

class ContractTests(unittest.TestCase):
    def test_read_of_previously_added_task_does_not_add(self):
        c=text_tool_contract('读取任务表，找到刚才添加的任务。')
        self.assertEqual(c.actions, frozenset({'list'}))
        self.assertFalse(c.accepts('task_plan', {}))

    def test_meta_and_multiple_sources_are_not_claimed_covered(self):
        for q in ['你会不会查台账？','解释台账工具是什么','查台账和知识库','如何修改日记？','删除全部日记']:
            self.assertIsNone(text_tool_contract(q),q)

    def test_explicit_external_reads_cannot_claim_unavailable_results(self):
        for text, tools in [
            ('读取一下 README.md 这个文件。', {'file_read', 'file_list'}),
            ('帮我上网查 llama.cpp 最新版本。', {'web_search', 'web_fetch'}),
            ('看看我有哪些技能。', {'skill_search'}),
        ]:
            contract = text_tool_contract(text)
            self.assertEqual(contract.tools, frozenset(tools))
            self.assertEqual(contract.assess([], {'memory_recall'}), 'unavailable')
            self.assertIn('还没核实', contract.failure_reply('unavailable'))
            self.assertIsNone(contract.initial_call(text))
        for text in ['读取台账文件', '帮我把 target_entry.py 里的错别字改掉。',
                     '如何读取README.md文件？', '解释技能系统是什么']:
            self.assertIsNone(text_tool_contract(text), text)

    def test_memory_miss_is_not_ledger_evidence(self):
        c=text_tool_contract('查台账后告诉我白鹭试验通过了吗？')
        use=ToolUse('memory_recall',{},True,'无结果')
        self.assertEqual(c.assess([use],{'ledger_search'}),'not_executed')
        self.assertEqual(c.assess([use],{'memory_recall'}),'unavailable')

    def test_failed_and_wrong_actions_are_not_success(self):
        c=text_tool_contract('把任务表里的白鹭标记为已完成')
        self.assertEqual(c.assess([ToolUse('task_plan',{'action':'list'},True,'x')],{'task_plan'}),'not_executed')
        self.assertEqual(c.assess([ToolUse('task_plan',{'action':'done'},False)],{'task_plan'}),'execution_failed')

    def test_handler_no_match_is_not_completed_write(self):
        c=text_tool_contract('把任务表里的白鹭标记为已完成')
        u=ToolUse('task_plan',{'action':'done'},True,'没找到含该内容的未完成任务')
        self.assertEqual(c.assess([u],{'task_plan'}),'effect_unconfirmed')

    def test_runtime_questions_cannot_invent_telemetry_tools(self):
        for q in ['夜里很安静，你的进程是不是也跟着慢下来了？',
                  '你刚才是不是已经自己训练升级了一次？',
                  '你的进程现在运行得快吗？', '你有没有自动训练？']:
            contract = text_tool_contract(q)
            self.assertEqual(contract.source, '运行状态', q)
            self.assertFalse(contract.tools)
            self.assertEqual(contract.assess([], []), 'unavailable')

    def test_runtime_boundary_does_not_capture_design_or_fiction(self):
        for q in ['如何设计自动训练？', '如果你自己训练了会怎样？',
                  '写个你的进程变慢的故事', '#dev 设计自动训练',
                  '你会训练模型吗？', '夜里很安静，陪我一会儿。']:
            self.assertIsNone(text_tool_contract(q), q)

    def test_literal_knowledge_write_preserves_user_content(self):
        q='把以下知识存入知识库：验收夹具中的青鸟编号为四十二号。'
        self.assertEqual(text_tool_contract(q).initial_call(q),
            ('kb_add', {'summary':'验收夹具中的青鸟编号为四十二号。'}))
        q='把我刚才说的知识总结后存入知识库'
        self.assertIsNone(text_tool_contract(q).initial_call(q))

    def test_deterministic_reads_and_literal_done(self):
        self.assertEqual(text_tool_contract('读取最近一条日记').initial_call('读取最近一条日记')[0], 'diary_list')
        self.assertEqual(text_tool_contract('读取任务表').initial_call('读取任务表')[1]['action'], 'list')
        q='把任务表里的白鹭标记为已完成。'
        self.assertEqual(text_tool_contract(q).initial_call(q), ('task_plan', {'action':'done','content':'白鹭'}))
        q='把任务表里的全部标记为已完成。'
        self.assertIsNone(text_tool_contract(q).initial_call(q))

class LoopTests(unittest.IsolatedAsyncioTestCase):
    async def test_one_correction_then_success_without_replaying_write(self):
        from backend.target_capability_registry import CapabilityRegistry, Capability
        registry=CapabilityRegistry();calls=[]
        registry.register_capability(Capability(name='task.plan',description='test',handler=lambda p:calls.append(p) or 'ok',input=('content',),optional_input=('action',)))
        rounds=[]
        async def model(messages,tools):
            rounds.append(tools)
            if len(rounds)==1:return {'content':'勾掉啦'}
            if len(rounds)==2:return {'tool_calls':[{'id':'a','function':{'name':'task_plan','arguments':'{"action":"done","content":"白鹭"}'}}]}
            return {'content':'完成'}
        result=await TurnOrchestrator(registry).run('勾掉任务表中的白鹭','system',model,text_contract=text_tool_contract('勾掉任务表中的白鹭'))
        self.assertEqual(len(calls),1)
        self.assertEqual(len(rounds),3)
        self.assertTrue(result.tool_uses[0].ok)

    async def test_wrong_action_never_reaches_handler(self):
        from backend.target_capability_registry import CapabilityRegistry, Capability
        registry=CapabilityRegistry();handler=Mock(return_value='ok')
        registry.register_capability(Capability(name='task.plan',description='test',handler=handler,input=('content',),optional_input=('action',)))
        n=0
        async def model(messages,tools):
            nonlocal n;n+=1
            if n==1:return {'tool_calls':[{'id':'a','function':{'name':'task_plan','arguments':'{"action":"add","content":"白鹭"}'}}]}
            return {'content':'完成'}
        contract=text_tool_contract('读取任务表')
        from unittest.mock import patch
        with patch.object(type(contract), 'initial_call', return_value=None):
            result=await TurnOrchestrator(registry).run('查询任务表并确认','system',model,text_contract=contract)
        handler.assert_not_called();self.assertFalse(result.tool_uses[0].ok)

if __name__=='__main__':unittest.main()
