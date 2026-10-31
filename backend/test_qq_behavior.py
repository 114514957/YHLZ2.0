"""QQ work state, recipient gate, main-memory social evidence (isolated)."""
import asyncio
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from backend.qq_behavior import command_not_for_bot
from backend.qq_main_memory import QqMainMemory
from backend.target_entry import is_owner_channel
from backend.channel_auth import is_owner_channel as is_auth_owner
from tools import qq_bot as qq


class RecipientTests(unittest.TestCase):
    def test_other_persons_command_silent(self):
        self.assertTrue(command_not_for_bot('请重启服务', ['901'], '900', ('元亨',), owner_command=False))
        self.assertFalse(command_not_for_bot('请重启服务', ['900'], '900', ('元亨',)))
        self.assertTrue(command_not_for_bot('小明，帮我检查服务', [], '900', ('元亨',)))
        self.assertFalse(command_not_for_bot('晚上好', ['901'], '900', ('元亨',)))
        self.assertFalse(command_not_for_bot('#dev 修bug', [], '900', ('元亨',), owner_command=True))

    def test_private_stranger_never_sees_owner_memory(self):
        for checker in (is_owner_channel, is_auth_owner):
            self.assertFalse(checker('qq_p123456789'))
            self.assertTrue(checker('qq_p2258374446'))


class OwnerWorkTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.state = {}
        self.patchers = [patch.object(qq,'_load_state',side_effect=lambda:self.state),
                         patch.object(qq,'_save_state',side_effect=lambda new:self.state.update(new)),
                         patch.object(qq,'_lite_dev', Mock(awaiting_job=lambda *a,**k:None)),
                         patch.object(qq,'_allowed_groups',return_value=None),
                         patch.object(qq,'_bridge_profile',return_value='lite')]
        for p in self.patchers:p.start()
        self.bridge = qq.QQBridge('unused','900',Path('unused'),masters={'100'})
        self.bridge._group_db = Mock(return_value=Mock(add=lambda **k:1, context_block=lambda *a,**k:{}))
        self.bridge._main_social = Mock(return_value=Mock(observe=Mock(return_value=None)))
        self.bridge._say = AsyncMock()
        self.bridge._deliver = AsyncMock()
        self.bridge._dev_cmd = AsyncMock()
        self.bridge._save_group_daily = Mock()
        self.bridge._daemon_ok = lambda:True
        self.ws=Mock(send=AsyncMock())

    async def asyncTearDown(self):
        for p in reversed(self.patchers):p.stop()

    def event(self, mid, sender='100', text='hello', target=None):
        segs=[{'type':'text','data':{'text':text}}]
        if target:segs.append({'type':'at','data':{'qq':target}})
        return {'post_type':'message','message_type':'group','group_id':'123',
                'user_id':sender,'message_id':mid,'message':segs}

    async def test_owner_work_does_not_dispatch_plain_followup(self):
        # 0830：旧行为把 follow-up 拼成 `#dev 原文` 二次派单，导致
        # "#退出任务 后依然在派单"；现在普通聊天只走对话，派单必须显式 #dev。
        await self.bridge.handle(self.ws, self.event(1, text='#任务派发 修复问题'))
        self.assertTrue(self.state['owner_work']['100']['enabled'])
        await self.bridge.handle(self.ws, self.event(2, text='继续处理'))
        self.assertEqual(self.bridge._dev_cmd.await_count, 1)
        await self.bridge.handle(self.ws, self.event(3, text='#退出任务'))
        self.assertFalse(self.state['owner_work']['100']['enabled'])

    async def test_release_bypasses_old_waiting_job(self):
        from backend.qq_behavior import set_work
        self.state.update(set_work(self.state, '100', False, 'qq_g123'))
        self.bridge._daemon_ok = lambda:False
        waiting = Mock(awaiting_job=Mock(return_value={'job_id':'old'}))
        with patch.object(qq,'_lite_dev',waiting):
            await self.bridge.handle(self.ws,self.event(41,text='晚上好'))
        waiting.awaiting_job.assert_not_called()
        self.bridge._dev_cmd.assert_not_awaited()

    async def test_command_to_other_stored_but_no_reply(self):
        with patch.object(qq,'_daemon_turn') as model:
            await self.bridge.handle(self.ws,self.event(4,sender='222',text='请重启服务',target='901'))
        model.assert_not_called()
        self.bridge._dev_cmd.assert_not_awaited()
        self.bridge._say.assert_not_awaited()
        self.bridge._main_social.return_value.observe.assert_called_once()

    async def test_other_group_member_quiet_during_owner_work(self):
        await self.bridge.handle(self.ws,self.event(5,text='#dev 修复'))
        with patch.object(qq,'_daemon_turn') as model:
            await self.bridge.handle(self.ws,self.event(6,sender='222',text='元亨 你好',target='900'))
        model.assert_not_called()
        self.bridge._main_social.return_value.observe.assert_called()


class SocialEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=QqMainMemory(Path(self.tmp.name)/'main.db')

    def event(self,group,mid,sender,text,target=''):
        msg=[{'type':'text','data':{'text':text}}]
        if target: msg.append({'type':'at','data':{'qq':target}})
        return {'message_type':'group','group_id':group,'message_id':mid,
                'user_id':sender,'sender':{'nickname':'群友甲'},'message':msg}

    def test_group_isolation_provenance_dedup_and_owner_context(self):
        e=self.event('123','m1','123456','只在甲群谈模型','888888')
        self.store.observe(e,'900');self.store.observe(e,'900')
        self.store.observe(self.event('456','m2','123456','只在乙群谈绘画'),'900')
        self.assertIn('只在甲群',self.store.context('[QQ群发言者 user_id=123456]','qq_g123'))
        self.assertNotIn('只在乙群',self.store.context('[QQ群发言者 user_id=123456]','qq_g123'))
        self.assertIn('只在乙群',self.store.context('人际 123456','console'))
        self.assertEqual(self.store.context('人际 123456','qq_p99999999'),'')
        con=sqlite3.connect(self.store.path)
        self.assertEqual(con.execute('select count(*) from qq_social_events').fetchone()[0],2)
        self.assertEqual(con.execute('select messages from qq_social_people where group_id=123').fetchone()[0],1)
        self.assertEqual(con.execute('select count(*) from qq_social_edges').fetchone()[0],1)
        con.close()

    def test_profile_derived_links_are_owner_only(self):
        import sqlite3
        p=Path(self.tmp.name)/'profiles.db'
        con=sqlite3.connect(p)
        con.execute('CREATE TABLE members(qq TEXT,inter_json TEXT)')
        con.execute('INSERT INTO members VALUES (?,?)',('123456',json.dumps([{'qq':'888888','score':4}])))
        con.commit();con.close()
        self.store.observe(self.event('123','m1','123456','你好'),'900')
        self.assertEqual(self.store.backfill_profile_edges(p),1)
        self.assertEqual(self.store.backfill_profile_edges(p),0)
        self.assertIn('derived_interaction',self.store.context('人际 123456','console'))
        self.assertNotIn('derived_interaction',self.store.context('user_id=123456','qq_g123'))

    def test_different_recipient_command_is_only_evidence(self):
        self.store.observe(self.event('123','m1','123456','请重启服务','999999'),'900')
        self.assertNotIn('请重启服务',self.store.context('元亨','qq_g456'))
