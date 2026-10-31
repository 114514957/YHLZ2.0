"""Native ingress contracts: synthetic PCM only, no models/devices/network."""
import asyncio
import base64
import io
import tempfile
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
import numpy as np

from backend.native_audio_ingress import NativeAudioIngress, NativeClipEncoder
from backend.media_adapter import AudioFrame, ProcessedAudioFrame
from backend.speech_segment import SpeechSegment
from backend.target_chain import CancellationSignal
from backend.voice_turn_trace import VoiceTurnTrace


def frame(seq=1, speech=True, samples=None):
    samples = np.zeros(320, dtype=np.float32) if samples is None else samples
    meta = AudioFrame(samples, 16000, sequence=seq, generation=1, duration_ms=20)
    return ProcessedAudioFrame(meta, samples, speech, False)


def segment(name='one', samples=None, rate=16000, channels=1):
    return SpeechSegment(name, 1, 1, 1, rate, channels, (frame(samples=samples),), 'vad_end')


class EncoderTests(unittest.TestCase):
    def test_wav_format_float_clip(self):
        uri = NativeClipEncoder().transcribe(segment(samples=np.array([-2., -.5, 0, .5, 2.])), CancellationSignal())
        with wave.open(io.BytesIO(base64.b64decode(uri.split(',', 1)[1])), 'rb') as wav:
            self.assertEqual((wav.getframerate(), wav.getnchannels(), wav.getsampwidth()), (16000, 1, 2))
            self.assertEqual(np.frombuffer(wav.readframes(10), dtype='<i2').tolist(), [-32767, -16383, 0, 16383, 32767])

    def test_integer_bytes_roundtrip(self):
        pcm = np.array([-32768, 0, 32767], dtype='<i2')
        for samples in (pcm, pcm.tobytes()):
            uri = NativeClipEncoder().transcribe(segment(samples=samples), CancellationSignal())
            with wave.open(io.BytesIO(base64.b64decode(uri.split(',', 1)[1])), 'rb') as wav:
                self.assertEqual(wav.readframes(10), pcm.tobytes())

    def test_rejects_invalid_or_unbounded_input(self):
        cases = [(np.array([]), 'EMPTY'), (b'x', 'ODD-PCM'),
                 (np.array([np.nan]), 'NONFINITE'), (np.array([np.inf]), 'NONFINITE'),
                 (np.zeros((10, 2)), 'CHANNELS'), (np.zeros(480001), 'TOO-LONG')]
        for samples, code in cases:
            with self.subTest(code=code), self.assertRaisesRegex(ValueError, code):
                NativeClipEncoder().transcribe(segment(samples=samples), CancellationSignal())
        with self.assertRaisesRegex(ValueError, '16K-MONO'):
            NativeClipEncoder().transcribe(segment(rate=48000), CancellationSignal())

    def test_cancel_before_encode(self):
        signal = CancellationSignal()
        signal.cancel()
        with self.assertRaises(asyncio.CancelledError):
            NativeClipEncoder().transcribe(segment(), signal)

    def test_inline_reference_is_bounded_fingerprint(self):
        from backend.target_entry import _voice_clip_reference
        uri = 'data:audio/wav;base64,' + 'a'*100000
        result = _voice_clip_reference(uri)
        self.assertTrue(result.startswith('inline-audio-'))
        self.assertLess(len(result), 40)
        self.assertEqual(result, _voice_clip_reference(uri))

    def test_trace_rotation_only_owns_uuid_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            keep = Path(tmp)/'user-report.json'
            keep.write_text('untouched')
            for _ in range(7):
                VoiceTurnTrace().save(tmp, max_files=3)
            self.assertEqual(len(list(Path(tmp).glob('*.json'))), 4)
            self.assertEqual(keep.read_text(), 'untouched')

    def test_voice_identity_survives_l1_reload(self):
        from backend.target_memory import TargetMemoryService
        from backend.target_kw_index import KeywordIndex
        with tempfile.TemporaryDirectory() as tmp:
            db, kw = Path(tmp)/'m.db', Path(tmp)/'k.db'
            mem = TargetMemoryService(db_path=db, kw_index=KeywordIndex(kw))
            first = mem.append_voice_turn(text='voice-1')
            second = mem.append_voice_turn(text='voice-2')
            restored = TargetMemoryService(db_path=db, kw_index=KeywordIndex(kw))
            self.assertTrue(restored.restamp_voice_turn(second, 'second'))
            self.assertTrue(restored.restamp_voice_turn(first, 'first'))
            self.assertEqual([t['text'] for t in restored._turns], ['first', 'second'])


