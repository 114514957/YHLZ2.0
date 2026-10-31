import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from backend.target_memory import TargetMemoryService
from backend.memory_health import snapshot
from backend.memory_carriers import CarrierEvidence, CarrierOrigin

class HealthTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name); self.db=self.root/'memory.db'
        self.mem=TargetMemoryService(db_path=self.db,l1_scope='console',window_turns=1)

    def test_counts_no_private_text_and_no_new_tables(self):
        self.mem.append_turn(role='user',text='secret-private-first')
        self.mem.append_turn(role='assistant',text='secret-private-second')
        before=hashlib.sha256(self.db.read_bytes()).hexdigest()
        report=snapshot(self.db,kw_db_path=self.mem._kw.db_path)
        self.assertTrue(report['ok']); self.assertEqual(report['l1'][0]['pending_count'],1)
        self.assertFalse(report['carriers']['initialized'])
        self.assertNotIn('secret-private',json.dumps(report))
        self.assertEqual(before,hashlib.sha256(self.db.read_bytes()).hexdigest())

    def test_missing_database_not_created(self):
        missing=self.root/'missing.db'
        self.assertFalse(snapshot(missing)['ok'])
        self.assertFalse(missing.exists())

    def test_corruption_does_not_get_repaired_or_echoed(self):
        raw=b'{private-corruption'
        self.mem._l1_path().write_bytes(raw)
        report=snapshot(self.db)
        self.assertFalse(report['ok']); self.assertFalse(report['l1'][0]['valid'])
        self.assertNotIn('private-corruption',json.dumps(report))
        self.assertEqual(self.mem._l1_path().read_bytes(),raw)

    def test_foreign_scope_is_reported(self):
        self.mem._l1_path().write_text(json.dumps({'scope':'other','turns':[],'pending':[]}),encoding='utf-8')
        self.assertFalse(snapshot(self.db)['l1'][0]['valid'])

    def test_pending_carrier_requires_reconciliation(self):
        CarrierEvidence(self.db).begin(CarrierOrigin('console','diary',True),content='private',operation='write')
        report=snapshot(self.db)
        self.assertFalse(report['ok'])
        self.assertEqual(report['carriers']['pending_reconciliation'],1)
        self.assertFalse(report['automatic_replay'])
        self.assertNotIn('private',json.dumps(report))

    def test_missing_index_not_created_by_readonly_audit(self):
        path=self.root/'absent-kw.db'
        report=snapshot(self.db,kw_db_path=path)
        self.assertFalse(report['ok']); self.assertFalse(path.exists())

class MCPBindingTests(unittest.IsolatedAsyncioTestCase):
    async def test_ledger_dispatch_does_not_construct_memory(self):
        from tools import yhlz_mcp_server as server
        from unittest.mock import AsyncMock
        with patch.object(server,'_registry') as registry, \
             patch.object(server,'_ensure_carriers_bound',side_effect=AssertionError('memory construction')):
            registry.execute_openai_async=AsyncMock(return_value={'ok':True,'output':'synthetic'})
            self.assertEqual(await server._call_async('ledger_search',{'query':'synthetic'}),'synthetic')

    async def test_mutations_bind_once_with_owner_local_origin(self):
        from tools import yhlz_mcp_server as server
        from unittest.mock import Mock
        service=Mock()
        with patch.object(server,'_carriers_bound',False), \
             patch('backend.target_memory.TargetMemoryService',return_value=service) as build, \
             patch('backend.memory_carriers.bind_memory_carriers') as bind:
            server._ensure_carriers_bound(); server._ensure_carriers_bound()
            build.assert_called_once_with(l1_scope='mcp')
            bind.assert_called_once_with(server._registry,service,channel='owner_local',owner_access=True)

    async def test_mcp_write_uses_evidence_handler_in_temporary_store(self):
        from tools import yhlz_mcp_server as server
        from backend.target_scheduler_tools import setup_scheduler_capabilities
        from backend.memory_carriers import CarrierEvidence
        with tempfile.TemporaryDirectory() as td:
            service=TargetMemoryService(db_path=Path(td)/'memory.db',l1_scope='mcp')
            registry=setup_scheduler_capabilities()
            with patch.object(server,'_registry',registry), patch.object(server,'_carriers_bound',False), \
                 patch('backend.target_memory.TargetMemoryService',return_value=service), \
                 patch('backend.target_scheduler_tools.DIARY_FILE',Path(td)/'diary.md'):
                output=await server._call_async('diary_write',{'content':'synthetic diary entry'})
                self.assertTrue(output.startswith('已'))
                events=CarrierEvidence(service.db_path).list()
                self.assertEqual(len(events),1)
                self.assertEqual(events[0]['state'],'committed')
                self.assertEqual(events[0]['channel'],'owner_local')
