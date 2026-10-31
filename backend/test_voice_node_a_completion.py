"""Node A service wiring, ownership and fault injection: no devices/models."""
import asyncio
import concurrent.futures
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from backend.session_audio_reasoner import SessionAudioReasoner
from backend.target_chain import CancellationSignal, TargetVoiceChain
from backend.target_daemon import DaemonRuntime
from backend.target_daemon_service import TargetDaemonService
from backend.target_device_binding import TargetDeviceBinding
from backend.target_workbench_adapter import TargetWorkbenchAdapter
from backend.voice_task_supervisor import VoiceTaskSupervisor
from backend.voice_turn_trace import VoiceTurnTrace, current_trace
from backend.session_kernel import ProviderCapabilities
from backend.tts_qwen_provider import QwenTTSConfig


def bare_runtime():
    rt = object.__new__(DaemonRuntime)
    rt._target_voice = None
    rt._target_voice_error = ""
    rt._target_voice_lock = threading.Lock()
    rt._target_voice_cleanup_pending = False
    rt._voice_supervisor = VoiceTaskSupervisor()
    rt._loop = Mock()
    return rt


class RoutingTests(unittest.TestCase):
    def test_post_dispatch_failure_never_requests_legacy_fallback(self):
        rt = bare_runtime()
        service = SimpleNamespace(submit_audio=AsyncMock())
        future = concurrent.futures.Future()
        future.set_exception(RuntimeError("already played"))
        def schedule(coroutine, loop):
            coroutine.close()
            return future
        with patch.object(rt, "_ensure_target_voice", return_value=service), patch(
            "asyncio.run_coroutine_threadsafe", side_effect=schedule):
            result = rt._target_voice_turn("", "private", ["clip"])
        self.assertEqual(result["status"], "failed")
        self.assertTrue(result["target_voice"])
        self.assertFalse(result["stop_confirmed"])

    def test_timeout_cancels_submitted_future_without_replay(self):
        rt = bare_runtime()
        service = SimpleNamespace(submit_audio=AsyncMock())
        future = Mock()
        future.result.side_effect = TimeoutError()
        def schedule(coroutine, loop):
            coroutine.close()
            return future
        with patch.object(rt, "_ensure_target_voice", return_value=service), patch(
            "asyncio.run_coroutine_threadsafe", side_effect=schedule):
            result = rt._target_voice_turn("", "console", ["clip"])
        future.cancel.assert_called_once()
        self.assertEqual(result["status"], "failed")

    def test_qq_and_public_never_open_local_speaker(self):
        rt = bare_runtime()
        with patch.object(rt, "_ensure_target_voice") as ensure:
            for channel in ("qq_p123", "qq_g123", "public"):
                self.assertIsNone(rt._target_voice_turn("", channel, ["clip"]))
            ensure.assert_not_called()

    def test_unknown_cleanup_blocks_fallback(self):
        rt = bare_runtime()
        rt._target_voice_cleanup_pending = True
        with patch.object(rt, "_ensure_target_voice", return_value=None):
            self.assertEqual(rt._target_voice_turn("", "private", ["clip"])["error_code"],
                             "TARGET-CLEANUP-UNCONFIRMED")

    def test_start_timeout_cancels_and_waits_cleanup(self):
        rt = bare_runtime()
        start = Mock()
        start.result.side_effect = TimeoutError()
        start.done.return_value = False
        cleanup = Mock()
        service = SimpleNamespace(start=AsyncMock(), shutdown=AsyncMock())
        futures = iter((start, cleanup))
        def schedule(coroutine, loop):
            coroutine.close()
            return next(futures)
        with patch("backend.target_daemon._daemon_target_voice_enabled", return_value=True), patch(
            "backend.target_daemon._daemon_target_device_binding", return_value=Mock()), patch(
            "backend.target_daemon_service.TargetDaemonService", return_value=service), patch(
            "asyncio.run_coroutine_threadsafe", side_effect=schedule):
            self.assertIsNone(rt._ensure_target_voice())
        start.cancel.assert_called_once()
        cleanup.result.assert_called_once_with(timeout=15)
        self.assertFalse(rt._target_voice_cleanup_pending)

    def test_failed_start_cleanup_retains_fail_closed_gate(self):
        rt = bare_runtime()
        service = SimpleNamespace(start=AsyncMock(), shutdown=AsyncMock())
        def schedule(coroutine, loop):
            coroutine.close()
            future = Mock()
            future.result.side_effect = RuntimeError()
            future.done.return_value = True
            return future
        with patch("backend.target_daemon._daemon_target_voice_enabled", return_value=True), patch(
            "backend.target_daemon._daemon_target_device_binding", return_value=Mock()), patch(
            "backend.target_daemon_service.TargetDaemonService", return_value=service), patch(
            "asyncio.run_coroutine_threadsafe", side_effect=schedule):
            self.assertIsNone(rt._ensure_target_voice())
        self.assertTrue(rt._target_voice_cleanup_pending)


