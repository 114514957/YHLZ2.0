"""Local clone routing regression; synthetic audio, no network/GPU/device."""
import asyncio
import pickle
import tempfile
import threading
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import numpy as np
from backend.target_voice_profile import build_target_qwen_config
from backend.tts_qwen_provider import QwenTTSConfig, QwenTTSWorker, QwenTTSAdapterError, create_qwen_provider
from backend.tts_qwen_process import QwenProcessWorker, create_qwen_process_provider
from backend.tts_provider_port import TTSRequest


class CloneModel:
    def __init__(self):
        self.calls = []
        self.slow = False

    def generate_voice_clone_streaming(self, text, language, ref_audio, ref_text, **kwargs):
        self.calls.append(dict(text=text, language=language, ref_audio=ref_audio, ref_text=ref_text, **kwargs))
        for _ in range(100 if self.slow else 2):
            if self.slow:
                time.sleep(0.01)
            yield np.full(480, 0.1, dtype=np.float32), 24000, {}

    def generate_custom_voice_streaming(self, **kwargs):
        raise AssertionError("must not silently use CustomVoice")


class VoiceProfileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        refs = self.root / "models/tts/refs/xiaoyi"
        refs.mkdir(parents=True)
        (refs / "ref01.wav").write_bytes(b"test-only-reference")
        (refs / "ref01.txt").write_text("private reference transcript", encoding="utf-8")
        (self.root / "models/qwen3-tts/Qwen3-TTS-12Hz-0.6B-Base").mkdir(parents=True)
        self.config = build_target_qwen_config(root=self.root, tail_verify=False, stop_timeout_s=0.5)
        self.gpu = patch("backend.tts_qwen_provider._gpu_snapshot", return_value={})
        self.gpu.start()

    def tearDown(self):
        self.gpu.stop()
        self.tmp.cleanup()

    def test_default_is_local_xiaoyi_clone(self):
        self.assertEqual(self.config.voice_mode, "clone")
        self.assertEqual(self.config.clone_voice_id, "xiaoyi")
        self.assertIn("0.6B-Base", str(self.config.model_dir))
        self.assertEqual(self.config.provider_id, "qwen3-faster-clone")
        self.assertNotIn(self.config.ref_text, str(self.config.to_dict()))
        self.assertNotIn(self.config.ref_text, repr(self.config))
        self.assertIsNone(self.config.to_dict()["speaker"])
        self.assertTrue(self.config.tail_verify is False)

    def test_composition_propagates_resolved_clone_voice(self):
        from backend.target_composition import TargetVoiceComposition, TargetVoiceCompositionConfig
        class Reasoner:
            async def generate(self, text, signal):
                yield "hello"
        model = CloneModel()
        provider = create_qwen_provider(self.config, model_factory=lambda c: model)
        composition = TargetVoiceComposition(TargetVoiceCompositionConfig(qwen=self.config),
                    reasoner=Reasoner(), provider_factory=lambda c: provider)
        self.assertEqual(composition.chain.tts_voice_id, "xiaoyi")
        self.assertNotEqual(composition.chain.tts_voice_id, self.config.speaker)
        asyncio.run(composition.shutdown("test"))

    def test_model_only_override_preserves_customvoice(self):
        config = build_target_qwen_config(model_dir="explicit-custom-model")
        self.assertEqual(config.voice_mode, "customvoice")
        self.assertEqual(config.speaker, "Vivian")
        self.assertTrue(config.tail_verify)

    def test_explicit_clone_model_override(self):
        config = build_target_qwen_config(voice_profile="xiaoyi", model_dir=self.config.model_dir, root=self.root)
        self.assertEqual(config.voice_mode, "clone")
        self.assertTrue(config.tail_verify)

    def test_missing_assets_never_fallback(self):
        for name in ("ref01.wav", "ref01.txt"):
            file = self.root / "models/tts/refs/xiaoyi" / name
            data = file.read_bytes()
            file.unlink()
            with self.assertRaises(FileNotFoundError):
                build_target_qwen_config(root=self.root)
            file.write_bytes(data)

    def test_empty_reference_rejected(self):
        (self.root / "models/tts/refs/xiaoyi/ref01.txt").write_text("  ")
        with self.assertRaises(ValueError):
            build_target_qwen_config(root=self.root)

    def test_invalid_profile_and_overrides_rejected(self):
        for kwargs in ({"voice_profile": "unknown"}, {"voice_profile": "customvoice"}, {"speaker": "Serena"}):
            with self.assertRaises(ValueError):
                build_target_qwen_config(root=self.root, **kwargs)
        with self.assertRaises(ValueError):
            QwenTTSConfig(model_dir="model", voice_mode="clone")

    def test_process_config_and_capabilities_preserve_clone(self):
        config = pickle.loads(pickle.dumps(self.config))
        self.assertEqual(config, self.config)
        worker = QwenProcessWorker(config)
        provider = create_qwen_process_provider(config)
        for obj in (worker, provider):
            caps = obj.describe_capabilities()
            self.assertEqual(caps.provider_id, "qwen3-faster-clone")
            self.assertTrue(caps.true_audio_stream)
            self.assertFalse(caps.text_stream)
            self.assertFalse(caps.native_emotion)
            self.assertEqual(obj.health()["provider_id"], "qwen3-faster-clone")

    def test_missing_clone_api_fails_before_customvoice(self):
        class CustomOnly:
            def generate_custom_voice_streaming(self, **kwargs):
                raise AssertionError("fallback is forbidden")
        worker = QwenTTSWorker(self.config, model_factory=lambda c: CustomOnly())
        with self.assertRaises(QwenTTSAdapterError) as cm:
            worker.start()
        self.assertEqual(cm.exception.code, "VOICE-TTS-QWEN-API-UNSUPPORTED")

    def test_clone_api_missing_required_parameters_rejected(self):
        class Incompatible:
            def generate_voice_clone_streaming(self, text, language):
                return iter(())
        worker = QwenTTSWorker(self.config, model_factory=lambda c: Incompatible())
        with self.assertRaises(QwenTTSAdapterError):
            worker.start()

    def test_reference_disappearing_before_start_fails_closed(self):
        self.config.ref_audio.unlink()
        worker = QwenTTSWorker(self.config, model_factory=lambda c: self.fail("must validate before loading model"))
        with self.assertRaises(QwenTTSAdapterError) as cm:
            worker.start()
        self.assertEqual(cm.exception.code, "VOICE-TTS-QWEN-REFERENCE-MISSING")

    def test_warmup_and_live_generation_use_clone_parameters(self):
        model = CloneModel()
        config = replace(self.config, warmup_text="warmup")
        provider = create_qwen_provider(config, model_factory=lambda c: model)
        async def run():
            try:
                session = await provider.open(self.request("first"))
                await session.push_text("hello")
                await session.commit_text()
                events = [e async for e in session.audio_events()]
                self.assertEqual([e.kind for e in events], ["READY", "PCM_CHUNK", "PCM_CHUNK", "PCM_STREAM_END", "DONE"])
                self.assertEqual(events[0].payload["provider_id"], config.provider_id)
                self.assertEqual(session.metrics()["provider_id"], config.provider_id)
                self.assertEqual(session.health()["provider_id"], config.provider_id)
            finally:
                self.assertTrue(await provider.wait_idle_stopped(0.5))
                provider.shutdown(timeout_s=0.5)
        asyncio.run(run())
        self.assertEqual([c["text"] for c in model.calls], ["warmup", "hello"])
        for call in model.calls:
            self.assertEqual(call["ref_audio"], str(config.ref_audio))
            self.assertEqual(call["ref_text"], config.ref_text)
            self.assertNotIn("speaker", call)
            self.assertFalse(call["xvec_only"])
            self.assertFalse(call["non_streaming_mode"])

    def test_wrong_requested_voice_errors_without_fallback(self):
        model = CloneModel()
        provider = create_qwen_provider(self.config, model_factory=lambda c: model)
        async def run():
            try:
                session = await provider.open(self.request("wrong", voice_id="Vivian"))
                await session.push_text("hello")
                await session.commit_text()
                events = [e async for e in session.audio_events()]
                errors = [e for e in events if e.kind == "ERROR"]
                self.assertEqual(errors[0].code, "VOICE-TTS-QWEN-VOICE-UNSUPPORTED")
                self.assertEqual(model.calls, [])
            finally:
                self.assertTrue(await provider.wait_idle_stopped(0.5))
                provider.shutdown(timeout_s=0.5)
        asyncio.run(run())

    def test_cancel_then_followup_clone_turn(self):
        model = CloneModel()
        model.slow = True
        provider = create_qwen_provider(self.config, model_factory=lambda c: model)
        async def run():
            try:
                first = await provider.open(self.request("cancel"))
                await first.push_text("cancel me")
                await first.commit_text()
                async def collect():
                    return [e async for e in first.audio_events()]
                collector = asyncio.create_task(collect())
                await asyncio.sleep(0.04)
                self.assertTrue(await first.cancel("test-interrupt"))
                self.assertTrue(await first.wait_stopped(0.5))
                events = await collector
                self.assertIn("STOPPED", [e.kind for e in events])
                self.assertNotIn("DONE", [e.kind for e in events])
                self.assertTrue(await provider.wait_idle_stopped(0.5))
                model.slow = False
                second = await provider.open(self.request("followup", epoch=2))
                await second.push_text("next turn")
                await second.commit_text()
                events = [e async for e in second.audio_events()]
                self.assertEqual(events[-1].kind, "DONE")
                self.assertTrue(any(e.kind == "PCM_CHUNK" for e in events))
            finally:
                self.assertTrue(await provider.wait_idle_stopped(0.5))
                provider.shutdown(timeout_s=0.5)
        asyncio.run(run())

    def test_cancelled_closed_consumer_keeps_busy_until_producer_stops(self):
        entered, release = threading.Event(), threading.Event()
        class BlockingModel(CloneModel):
            def generate_voice_clone_streaming(self, **kwargs):
                entered.set()
                if not release.wait(3):
                    raise RuntimeError("test did not release producer")
                yield np.full(480, 0.1, dtype=np.float32), 24000, {}
        worker = QwenTTSWorker(self.config, model_factory=lambda c: BlockingModel())
        worker.start()
        try:
            session = worker.open(self.request("blocked"))
            session.push_text("first")
            session.commit_text()
            self.assertTrue(entered.wait(1))
            consumer = session.audio_events()
            self.assertEqual(next(consumer).kind, "READY")
            session.cancel("test")
            consumer.close()
            self.assertFalse(session.is_finished)
            self.assertFalse(session.is_drained)
            with self.assertRaises(QwenTTSAdapterError) as cm:
                worker.open(self.request("too-soon"))
            self.assertEqual(cm.exception.code, "VOICE-TTS-QWEN-SESSION-BUSY")
            release.set()
            session._thread.join(1)
            self.assertFalse(session._thread.is_alive())
            self.assertTrue(session.is_drained)
            followup = worker.open(self.request("after-stop"))
            followup.cancel("cleanup")
            list(followup.audio_events())
        finally:
            release.set()
            worker.stop()

    def test_uncancelled_finished_session_requires_consumer_drain(self):
        worker = QwenTTSWorker(self.config, model_factory=lambda c: CloneModel())
        worker.start()
        try:
            session = worker.open(self.request("undrained"))
            session.push_text("first")
            session.commit_text()
            session._thread.join(1)
            self.assertFalse(session._thread.is_alive())
            consumer = session.audio_events()
            self.assertEqual(next(consumer).kind, "READY")
            consumer.close()
            self.assertFalse(session.is_drained)
            with self.assertRaises(QwenTTSAdapterError) as cm:
                worker.open(self.request("too-soon"))
            self.assertEqual(cm.exception.code, "VOICE-TTS-QWEN-SESSION-BUSY")
            remaining = list(session.audio_events())
            self.assertIn("DONE", [e.kind for e in remaining])
            self.assertTrue(session.is_drained)
            followup = worker.open(self.request("after-drain"))
            followup.cancel("cleanup")
            list(followup.audio_events())
        finally:
            worker.stop()

    def test_cancel_after_finished_consumer_closed_releases_session(self):
        worker = QwenTTSWorker(self.config, model_factory=lambda c: CloneModel())
        worker.start()
        try:
            session = worker.open(self.request("late-cancel"))
            session.push_text("first")
            session.commit_text()
            session._thread.join(1)
            self.assertFalse(session._thread.is_alive())
            consumer = session.audio_events()
            next(consumer)
            consumer.close()
            self.assertFalse(session.is_drained)
            session.cancel("late-cancel")
            self.assertTrue(session.is_drained)
            followup = worker.open(self.request("after-late-cancel"))
            followup.cancel("cleanup")
            list(followup.audio_events())
        finally:
            worker.stop()

    def test_probe_reassesses_legacy_underrun_as_failure_not_control_failure(self):
        from backend.target_playback_probe import _finalize_acceptance
        result = {"closed": True, "scenario": "normal", "acceptance": dict.fromkeys(
            ["turn_completed", "audio_chunk_seen", "audio_done_seen", "port_drained",
             "entrypoint_untouched", "port_error_free"], True),
            "playback_metrics_before_shutdown": {"underrun_count": 1,
                "last_error_code": "VOICE-PLAYBACK-UNDERRUN"},
            "playback_events": [{"kind": "PLAYBACK_UNDERRUN", "code": "VOICE-PLAYBACK-UNDERRUN"}]}
        _finalize_acceptance(result)
        self.assertTrue(result["acceptance_groups"]["control_path_passed"])
        self.assertFalse(result["acceptance_groups"]["playback_continuity_passed"])
        self.assertFalse(result["acceptance"]["port_error_free"])
        self.assertFalse(result["acceptance_groups"]["all_automated_checks_passed"])

    def test_probe_missing_evidence_never_passes(self):
        from backend.target_playback_probe import _finalize_acceptance
        result = {}
        _finalize_acceptance(result)
        self.assertFalse(any(result["acceptance_groups"].values()))

    def test_probe_interrupt_then_followup_with_real_chain_and_fake_device(self):
        result = self.run_probe_simulation("interrupt-followup")
        self.assertTrue(result["acceptance"])
        self.assertTrue(all(result["acceptance"].values()), result)
        self.assertTrue(result["closed"])
        self.assertTrue(result["acceptance_groups"]["all_automated_checks_passed"])
        self.assertEqual(result["interruption"]["cancelled_status"], "interrupted")
        self.assertTrue(result["interruption"]["tts_stop_confirmed"])
        self.assertTrue(result["interruption"]["playback_stop_confirmed"])

    def test_probe_normal_with_real_chain_and_fake_device(self):
        result = self.run_probe_simulation("normal")
        self.assertTrue(all(result["acceptance"].values()), result)
        self.assertEqual(result["outcome"]["status"], "completed")

    def test_probe_retains_failures_and_closes_output(self):
        result = self.run_probe_simulation("normal", failing=True)
        self.assertFalse(result["acceptance"]["scenario_completed"])
        self.assertIn("provider_health_before_shutdown", result)
        self.assertIn("playback_metrics_before_shutdown", result)
        self.assertTrue(result["closed"])

    def run_probe_simulation(self, scenario, failing=False):
        from backend import target_playback_probe as probe
        from backend.target_composition import TargetVoiceComposition
        from backend.test_target_playback import _FakeSoundDevice
        class Device(_FakeSoundDevice):
            def check_output_settings(self, **kwargs):
                pass
        class Model(CloneModel):
            def generate_voice_clone_streaming(self, **kwargs):
                if failing:
                    raise RuntimeError("synthetic clone failure")
                for _ in range(60):
                    time.sleep(0.005)
                    yield np.full(480, 0.1, dtype=np.float32), 24000, {}
        device = Device()
        model = Model()
        def composition(config, **kwargs):
            return TargetVoiceComposition(config, provider_factory=lambda q:
                create_qwen_provider(q, model_factory=lambda c: model), **kwargs)
        def config(**kwargs):
            kwargs["warmup_text"] = None
            return build_target_qwen_config(root=self.root, tail_verify=False, **kwargs)
        with patch("sys.argv", ["probe", "--out-dir", "unused", "--output-device", "0", "--scenario", scenario,
                                "--interrupt-after-ms", "10", "--initial-buffer-ms", "20", "--turn-timeout-s", "3"]):
            args = probe._parse_args()
        async def run():
            async def pump():
                while True:
                    if device.stream is not None and device.stream.active:
                        device.stream.pump()
                    # The fake callback consumes 480 samples at 24 kHz: 20 ms.
                    # A 5 ms clock artificially drains audio at four times speed.
                    await asyncio.sleep(0.02)
            task = asyncio.create_task(pump())
            try:
                return await probe._run(args)
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        # Restore only this binding: restoring all sys.modules unloads native
        # extensions imported by the runtime and breaks subsequent tests.
        import sys
        missing = object()
        original = sys.modules.get("sounddevice", missing)
        sys.modules["sounddevice"] = device
        try:
            with patch.object(probe, "TargetVoiceComposition", side_effect=composition), \
                 patch.object(probe, "build_target_qwen_config", side_effect=config):
                return asyncio.run(run())
        finally:
            if original is missing:
                sys.modules.pop("sounddevice", None)
            else:
                sys.modules["sounddevice"] = original


    @staticmethod
    def request(speech_id, voice_id="default", epoch=1):
        return TTSRequest(session_id="clone-test", turn_id="turn-"+speech_id, speech_id=speech_id,
                          provider_epoch=epoch, voice_id=voice_id)


if __name__ == "__main__":
    unittest.main()
