"""Real thread teardown with fake harness and temporary state; no live tools."""
import io
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
TOOLS=Path(__file__).resolve().parents[1]/'tools'
if str(TOOLS) not in sys.path:sys.path.insert(0,str(TOOLS))
import dsh_worker as resident
import qq_dev_worker as worker
import harness_gateway as gw

class ResidentCleanupTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.patchers=[patch.object(resident,'JOBS_DIR',self.root/'jobs'),
                       patch.object(resident,'_log'),patch.object(resident,'_jobs',{}),
                       patch.object(resident,'_job_threads',{}),patch.object(resident,'_harness_pool',{})]
        for p in self.patchers:p.start()
        self.addCleanup(lambda:[p.stop() for p in reversed(self.patchers)])
    def run_thread(self,harness):
        workspace=str(self.root.resolve())
        resident._job_update('job1',state='running',session='job1',workspace=workspace)
        resident._harness_pool[workspace]=harness
        thread=threading.Thread(target=resident._run_job,args=('job1',workspace,'fixture','fixture'))
        resident._job_threads['job1']=thread
        thread.start();thread.join(timeout=5)
        self.assertFalse(thread.is_alive());self.assertNotIn('job1',resident._job_threads)
        return resident._job_get('job1')
    def test_failure_closes_runtime_and_clears_session_and_thread(self):
        h=Mock(run=Mock(side_effect=RuntimeError('fixture failed')))
        result=self.run_thread(h)
        self.assertEqual(result['state'],'error');self.assertEqual(result['session'],'')
        self.assertTrue(result['cleanup_confirmed']);self.assertEqual(resident._harness_pool,{})
        h.close.assert_called_once()
    def test_cancel_cannot_be_overwritten_by_late_success(self):
        def late(*a,**k):
            resident._job_update('job1',state='cancelled')
            return SimpleNamespace(final_response='[DONE] late')
        result=self.run_thread(Mock(run=Mock(side_effect=late)))
        self.assertEqual(result['state'],'cancelled');self.assertEqual(result['session'],'')
        self.assertEqual(resident._harness_pool,{})
    def test_failed_close_is_observable_instead_of_discarded(self):
        h=Mock(run=Mock(side_effect=RuntimeError()),close=Mock(side_effect=RuntimeError()))
        result=self.run_thread(h)
        self.assertFalse(result['cleanup_confirmed']);self.assertEqual(result['state'],'error')
        self.assertIn(str(self.root.resolve()),resident._harness_pool)
    def test_failed_job_cannot_resume(self):
        resident._job_update('old',state='error',session='',workspace=str(self.root))
        self.assertFalse(resident.job_answer({'job_id':'old','text':'继续'})['ok'])

class TransportCleanupTests(unittest.TestCase):
    def test_transport_exception_still_disposes_workspace(self):
        with patch.object(gw,'ensure',return_value=True), \
             patch.object(gw,'run_job',side_effect=ConnectionError()), \
             patch.object(gw,'post',return_value={'ok':True}) as dispose:
            result=worker._harness_execute({'job_id':'j','workspace':'isolated'},'start',1,io.StringIO())
        self.assertEqual(result['state'],'error');self.assertEqual(result['session'],'')
        dispose.assert_called_once_with('/job/dispose',{'workspace':'isolated'},timeout=30.0)