class SessionReasonerTests(unittest.IsolatedAsyncioTestCase):
    async def test_stream_preserves_session_and_explicit_tool_policy(self):
        release = asyncio.Event()
        seen = []
        class Session:
            async def run_turn(self, text, **kwargs):
                seen.append((text, kwargs["audio"], kwargs["voice_tools_enabled"]))
                kwargs["on_delta"]("第一段")
                await release.wait()
                kwargs["on_delta"]("第二段")
                return {"answer": "第一段第二段"}
        reasoner = SessionAudioReasoner(Session, None)
        stream = reasoner.generate_audio("", ["clip"], CancellationSignal())
        self.assertEqual(await anext(stream), "第一段")
        release.set()
        self.assertEqual([x async for x in stream], ["第二段"])
        self.assertEqual(seen, [("", ["clip"], False)])

    async def test_closing_consumer_cancels_session(self):
        stopped = asyncio.Event()
        class Session:
            async def run_turn(self, text, **kwargs):
                try:
                    kwargs["on_delta"]("第一段")
                    await asyncio.Event().wait()
                finally:
                    stopped.set()
        stream = SessionAudioReasoner(Session, None).generate_audio("", ["clip"], CancellationSignal())
        await anext(stream)
        await stream.aclose()
        self.assertTrue(stopped.is_set())

    async def test_bounded_content_overflow_fails_instead_of_silent_loss(self):
        class Session:
            async def run_turn(self, text, **kwargs):
                for i in range(80):
                    kwargs["on_delta"]("a")
                return {"answer": "a" * 80}
        with self.assertRaisesRegex(Exception, "VOICE-CONTENT-BACKPRESSURE"):
            async for _ in SessionAudioReasoner(Session, None).generate_audio("", ["clip"], CancellationSignal()):
                pass

    async def test_text_path_unchanged(self):
        class Text:
            async def generate(self, text, signal):
                yield text
        reasoner = SessionAudioReasoner(lambda: self.fail("audio session used"), Text())
        self.assertEqual([x async for x in reasoner.generate("hello", CancellationSignal())], ["hello"])

    async def test_explicit_audio_does_not_require_fabricated_wake_word(self):
        seen = []
        class Reasoner:
            async def generate(self, text, signal):
                raise AssertionError("text fallback")
                yield ""
            async def generate_audio(self, text, audio, signal):
                seen.append((text, audio))
                yield "收到"
        chain = TargetVoiceChain(reasoner=Reasoner())
        chain.start(ProviderCapabilities(continuous_capture=True))
        try:
            result = await TargetWorkbenchAdapter(chain=chain).submit_audio(["clip"], text="")
            self.assertEqual(result.status, "completed")
            self.assertEqual(seen, [("", ["clip"])])
            self.assertEqual(chain.gate.state.value, "idle")
        finally:
            await chain.shutdown()

    async def test_audio_without_capable_reasoner_fails_not_silent_text(self):
        class Text:
            async def generate(self, text, signal):
                yield "wrong"
        chain = TargetVoiceChain(reasoner=Text())
        chain.start(ProviderCapabilities(continuous_capture=True))
        result = await TargetWorkbenchAdapter(chain=chain).submit_audio(["clip"])
        self.assertEqual(result.status, "failed")
        await chain.shutdown()

    async def test_old_request_cannot_interrupt_new_turn(self):
        chain = TargetVoiceChain(reasoner=Mock())
        with patch.object(chain.kernel, "snapshot", return_value={"active_turn_id": "new"}), patch.object(
            chain.kernel, "abort_active_turn_async", new_callable=AsyncMock) as abort:
            self.assertIsNone(await chain.interrupt(expected_turn_id="old"))
            abort.assert_not_awaited()


