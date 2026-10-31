"""Nonblocking HTTP jobs and trace reporting, no network/voice devices/models."""
import asyncio
import io
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from backend.voice_jobs import VoiceJobs, VoiceJobError
from backend.target_workbench_adapter import WorkbenchTurnResult
from backend.target_voice_api import handle_post, handle_get
from tools.voice_trace_report import summarize

class JobsTests(unittest.IsolatedAsyncioTestCase):
    async def test_submission_returns_before_work_completes(self):
        entered, release = asyncio.Event(), asyncio.Event()
        async def submit(*a, **kw):
            entered.set()
            await release.wait()
            return WorkbenchTurnResult('target','completed',text='hello')
        jobs=VoiceJobs()
        result=jobs.submit(asyncio.get_running_loop(), SimpleNamespace(submit_audio=submit), ['clip'])
        self.assertEqual(result['status'],'queued')
        self.assertIsNone(result['result'])
        await asyncio.wait_for(entered.wait(),1)
        release.set()
        for _ in range(10):
            await asyncio.sleep(0)
            if jobs.get(result['job_id'])['status']=='completed':
                break
        self.assertEqual(jobs.get(result['job_id'])['result']['text'],'hello')
        await jobs.shutdown()

    async def test_cancelled_means_cleanup_finished_not_just_future_cancelled(self):
        entered, cleaning, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
        async def submit(*a, **kw):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleaning.set()
                await release.wait()
        jobs=VoiceJobs()
        loop=asyncio.get_running_loop()
        record=jobs.submit(loop,SimpleNamespace(submit_audio=submit,error_code=None),['clip'])
        await asyncio.wait_for(entered.wait(),1)
        jobs.cancel(loop,record['job_id'])
        await asyncio.wait_for(cleaning.wait(),1)
        self.assertEqual(jobs.get(record['job_id'])['status'],'cancel_requested')
        jobs.cancel(loop,record['job_id']) # repeated cancel must not cut cleanup
        await asyncio.sleep(0)
        self.assertEqual(jobs.get(record['job_id'])['status'],'cancel_requested')
        release.set()
        await jobs.shutdown()
        self.assertEqual(jobs.get(record['job_id'])['status'],'cancelled')

    async def test_cancel_before_dispatch_never_calls_service(self):
        jobs=VoiceJobs()
        service=SimpleNamespace(submit_audio=AsyncMock())
        loop=asyncio.get_running_loop()
        record=jobs.submit(loop,service,['clip'])
        jobs.cancel(loop,record['job_id'])
        await asyncio.sleep(.01)
        self.assertEqual(jobs.get(record['job_id'])['status'],'cancelled')
        service.submit_audio.assert_not_awaited()
        await jobs.shutdown()

    async def test_unconfirmed_service_cleanup_is_failure_not_cancelled(self):
        entered = asyncio.Event()
        service = SimpleNamespace(error_code=None)
        async def submit(*a, **kw):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                service.error_code = 'TARGET-STOP-UNCONFIRMED'
        service.submit_audio = submit
        jobs = VoiceJobs()
        record = jobs.submit(asyncio.get_running_loop(), service, ['clip'])
        await asyncio.wait_for(entered.wait(), 1)
        await jobs.shutdown()
        self.assertEqual(jobs.get(record['job_id'])['status'], 'failed')
        self.assertEqual(jobs.get(record['job_id'])['error_code'], 'TARGET-STOP-UNCONFIRMED')

    async def test_shutdown_queued_job_does_not_wait_for_service(self):
        jobs = VoiceJobs()
        service = SimpleNamespace(submit_audio=AsyncMock())
        record = jobs.submit(asyncio.get_running_loop(), service, ['clip'])
        await jobs.shutdown()
        self.assertEqual(jobs.get(record['job_id'])['status'], 'cancelled')
        await asyncio.sleep(0)
        service.submit_audio.assert_not_awaited()

    async def test_capacity_failure_and_bounded_history(self):
        jobs=VoiceJobs(capacity=1,history_limit=2)
        service=SimpleNamespace(submit_audio=AsyncMock(side_effect=RuntimeError('secret detail')))
        loop=asyncio.get_running_loop()
        first=jobs.submit(loop,service,['clip'])
        with self.assertRaisesRegex(VoiceJobError,'BUSY'):
            jobs.submit(loop,service,['clip'])
        await asyncio.sleep(.01)
        self.assertEqual(jobs.get(first['job_id'])['error_code'],'RuntimeError')
        for _ in range(3):
            jobs.submit(loop,service,['clip'])
            await asyncio.sleep(.01)
        self.assertEqual(len(jobs._records),2)
        with self.assertRaises(KeyError):
            jobs.get(first['job_id'])
        await jobs.shutdown()
        with self.assertRaisesRegex(VoiceJobError,'CLOSED'):
            jobs.submit(loop,service,['clip'])


