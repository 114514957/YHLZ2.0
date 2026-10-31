"""Integrated software acceptance; no real models or audio devices are opened."""
import asyncio
import contextlib
import io
import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from backend.session_kernel import ProviderCapabilities
from backend.target_chain import AudioChunk, CancellationSignal, PipelineError, TargetVoiceChain
from backend.target_playback import PlaybackConfig, SoundDevicePlaybackPort
from tools.target_fixed_text_playback_probe import (
    FIXED_REPLY, FIXED_TRANSCRIPT, SimulatedSoundDevice, main, run_probe,
    FixedReasoner, ProbeProvider, Timeline,
)


class FixedTextPlaybackTests(unittest.TestCase):
    def test_fixed_text_completion_cancel_followup_and_identity(self):
        r = asyncio.run(run_probe())
        self.assertTrue(r['passed'], (r['errors'], r['software_evidence']))
        self.assertEqual(r['fixed_transcript'], FIXED_TRANSCRIPT)
        self.assertEqual(r['fixed_reply'], FIXED_REPLY)
        self.assertEqual([t['status'] for t in r['turns']], ['completed', 'interrupted', 'completed'])
        self.assertEqual(len({t['turn_id'] for t in r['turns']}), 3)
        self.assertEqual(len({t['trace_id'] for t in r['turns']}), 3)
        self.assertGreater(r['turns'][2]['generation'], r['turns'][1]['generation'])
        self.assertFalse(any(r['acoustic_evidence'].values()))
        self.assertFalse(r['backend_evidence']['real_audio_device_opened'])
        self.assertEqual(sum(e['name'] == 'late_playback_attempt' for e in r['events']), 2)
        self.assertTrue(r['software_evidence']['drain_before_audio_done'])
        self.assertTrue(r['software_evidence']['cancelled_turn_has_no_audio_done'])
        self.assertFalse(r['software_evidence']['old_generation_audio'])

    def test_timings_are_measured_from_monotonic_boundaries(self):
        r = asyncio.run(run_probe())
        self.assertTrue(r['passed'], r['errors'])
        t = r['timing_boundaries_perf_counter_s']
        for metric, start, end in [
            ('submit_to_first_pcm', 'submit', 'first_pcm'),
            ('first_pcm_to_playback_start', 'first_pcm', 'playback_start'),
            ('playback_start_to_done', 'playback_start', 'playback_done'),
            ('barge_in_to_stop_observed', 'barge_in', 'stop_observed'),
        ]:
            self.assertGreater(r['latency_ms'][metric], 0)
            self.assertAlmostEqual(r['latency_ms'][metric], (t[end]-t[start])*1000)

    def test_missing_done_fails_closed(self):
        r = asyncio.run(run_probe(fault='missing-done'))
        self.assertFalse(r['passed'])
        self.assertIn('VOICE-TTS-NO-DONE', r['errors'])
        self.assertFalse(r['software_evidence']['turn_completed'])

    def test_missing_effective_pcm_fails_closed(self):
        r = asyncio.run(run_probe(fault='no-pcm'))
        self.assertFalse(r['passed'])
        self.assertIn('VOICE-TTS-NO-EFFECTIVE-PCM', r['errors'])
        self.assertIsNone(r['latency_ms']['submit_to_first_pcm'])

    def test_tts_stop_timeout_blocks_followup(self):
        r = asyncio.run(run_probe(fault='tts-stop-timeout'))
        self.assertFalse(r['passed'])
        self.assertTrue(r['cancel_result']['timed_out_tasks'])
        self.assertTrue(r['followup_blocked'])
        self.assertFalse(r['software_evidence']['tts_stop_observed'])
        self.assertIsNone(r['latency_ms']['barge_in_to_stop_observed'])

    def test_playback_stop_timeout_blocks_followup(self):
        r = asyncio.run(run_probe(fault='playback-stop-timeout'))
        self.assertFalse(r['passed'])
        self.assertTrue(r['cancel_result']['timed_out_tasks'])
        self.assertTrue(r['followup_blocked'])
        self.assertFalse(r['software_evidence']['playback_stop_observed'])
        self.assertIsNone(r['latency_ms']['barge_in_to_stop_observed'])

    def test_cli_writes_json_and_returns_failure_for_negative_probe(self):
        with tempfile.TemporaryDirectory() as temp, contextlib.redirect_stdout(io.StringIO()):
            path = Path(temp) / 'evidence.json'
            self.assertEqual(main(['--output', str(path)]), 0)
            self.assertTrue(json.loads(path.read_text(encoding='utf-8'))['passed'])
            self.assertEqual(main(['--fault', 'no-pcm', '--output', str(path)]), 1)
            self.assertFalse(json.loads(path.read_text(encoding='utf-8'))['passed'])

    def test_backpressured_producer_cannot_enqueue_after_interrupt(self):
        async def scenario():
            device = SimulatedSoundDevice()
            port = SoundDevicePlaybackPort(PlaybackConfig(device='SIMULATED',
                max_queue_blocks=1, initial_buffer_ms=300), sounddevice_module=device)
            port.start()
            signal, lease = CancellationSignal(), SimpleNamespace(turn_id='old-turn')
            chunk = AudioChunk(np.full(480, 1024, dtype='<i2').tobytes(), 24000, 1, 'pcm_s16le')
            entered = threading.Event()
            original_wait = port._not_full.wait
            def observed_wait(timeout=None):
                entered.set()
                return original_wait(timeout)
            port._not_full.wait = observed_wait
            try:
                await port.play(chunk, lease, signal)
                pending = asyncio.create_task(port.play(chunk, lease, signal))
                self.assertTrue(await asyncio.to_thread(entered.wait, 1.0))
                signal.cancel()
                port.interrupt('barge_in')
                self.assertFalse(await asyncio.wait_for(pending, 1.0))
                self.assertEqual(port.health()['queue_depth'], 0)
                self.assertEqual(device.stream.pump(), [])
                self.assertTrue(await port.wait_stopped(0.1))
            finally:
                port.close()
        asyncio.run(scenario())

    def test_unknown_fault_rejected(self):
        with self.assertRaises(ValueError):
            asyncio.run(run_probe(fault='typo'))

    def test_new_final_supersedes_active_provider_without_sticky_cleanup(self):
        async def scenario():
            provider = ProbeProvider(Timeline())
            provider.mode = 'hold'
            chain = TargetVoiceChain(reasoner=FixedReasoner(), tts_provider=provider)
            chain.start(ProviderCapabilities())
            old = await chain.submit_transcript(FIXED_TRANSCRIPT)
            while not provider.sessions:
                await asyncio.sleep(0)
            await asyncio.wait_for(provider.sessions[0].committed.wait(), 1)
            provider.mode = 'complete'
            new = await chain.submit_transcript('这是新的输入')
            self.assertEqual((await asyncio.wait_for(old.task, 1)).status, 'interrupted')
            self.assertEqual((await asyncio.wait_for(new.task, 1)).status, 'completed')
            self.assertGreater(new.lease.generation, old.lease.generation)
            next_turn = await chain.submit_transcript('再来一轮')
            self.assertEqual((await asyncio.wait_for(next_turn.task, 1)).status, 'completed')
        asyncio.run(scenario())

    def test_idle_interrupt_cannot_clear_previous_unconfirmed_stop(self):
        async def scenario():
            provider = ProbeProvider(Timeline(), fault='tts-stop-timeout')
            provider.mode = 'hold'
            chain = TargetVoiceChain(reasoner=FixedReasoner(), tts_provider=provider)
            chain.start(ProviderCapabilities())
            old = await chain.submit_transcript(FIXED_TRANSCRIPT)
            while not provider.sessions:
                await asyncio.sleep(0)
            await asyncio.wait_for(provider.sessions[0].committed.wait(), 1)
            result = await chain.interrupt(timeout_s=0.05)
            self.assertTrue(result.timed_out_tasks)
            await old.task
            await chain.interrupt(timeout_s=0.05)
            with self.assertRaises(PipelineError):
                await chain.submit_transcript('不能绕过停止确认')
        asyncio.run(scenario())


if __name__ == '__main__':
    unittest.main()
