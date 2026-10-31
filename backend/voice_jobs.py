"""Bounded nonblocking voice requests, owned by the daemon's existing loop.

Cancellation status is published ONLY after service cleanup, not merely when a
concurrent Future accepts cancel(). Queued requests can be cancelled before start.
"""
from __future__ import annotations
import asyncio
import threading
import uuid
from collections import OrderedDict

class VoiceJobError(RuntimeError):
    pass

class VoiceJobs:
    def __init__(self, *, capacity=2, history_limit=64):
        if capacity < 1 or history_limit < capacity:
            raise ValueError('invalid voice job bounds')
        self.capacity, self.history_limit = capacity, history_limit
        self._lock = threading.RLock()
        self._records = OrderedDict()
        self._tasks = {}
        self._closed = False

    def submit(self, loop, service, audio, *, text=''):
        with self._lock:
            if self._closed:
                raise VoiceJobError('VOICE-JOBS-CLOSED')
            if sum(r['status'] in {'queued','running','cancel_requested'} for r in self._records.values()) >= self.capacity:
                raise VoiceJobError('VOICE-JOBS-BUSY')
            while len(self._records) >= self.history_limit:
                old = next((k for k,r in self._records.items()
                            if r['status'] not in {'queued','running','cancel_requested'}), None)
                if old is None:
                    raise VoiceJobError('VOICE-JOBS-BUSY')
                del self._records[old]
            job_id = uuid.uuid4().hex
            self._records[job_id] = {'job_id':job_id, 'status':'queued',
                                     'cancel_requested':False, 'result':None, 'error_code':None}
        async def work():
            with self._lock:
                record = self._records[job_id]
                if record['cancel_requested'] or self._closed:
                    record['status'] = 'cancelled'
                    return
                record['status'] = 'running'
                self._tasks[job_id] = asyncio.current_task()
            try:
                result = await service.submit_audio(audio, text=text, source='daemon_audio_job')
                with self._lock:
                    record['result'] = result.to_dict()
                    record['status'] = result.status
                    record['error_code'] = result.error_code
            except asyncio.CancelledError:
                with self._lock:
                    record['error_code'] = getattr(service, 'error_code', None)
                    record['status'] = 'failed' if record['error_code'] else 'cancelled'
            except Exception as exc:
                with self._lock:
                    record['status'], record['error_code'] = 'failed', type(exc).__name__
            finally:
                with self._lock:
                    self._tasks.pop(job_id, None)
        coroutine = work()
        try:
            asyncio.run_coroutine_threadsafe(coroutine, loop)
        except Exception:
            coroutine.close()
            with self._lock:
                self._records.pop(job_id, None)
            raise
        return self.get(job_id)

    def get(self, job_id):
        with self._lock:
            record = self._records.get(job_id)
            if record is None:
                raise KeyError(job_id)
            result = dict(record)
            if result['result'] is not None:
                result['result'] = dict(result['result'])
            return result

    def cancel(self, loop, job_id):
        with self._lock:
            record = self._records.get(job_id)
            if record is None:
                raise KeyError(job_id)
            if record['status'] in {'queued','running','cancel_requested'}:
                record['cancel_requested'] = True
                record['status'] = 'cancel_requested'
                task = self._tasks.get(job_id)
                if task is not None:
                    loop.call_soon_threadsafe(self._cancel_if_live, task)
        return self.get(job_id)

    @staticmethod
    def _cancel_if_live(task):
        if not task.done() and not task.cancelling():
            task.cancel()

    async def shutdown(self):
        with self._lock:
            self._closed = True
            tasks = list(self._tasks.values())
            for job_id, record in self._records.items():
                if record['status'] in {'queued','running','cancel_requested'}:
                    record['cancel_requested'] = True
                    record['status'] = 'cancel_requested' if job_id in self._tasks else 'cancelled'
        for task in tasks:
            self._cancel_if_live(task)
        await asyncio.gather(*tasks, return_exceptions=True)