class IngressTests(unittest.IsolatedAsyncioTestCase):
    async def test_frames_submit_native_audio_without_asr_or_two_second_cut(self):
        submit = AsyncMock(return_value=SimpleNamespace(status='completed', error_code=None))
        bridge = NativeAudioIngress(chain=Mock(), submit_audio=submit)
        for seq in range(1, 131):
            self.assertIsNone(await bridge.accept_frame(frame(seq)))
        task = await bridge.accept_frame(frame(131, speech=False))
        self.assertIsNotNone(task)
        result = await task
        self.assertEqual(result.status, 'completed')
        submit.assert_awaited_once()
        self.assertEqual(submit.call_args.kwargs, {'text':'', 'source':'microphone_native'})
        self.assertTrue(submit.call_args.args[0][0].startswith('data:audio/wav;base64,'))
        self.assertFalse(bridge.snapshot()['ports']['asr_stop_observable'])
        await bridge.close()

    async def test_new_segment_waits_for_cancel_cleanup(self):
        entered, cleaned = asyncio.Event(), asyncio.Event()
        calls = []
        async def submit(*args, **kwargs):
            calls.append(args)
            if len(calls) == 1:
                entered.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    await asyncio.sleep(.01)
                    cleaned.set()
            else:
                self.assertTrue(cleaned.is_set())
            return SimpleNamespace(status='completed', error_code=None)
        bridge = NativeAudioIngress(chain=Mock(), submit_audio=submit)
        bridge.assembler.reset(1)
        first = await bridge.submit_segment(segment())
        await asyncio.wait_for(entered.wait(), 2)
        second = await bridge.submit_segment(segment('two'))
        with self.assertRaises(asyncio.CancelledError):
            await first
        self.assertEqual((await second).status, 'completed')
        await bridge.close()
        self.assertFalse(bridge.snapshot()['active_task'])

    async def test_close_cancels_active_turn_and_rejects_new(self):
        entered, stopped = asyncio.Event(), asyncio.Event()
        async def submit(*a, **kw):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()
        bridge = NativeAudioIngress(chain=Mock(), submit_audio=submit)
        bridge.assembler.reset(1)
        task = await bridge.submit_segment(segment())
        await asyncio.wait_for(entered.wait(), 2)
        await bridge.close()
        self.assertTrue(stopped.is_set())
        self.assertTrue(task.cancelled())
        with self.assertRaisesRegex(RuntimeError, 'closed'):
            await bridge.submit_segment(segment('two'))

    async def test_timeout_waits_for_turn_cleanup(self):
        stopped = asyncio.Event()
        async def submit(*a, **kw):
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()
        bridge = NativeAudioIngress(chain=Mock(), submit_audio=submit, timeout_s=.01)
        bridge.assembler.reset(1)
        result = await (await bridge.submit_segment(segment()))
        self.assertEqual(result.error_code, 'NATIVE-AUDIO-TIMEOUT')
        self.assertTrue(stopped.is_set())
        await bridge.close()

    async def test_composition_uses_one_kernel_without_asr_provider(self):
        from backend.test_target_composition import _config, _Reasoner, _Provider, _Source, _VAD
        from backend.target_composition import TargetVoiceComposition
        comp = TargetVoiceComposition(_config(), reasoner=_Reasoner(), provider_factory=lambda _: _Provider())
        runtime = comp.create_runtime(asr=None, source=_Source(), vad=_VAD(), native_audio_submit=AsyncMock())
        self.assertIsInstance(runtime.asr, NativeAudioIngress)
        self.assertIs(runtime.asr.chain, comp.chain)
        self.assertIs(runtime.chain.kernel, comp.kernel)
        await comp.shutdown('test')

    async def test_native_service_does_not_construct_sherpa(self):
        from backend.target_daemon_service import TargetDaemonService
        from backend.target_device_binding import TargetDeviceBinding
        from backend.tts_qwen_provider import QwenTTSConfig
        service = TargetDaemonService(TargetDeviceBinding(input_name='in', output_name='out', route='headset'), session_factory=Mock())
        service.native_capture = True
        devices = Mock(output_index=1, output_sample_rate=48000, output_channels=2, input_sample_rate=16000)
        comp = Mock()
        comp.chain = Mock()
        comp.runtime = SimpleNamespace(chain=comp.chain)
        comp.shutdown = AsyncMock()
        async def run():
            await asyncio.Event().wait()
        comp.run = run
        with patch('backend.target_daemon_service.resolve_devices', return_value=devices), patch(
            'backend.target_composition.TargetVoiceComposition', return_value=comp), patch(
            'backend.target_voice_profile.build_target_qwen_config', return_value=QwenTTSConfig(model_dir=Path('C:/fake'))), patch(
            'backend.target_playback.SoundDevicePlaybackPort'), patch(
            'backend.llm_hybrid_compose.create_hybrid_reasoner'), patch(
            'backend.target_sherpa_asr.SherpaOnlineASRProvider') as sherpa, patch(
            'backend.target_vad.TargetVADProvider'), patch(
            'backend.media_adapter.SoundDeviceInputSource'), patch(
            'backend.target_daemon_service.TargetWorkbenchAdapter', return_value=Mock()):
            await service.start()
            sherpa.assert_not_called()
            self.assertIsNone(comp.create_runtime.call_args.kwargs['asr'])
            self.assertEqual(comp.create_runtime.call_args.kwargs['native_audio_submit'], service.submit_audio)
            await service.shutdown()

class SessionSerializationTests(unittest.IsolatedAsyncioTestCase):
    async def test_text_audio_share_history_mutation_lock(self):
        from backend.target_entry import ConversationSession
        session = object.__new__(ConversationSession)
        session._turn_lock = asyncio.Lock()
        entered, release = asyncio.Event(), asyncio.Event()
        order = []
        async def serial(text, **kwargs):
            order.append(text)
            if text == 'first':
                entered.set()
                await release.wait()
            return {'answer': text}
        session._run_turn_serial = serial
        first = asyncio.create_task(session.run_turn('first'))
        await asyncio.wait_for(entered.wait(), 1)
        second = asyncio.create_task(session.run_turn('second', audio=['clip']))
        await asyncio.sleep(.01)
        self.assertEqual(order, ['first'])
        release.set()
        await asyncio.gather(first, second)
        self.assertEqual(order, ['first', 'second'])

    async def test_cancelled_queued_voice_does_not_start_session(self):
        from backend.target_entry import ConversationSession
        session = object.__new__(ConversationSession)
        session._turn_lock = asyncio.Lock()
        session._run_turn_serial = AsyncMock()
        async with session._turn_lock:
            task = asyncio.create_task(session.run_turn('', audio=['clip']))
            await asyncio.sleep(0)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        session._run_turn_serial.assert_not_awaited()

if __name__ == '__main__':
    unittest.main()