def handler(path='/voice/submit', address='127.0.0.1'):
    service=SimpleNamespace(health=lambda:{'ready':True})
    return SimpleNamespace(path=path,client_address=(address,123),headers={'Content-Type':'application/json'},
        runtime=SimpleNamespace(_target_voice=service, _ensure_target_voice=Mock(return_value=service),
                                _loop=object(),_voice_jobs=Mock()),_send=Mock())

class APITests(unittest.TestCase):
    def test_submit_is_202_and_does_not_start_a_second_graph(self):
        h=handler()
        h.runtime._voice_jobs.submit.return_value={'job_id':'id','status':'queued'}
        handle_post(h,{'source':'console','audio':['clip']})
        self.assertEqual(h._send.call_args.args[0],202)
        h.runtime._ensure_target_voice.assert_not_called()

    def test_rejects_remote_qq_cross_origin_and_non_json(self):
        for kind in ('remote','qq','origin','json'):
            h=handler(address='192.0.2.5' if kind=='remote' else '127.0.0.1')
            body={'source':'qq_bridge' if kind=='qq' else 'console','audio':['clip']}
            if kind=='origin': h.headers['Origin']='https://malicious.example'
            if kind=='json': h.headers['Content-Type']='text/plain'
            handle_post(h,body)
            self.assertIn(h._send.call_args.args[0],(400,403))
            h.runtime._voice_jobs.submit.assert_not_called()

    def test_get_unknown_job_is_404(self):
        h=handler('/voice/jobs/missing')
        h.runtime._voice_jobs.get.side_effect=KeyError('missing')
        handle_get(h)
        self.assertEqual(h._send.call_args.args[0],404)

    def test_submit_requires_explicit_start(self):
        h=handler()
        h.runtime._target_voice=None
        handle_post(h,{'source':'console','audio':['clip']})
        self.assertEqual(h._send.call_args.args[0],409)

    def test_start_uses_existing_runtime_owner(self):
        h=handler('/voice/start')
        handle_post(h,{'source':'console'})
        h.runtime._ensure_target_voice.assert_called_once()
        self.assertEqual(h._send.call_args.args[0],200)

    def test_daemon_handler_routes_and_bounds_body_before_read(self):
        from backend.target_daemon import _Handler
        h=handler()
        h._ui_route=Mock(return_value=False)
        h.headers['Content-Length']=str(4*1024*1024)
        h.rfile=Mock()
        _Handler.do_POST(h)
        self.assertEqual(h._send.call_args.args[0],413)
        h.rfile.read.assert_not_called()
        body=json.dumps({'source':'console','audio':['clip']}).encode()
        h.headers['Content-Length']=str(len(body))
        h.rfile=io.BytesIO(body)
        _Handler.do_POST(h)
        self.assertEqual(h._send.call_args.args[0],202)

class ReportTests(unittest.TestCase):
    def test_missing_failed_and_synthetic_never_mean_hardware_pass(self):
        report=summarize([{'status':'completed','events_ms':{'request_received':0,
            'playback_callback_first_nonzero':100,'llm_done':200}},
            {'status':'failed','events_ms':{'request_received':0,'playback_callback_first_nonzero':1}}])
        self.assertEqual(report['metrics']['request_to_callback_ms']['samples'],1)
        self.assertEqual(report['metrics']['request_to_callback_ms']['p50'],100)
        self.assertIsNone(report['metrics']['llm_first_content_ms']['p95'])
        self.assertEqual(report['hardware_acceptance'],'not_established')
        self.assertIsNone(report['speech_end_to_acoustic_ms'])

if __name__=='__main__':
    unittest.main()