class BackgroundTests(unittest.IsolatedAsyncioTestCase):
    async def test_foreground_defers_then_background_completes(self):
        supervisor = VoiceTaskSupervisor()
        supervisor.enter_foreground()
        entered = asyncio.Event()
        async def work():
            entered.set()
            return "completed"
        task = supervisor.submit(work())
        await asyncio.sleep(.01)
        self.assertFalse(entered.is_set())
        supervisor.leave_foreground()
        await task
        await asyncio.sleep(0)
        self.assertEqual(supervisor.snapshot()["pending"], 0)
        self.assertEqual(supervisor.records[-1]["status"], "completed")

    async def test_timeout_includes_waiting_for_foreground(self):
        supervisor = VoiceTaskSupervisor(timeout_s=.01)
        supervisor.enter_foreground()
        task = supervisor.submit(asyncio.sleep(10))
        await task
        self.assertEqual(supervisor.records[-1]["status"], "timeout")

    async def test_capacity_shutdown_and_immediate_cancel(self):
        supervisor = VoiceTaskSupervisor(capacity=1)
        first = supervisor.submit(asyncio.sleep(10))
        self.assertIsNone(supervisor.submit(asyncio.sleep(10)))
        await supervisor.shutdown()
        self.assertTrue(first.cancelled())
        self.assertEqual(supervisor.snapshot()["pending"], 0)
        self.assertIn("cancelled", [r["status"] for r in supervisor.records])

    async def test_foreground_preempts_running_writeback(self):
        supervisor = VoiceTaskSupervisor()
        entered = asyncio.Event()
        async def work():
            entered.set()
            await asyncio.Event().wait()
        task = supervisor.submit(work())
        await entered.wait()
        supervisor.enter_foreground()
        await asyncio.gather(task, return_exceptions=True)
        self.assertEqual(supervisor.records[-1]["status"], "cancelled")


