"""Offline carrier evidence and identity contracts; only temporary stores."""
from contextlib import closing
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from backend.memory_carriers import CarrierEvidence, CarrierOrigin, bind_memory_carriers
from backend.target_capability_registry import Capability, CapabilityRegistry
from backend.target_memory import TargetMemoryService
from backend import target_scheduler_tools as tools


class CarrierTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.mem = TargetMemoryService(db_path=self.root / 'mem.db')
        self.journal = CarrierEvidence(self.mem.db_path, timeout_s=.02)
        self.origin = CarrierOrigin('console', 'memory', True)

    def registry(self, name, handler, *, channel='console', owner=True):
        r = CapabilityRegistry()
        cap = Capability(name, handler, input=('content',), optional_input=('source',),
                         requires=('owner.approval',), side_effect=True, risk='high',
                         timeout_ms=1200, description='retained description')
        r.register_capability(cap)
        bind_memory_carriers(r, self.mem, channel=channel, owner_access=owner)
        return r, cap

    def test_schedule_read_is_not_mutation_evidence(self):
        fn=Mock(return_value='计划列表')
        r,_=self.registry('schedule.plan',fn)
        r.get('schedule.plan').handler({'action':'list'})
        self.assertEqual(self.journal.list(),[])
        fn.assert_called_once()

    def test_schedule_write_is_attributed_and_arguments_hashed(self):
        r,_=self.registry('schedule.plan',Mock(return_value='已加入计划表'))
        r.get('schedule.plan').handler({'action':'add','name':'fixture_private_name','time':'10:30','steps':'step'})
        rows=self.journal.list()
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['state'],'committed')
        self.assertIn('schedule',str(rows))
        self.assertNotIn('fixture_private_name',str(rows))

    def test_group_label_cannot_be_promoted_to_owner(self):
        for channel in ['qq_g123456', 'public', '../console']:
            with self.assertRaises(ValueError): CarrierOrigin(channel, 'memory', True)

    def test_unknown_carrier_refused(self):
        with self.assertRaises(ValueError): CarrierOrigin('console', 'persona', True)

    def test_kb_diary_plan_not_owner_facts_or_persona(self):
        for carrier in ['kb', 'diary', 'plan']:
            o = CarrierOrigin('console', carrier, True)
            self.assertEqual(o.source, 'agent'); self.assertEqual(o.stance, 'opinion')
        self.assertEqual(CarrierOrigin('console', 'kb', True).scope, 'knowledge')

    def test_no_raw_secret_in_evidence_and_pending_survives_restart(self):
        text = 'api_key=private-sensitive-value'
        event = self.journal.begin(self.origin, content=text, operation='save', observed_at=1700000000)
        rows = CarrierEvidence(self.mem.db_path).list()
        self.assertEqual(rows[0]['trace_id'], event['trace_id'])
        self.assertNotIn(text, str(rows)); self.assertEqual(rows[0]['content_chars'], len(text))
        self.assertEqual(self.journal.health()['pending_reconciliation'], 1)
        self.assertFalse(self.journal.health()['automatic_replay'])

    def test_finish_is_terminal(self):
        e = self.journal.begin(self.origin, content='fact', operation='save')
        self.journal.finish(e['trace_id'], state='committed')
        with self.assertRaises(RuntimeError): self.journal.finish(e['trace_id'], state='committed')

    def test_public_begin_refused_before_write(self):
        with self.assertRaises(PermissionError):
            self.journal.begin(CarrierOrigin('qq_g123456','memory',False), content='no',operation='save')
        self.assertEqual(self.journal.list(), [])

    def test_channel_query_is_exact_and_bound(self):
        self.journal.begin(self.origin, content='private', operation='save')
        self.assertEqual(self.journal.list(channel="console' OR 1=1--"), [])

    def test_sqlite_busy_retains_prior_journal_without_new_intent(self):
        lock = sqlite3.connect(str(self.mem.db_path)); lock.execute('BEGIN IMMEDIATE')
        try:
            with self.assertRaises(sqlite3.OperationalError):
                self.journal.begin(self.origin, content='busy', operation='save')
        finally: lock.rollback(); lock.close()
        self.assertEqual(self.journal.list(), [])

    def test_preserves_capability_approval_and_description(self):
        r, cap = self.registry('diary.write', Mock(return_value='已写入'))
        new = r.get('diary.write')
        for key in ['requires','risk','description','timeout_ms','side_effect','input','optional_input']:
            self.assertEqual(getattr(cap,key),getattr(new,key))

    def test_accidentally_exposed_group_write_denied(self):
        fn = Mock(return_value='已写入')
        r, _ = self.registry('diary.write', fn, channel='qq_g123456', owner=False)
        with self.assertRaises(PermissionError): r.get('diary.write').handler({'content':'external'})
        fn.assert_not_called(); self.assertEqual(self.journal.list(), [])

    def test_owner_memory_source_cannot_be_spoofed(self):
        with patch.object(tools,'memory_save',return_value='已保存') as save:
            r, _ = self.registry('memory.save', Mock())
            r.get('memory.save').handler({'content':'owner fact','source':'群聊','profile':True})
        self.assertEqual(save.call_args.kwargs['source'],'owner')
        self.assertTrue(save.call_args.kwargs['evidence_ref'].startswith('carrier:memory:'))
        self.assertEqual(self.journal.list()[0]['state'],'committed')

    def test_real_l2_save_has_linked_evidence_and_profile_compatibility(self):
        with patch.object(tools,'_constitution_check',return_value=(True,'')), \
             patch.object(tools,'_memory_fault_alert'), patch('backend.growth_log.record'):
            r, _ = self.registry('memory.save', Mock())
            out = r.get('memory.save').handler({'content':'我的偏好是可追溯记忆','source':'模型伪造'})
        self.assertTrue(out.startswith('已保存'))
        row = self.mem.profile_get('偏好')[0]
        e = self.journal.list()[0]
        with closing(sqlite3.connect(str(self.mem.db_path))) as con:
            stored = con.execute('SELECT source,evidence_ref FROM l2_items WHERE id=?',(row['id'],)).fetchone()
        self.assertEqual(stored, ('owner',e['evidence_ref']))

    def test_diary_and_plan_actual_files_never_promote_to_l2(self):
        with patch.object(tools,'DIARY_FILE',self.root/'diary.md'), \
             patch.object(tools,'TASK_FILE',self.root/'tasks.md'):
            r, _ = self.registry('diary.write', lambda p: tools.diary_write(p['content']))
            r.get('diary.write').handler({'content':'今天是一次待验证的经历，不是永久人格'})
            p, _ = self.registry('task.plan',lambda p: tools.task_plan(p['content'],p.get('action','add')))
            p.get('task.plan').handler({'content':'完成测试'})
            p.get('task.plan').handler({'content':'完成测试','action':'done'})
            before = len(self.journal.list())
            p.get('task.plan').handler({'content':'','action':'list'})
            self.assertEqual(len(self.journal.list()),before)
        self.assertEqual(self.mem.health()['l2_items'],0)
        self.assertEqual({e['carrier'] for e in self.journal.list()},{'diary','plan'})
        self.assertEqual({e['state'] for e in self.journal.list()},{'committed'})

    def test_kb_stays_separate_and_source_cannot_claim_owner(self):
        from backend import yuanheng_kb as kb
        with patch.object(kb,'DEFAULT_KB_DB',self.root/'kb.db'):
            r, _ = self.registry('kb.add', Mock())
            out = r.get('kb.add').handler({'summary':'SQLite事务要么全部提交要么全部回滚','source':'owner'})
            self.assertTrue(out.startswith('已入库'))
            rows = kb.kb_list(); self.assertTrue(rows[0]['source'].startswith('carrier:kb:'))
        self.assertEqual(self.mem.health()['l2_items'],0)
        self.assertEqual(self.journal.list()[0]['scope'],'knowledge')

    def test_refusal_is_not_success(self):
        r, _ = self.registry('diary.write',Mock(return_value='内容长度需在范围内'))
        r.get('diary.write').handler({'content':''})
        self.assertEqual(self.journal.list()[0]['state'],'refused')

    def test_mutation_failure_records_only_exception_class(self):
        r, _ = self.registry('diary.write',Mock(side_effect=OSError('private key'))) 
        with self.assertRaises(OSError): r.get('diary.write').handler({'content':'diary'})
        row = self.journal.list()[0]
        self.assertEqual(row['state'],'failed'); self.assertEqual(row['error_type'],'OSError')
        self.assertNotIn('private key', str(row))

    def test_commit_confirmation_failure_retains_pending_without_replay(self):
        fn = Mock(return_value='已写入')
        r, _ = self.registry('diary.write',fn)
        with patch.object(CarrierEvidence,'finish',side_effect=sqlite3.OperationalError('busy')):
            out = r.get('diary.write').handler({'content':'diary'})
        self.assertIn('不要自动重试',out); self.assertEqual(fn.call_count,1)
        self.assertEqual(self.journal.list()[0]['state'],'pending')


if __name__=='__main__': unittest.main()