class ServiceTests(unittest.IsolatedAsyncioTestCase):
    def service(self):
        return TargetDaemonService(TargetDeviceBinding(input_name="in", output_name="out", route="headset"),
                                   session_factory=Mock())

    async def test_real_start_wires_session_reasoner_and_segmented_config(self):
        service = self.service()
        devices = Mock(output_index=1, output_sample_rate=48000, output_channels=2,
                       input_sample_rate=16000)
        comp = Mock()
        comp.chain = Mock()
        comp.runtime = SimpleNamespace(chain=comp.chain)
        comp.shutdown = AsyncMock()
        async def run():
            await asyncio.Event().wait()
        comp.run = run
        with patch("backend.target_daemon_service.resolve_devices", return_value=devices), patch(
            "backend.target_composition.TargetVoiceComposition", return_value=comp) as factory, patch(
            "backend.target_voice_profile.build_target_qwen_config", return_value=QwenTTSConfig(model_dir=Path("C:/fake"))), patch(
            "backend.target_playback.SoundDevicePlaybackPort"), patch(
            "backend.llm_hybrid_compose.create_hybrid_reasoner"), patch(
            "backend.target_sherpa_asr.SherpaOnlineASRProvider"), patch(
            "backend.target_vad.TargetVADProvider"), patch(
            "backend.media_adapter.SoundDeviceInputSource"), patch(
            "backend.target_daemon_service.TargetWorkbenchAdapter", return_value=Mock()):
            await service.start()
            self.assertTrue(factory.call_args.args[0].segmented_tts_enabled)
            self.assertIsInstance(factory.call_args.kwargs["reasoner"], SessionAudioReasoner)
            await service.shutdown()
        comp.shutdown.assert_awaited_once()

    async def test_partial_start_failure_cleans_composition_once(self):
        service = self.service()
        devices = Mock(output_index=1, output_sample_rate=48000, output_channels=2,
                       input_sample_rate=16000)
        comp = Mock()
        comp.create_runtime.side_effect = RuntimeError("partial startup")
        comp.shutdown = AsyncMock()
        with patch("backend.target_daemon_service.resolve_devices", return_value=devices), patch(
            "backend.target_composition.TargetVoiceComposition", return_value=comp), patch(
            "backend.target_voice_profile.build_target_qwen_config", return_value=QwenTTSConfig(model_dir=Path("C:/fake"))), patch(
            "backend.target_playback.SoundDevicePlaybackPort"), patch(
            "backend.llm_hybrid_compose.create_hybrid_reasoner"), patch(
            "backend.target_sherpa_asr.SherpaOnlineASRProvider"), patch(
            "backend.target_vad.TargetVADProvider"), patch(
            "backend.media_adapter.SoundDeviceInputSource"):
            with self.assertRaisesRegex(RuntimeError, "partial startup"):
                await service.start()
        await service.shutdown()
        comp.shutdown.assert_awaited_once()

    async def test_shutdown_failure_keeps_resource_and_error_visible(self):
        service = self.service()
        service.composition = SimpleNamespace(shutdown=AsyncMock(side_effect=RuntimeError("stop")))
        with self.assertRaises(RuntimeError):
            await service.shutdown()
        self.assertIsNotNone(service.composition)
        self.assertEqual(service.error_code, "TARGET-CLEANUP-UNCONFIRMED")

    async def test_cancelled_request_interrupts_only_owned_lease_and_persists_trace(self):
        service = self.service()
        entered = asyncio.Event()
        async def submit(*a, **kw):
            current_trace.get().bind(SimpleNamespace(turn_id="old", generation=2))
            entered.set()
            await asyncio.Event().wait()
        service.devices = Mock()
        service.adapter = SimpleNamespace(submit_audio=submit)
        interrupt = AsyncMock(return_value=None)
        service.composition = SimpleNamespace(chain=SimpleNamespace(interrupt=interrupt))
        with patch.object(VoiceTurnTrace, "save") as save:
            task = asyncio.create_task(service.submit_audio(["clip"]))
            await entered.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        interrupt.assert_awaited_once_with("audio_request_cancelled", expected_turn_id="old")
        save.assert_called_once()
        self.assertFalse(service.recent_traces[-1]["acoustic_output_measured"])

    async def test_trace_file_excludes_content_and_does_not_fabricate_speech_end(self):
        trace = VoiceTurnTrace("headset")
        trace.mark("first_pcm_received")
        first = trace.events["first_pcm_received"]
        trace.mark("first_pcm_received")
        self.assertEqual(first, trace.events["first_pcm_received"])
        with tempfile.TemporaryDirectory() as tmp:
            self.assertTrue(trace.save(tmp).exists())
        self.assertFalse(trace.snapshot()["speech_end_measured"])

    async def test_callback_marker_requires_nonzero_output_not_enqueue(self):
        from backend.test_target_playback import _port, _chunk, _lease, _Signal
        trace = VoiceTurnTrace()
        token = current_trace.set(trace)
        port, device, _ = _port(initial_buffer_ms=0)
        try:
            await port.play(_chunk(), _lease(), _Signal())
            self.assertNotIn("playback_callback_first_nonzero", trace.events)
            device.stream.pump()
            self.assertIn("playback_callback_first_nonzero", trace.events)
        finally:
            port.close()
            current_trace.reset(token)


class JointSessionStreamingTests(unittest.IsolatedAsyncioTestCase):
    async def test_actual_session_to_target_stream_preserves_persona_and_no_tools(self):
        await self._exercise()

    async def test_native_frames_to_same_session_kernel_and_segmented_tts(self):
        await self._exercise(native=True)

    async def _exercise(self, native=False):
        from backend.target_entry import ConversationSession
        from backend.target_memory import TargetMemoryService
        from backend.target_kw_index import KeywordIndex
        from backend.target_orchestrator import build_openai_compatible_llm_turn
        from backend.target_composition import TargetVoiceComposition, TargetVoiceCompositionConfig
        from backend.test_tts_segmented_provider import FakeProvider
        from contextlib import nullcontext
        played = asyncio.Event()
        captured = []
        async def fake_stream(**kwargs):
            captured.append(kwargs)
            await kwargs["on_event"]({"kind":"delta", "stage":"content", "delta":"这是一段能先播放的测试回答。"})
            await asyncio.wait_for(played.wait(), 3)
            await kwargs["on_event"]({"kind":"delta", "stage":"content", "delta":"后半句来了。"})
            return {"content":"这是一段能先播放的测试回答。后半句来了。", "tool_calls":[]}
        class Playback:
            async def play(self, chunk, lease, signal):
                played.set()
                return True
            async def finish(self, lease, signal):
                return True
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)
            mem=TargetMemoryService(db_path=path/"m.db", kw_index=KeywordIndex(path/"k.db"))
            session=ConversationSession(memory=mem, llm_turn=build_openai_compatible_llm_turn(), channel="console")
            supervisor=VoiceTaskSupervisor()
            supervisor.enter_foreground()
            session._voice_supervisor=supervisor
            session.render_system=lambda: "你是元亨，保持我的人格测试标识。"
            session._maybe_contradiction=AsyncMock(return_value=[])
            raw=FakeProvider()
            comp=TargetVoiceComposition(
                TargetVoiceCompositionConfig(qwen=QwenTTSConfig(model_dir=Path("C:/fake")), segmented_tts_enabled=True),
                reasoner=SessionAudioReasoner(lambda:session, None), playback=Playback(), provider_factory=lambda cfg:raw)
            comp.chain.start(ProviderCapabilities(continuous_capture=True))
            trace=VoiceTurnTrace("headset")
            token=current_trace.set(trace)
            try:
                with patch("backend.entity_graph.ingest_text", new_callable=AsyncMock), patch(
                    "backend.intrinsic_drives.observe"), patch("backend.intrinsic_drives.dad_direction"), patch(
                    "backend.llm_stream.stream_openai_compatible", side_effect=fake_stream), (
                    nullcontext() if native else patch("backend.target_orchestrator._to_input_audio",
                        return_value={"type":"input_audio", "input_audio":{"data":"fake", "format":"wav"}})):
                    adapter = TargetWorkbenchAdapter(chain=comp.chain)
                    if native:
                        from backend.native_audio_ingress import NativeAudioIngress
                        from backend.test_native_audio_ingress import frame
                        bridge = NativeAudioIngress(chain=comp.chain, submit_audio=adapter.submit_audio)
                        try:
                            for seq in range(1, 11):
                                await bridge.accept_frame(frame(seq))
                            task = await bridge.accept_frame(frame(11, speech=False))
                            result = await asyncio.wait_for(task, 5)
                        finally:
                            await bridge.close()
                    else:
                        result=await asyncio.wait_for(adapter.submit_audio(["clip"]),5)
                self.assertEqual(result.status,"completed")
                self.assertIn("后半句",session.history[-1]["content"])
                self.assertEqual(captured[0]["model"],"gemma-4-e4b")
                self.assertFalse(captured[0]["tools"])
                self.assertIn("人格测试标识",captured[0]["messages"][0]["content"])
                self.assertEqual(len(session.history),2)
                for event in ("turn_accepted","llm_request_start","llm_first_content","first_segment_ready", "first_tts_submit","first_pcm_received","llm_done"):
                    self.assertIn(event,trace.events)
                self.assertLess(trace.events["first_pcm_received"],trace.events["llm_done"])
                self.assertGreaterEqual(len(raw.sessions),2)
            finally:
                current_trace.reset(token)
                await supervisor.shutdown()
                await comp.chain.shutdown()


class WritebackIdentityTests(unittest.IsolatedAsyncioTestCase):
    async def test_reversed_transcripts_restamp_exact_history_and_memory(self):
        from backend.target_entry import ConversationSession
        from backend.target_memory import TargetMemoryService
        from backend.target_kw_index import KeywordIndex
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            memory = TargetMemoryService(db_path=path/"m.db", kw_index=KeywordIndex(path/"k.db"))
            one = memory.append_voice_turn(text="（语音）")
            two = memory.append_voice_turn(text="（语音）")
            session = object.__new__(ConversationSession)
            first = {"role": "user", "content": "（语音）"}
            second = {"role": "user", "content": "（语音）"}
            session.history = [first, second]
            session.memory = memory
            session.channel = "console"
            session._session_name = ""
            session.llm_turn = AsyncMock(spec=[], side_effect=[{"content": "第二句"}, {"content": "第一句"}])
            with patch("backend.target_orchestrator._to_input_audio", return_value={"type":"input_audio"}):
                await session._transcribe_audio_turn(["two.wav"], "（语音）", user_entry=second, memory_ref=two)
                await session._transcribe_audio_turn(["one.wav"], "（语音）", user_entry=first, memory_ref=one)
            self.assertTrue(first["content"].startswith("第一句"))
            self.assertTrue(second["content"].startswith("第二句"))
            self.assertTrue(memory._turns[0]["text"].startswith("第一句"))
            self.assertTrue(memory._turns[1]["text"].startswith("第二句"))

if __name__ == "__main__":
    unittest.main()
