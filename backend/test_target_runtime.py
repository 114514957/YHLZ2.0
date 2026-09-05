"""End-to-end isolated tests for the target voice runtime wiring."""

from __future__ import annotations

import asyncio
import threading
import unittest
from dataclasses import replace
from types import SimpleNamespace

from backend.asr_bridge import ASRBridge
from backend.media_adapter import DeviceDescriptor, MediaAdapter, MediaError, MediaState
from backend.session_kernel import AudioRoute, DuplexMode, KernelError, ProviderCapabilities
from backend.speech_segment import SpeechSegmentAssembler
from backend.target_chain import AudioChunk, TargetVoiceChain
from backend.target_acceptance import (
    AcceptanceAdapters,
    AcceptanceCheckEvidence,
    AcceptanceCheckStatus,
    AcceptanceThresholds,
    FullDuplexAcceptanceExecutor,
)
from backend.target_probe import (
    DeviceProbe,
    EnvironmentProbeReport,
    ProbeStatus,
    select_input_device,
)
from backend.target_runtime import (
    AcceptanceStatus,
    C_ACCEPTANCE_CHECKS,
    FaultAction,
    FaultImportance,
    RuntimeFaultPolicy,
    RuntimeState,
    TargetVoiceRuntime,
)


class Source:
    def __init__(self) -> None:
        self.started = False
        self.stopped = False

    def start(self, callback, device) -> None:
        self.started = True
        self.stopped = False

    def stop(self) -> None:
        self.stopped = True

    def health(self) -> dict:
        return {"ok": self.started and not self.stopped}


class VAD:
    def __init__(self, values) -> None:
        self.values = list(values)

    def detect_speech(self, samples, sample_rate) -> bool:
        return bool(self.values.pop(0)) if self.values else False


class FailingAEC:
    def process(self, mic, reference, sample_rate):
        raise RuntimeError("aec probe failed")


class ASR:
    def __init__(self, values) -> None:
        self.values = list(values)

    async def transcribe(self, segment, signal):
        await asyncio.sleep(0)
        return self.values.pop(0)


class AcceptanceASR(ASR):
    def interrupt(self) -> None:
        pass

    async def wait_stopped(self, timeout_s: float) -> bool:
        return True


class UnconfirmedStopASR:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.interrupts = 0

    async def transcribe(self, segment, signal):
        self.started.set()
        await asyncio.Future()

    def interrupt(self) -> None:
        self.interrupts += 1

    async def wait_stopped(self, timeout_s: float) -> bool:
        await asyncio.sleep(0)
        return False


class ScriptedDuplexASR:
    def __init__(self, values) -> None:
        self.values = list(values)

    async def transcribe(self, segment, signal):
        await asyncio.sleep(0)
        return self.values.pop(0)


class Reasoner:
    def __init__(self) -> None:
        self.seen = []

    async def generate(self, text, signal):
        self.seen.append(text)
        yield "收到"


class DuplexReasoner:
    def __init__(self) -> None:
        self.seen = []

    async def generate(self, text, signal):
        self.seen.append(text)
        yield "旧回答" if text == "开始" else "新回答"


class DuplexSpeech:
    async def synthesize(self, text, signal):
        yield AudioChunk(b"duplex-audio", 24_000)

    def interrupt(self) -> None:
        pass

    async def wait_stopped(self, timeout_s: float) -> bool:
        return True


class GatePlayback:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.released = asyncio.Event()
        self.interrupts = 0
        self.played = []

    async def play(self, chunk, lease, signal):
        self.played.append((chunk.samples, lease.turn_id))
        if len(self.played) == 1:
            self.started.set()
            await self.released.wait()

    def interrupt(self) -> None:
        self.interrupts += 1
        self.released.set()


class AcceptancePlayback:
    async def play(self, chunk, lease, signal) -> None:
        return None

    def interrupt(self) -> None:
        pass

    async def wait_stopped(self, timeout_s: float) -> bool:
        return True


class LifecyclePlayback:
    """Minimal port with explicit lifecycle and relayable operational events."""

    def __init__(self) -> None:
        self.started = False
        self.closed = False
        self.on_event = None

    def start(self) -> None:
        self.started = True
        self.closed = False

    def close(self) -> None:
        self.closed = True

    def health(self) -> dict:
        return {
            "state": "stopped" if self.closed else "ready",
            "started": self.started and not self.closed,
            "queue_depth": 0,
            "queue_duration_ms": 0,
            "playing": False,
        }

    def emit_error(self, code: str) -> None:
        if self.on_event is not None:
            self.on_event(
                SimpleNamespace(
                    kind="PLAYBACK_ERROR",
                    code=code,
                    event_seq=1,
                    generation=1,
                    payload={"source": "fake"},
                )
            )


class PassingAcceptanceProvider:
    """Synthetic structured evidence provider for runtime contract tests."""

    _METRICS = {
        "continuous_capture": (("capture_frames", 3),),
        "route_and_echo_control": (
            ("route_verified", True),
            ("echo_control_verified", True),
        ),
        "vad_and_wake_word": (
            ("vad_segments", 1),
            ("wake_word_detected", True),
        ),
        "asr_tts_concurrent": (("concurrent_observed", True),),
        "cancel_asr": (("cancelled", True), ("stop_latency_ms", 5)),
        "asr_stop_confirmed": (("stop_latency_ms", 5),),
        "cancel_generation": (("cancelled", True),),
        "cancel_tts": (("cancelled", True),),
        "cancel_playback": (("cancelled", True), ("stop_latency_ms", 5)),
        "playback_stop_confirmed": (("stop_latency_ms", 5),),
        "resource_budget": (("queue_depth", 1), ("queue_duration_ms", 10)),
    }

    async def run_check(self, check, context):
        return AcceptanceCheckEvidence(
            check=check,
            status=AcceptanceCheckStatus.PASSED,
            duration_ms=1,
            code="CHECK-SYNTHETIC",
            metrics=self._METRICS[check],
        )


class CooperativeBlockingSyncAcceptanceProvider:
    """A worker-thread check that exits only after the runtime's signal."""

    def __init__(self) -> None:
        self.started = threading.Event()
        self.finished = threading.Event()
        self.cancellation_seen = False
        self._waiter = threading.Event()

    def run_check(self, check, context):
        if check == C_ACCEPTANCE_CHECKS[0]:
            self.started.set()
            while not context.cancellation_requested:
                self._waiter.wait(0.01)
            self.cancellation_seen = True
            self.finished.set()
        return AcceptanceCheckEvidence(
            check=check,
            status=AcceptanceCheckStatus.PASSED,
            duration_ms=1,
            code="CHECK-SYNTHETIC",
            metrics=PassingAcceptanceProvider._METRICS[check],
        )


class UncooperativeBlockingSyncAcceptanceProvider:
    """Models a third-party worker that cannot stop until it returns itself."""

    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()
        self.finished = threading.Event()

    def run_check(self, check, context):
        if check == C_ACCEPTANCE_CHECKS[0]:
            self.started.set()
            self.release.wait()
            self.finished.set()
        return AcceptanceCheckEvidence(
            check=check,
            status=AcceptanceCheckStatus.PASSED,
            duration_ms=1,
            code="CHECK-SYNTHETIC",
            metrics=PassingAcceptanceProvider._METRICS[check],
        )


def _acceptance_executor(
    runtime: TargetVoiceRuntime,
    device: DeviceDescriptor,
    provider=None,
):
    return FullDuplexAcceptanceExecutor(
        provider=provider or PassingAcceptanceProvider(),
        device=device,
        adapters=AcceptanceAdapters(
            input_source=runtime.media.source,
            vad=runtime.media.vad,
            asr=runtime.asr.asr,
            reasoner=runtime.chain.reasoner,
            speech=runtime.chain.speech,
            playback=runtime.chain.playback,
            aec=runtime.media.aec,
        ),
        thresholds=runtime.acceptance_thresholds,
    )


def _caps() -> ProviderCapabilities:
    return ProviderCapabilities(
        continuous_capture=True,
        concurrent_input_output=True,
        audio_route=AudioRoute.HEADSET.value,
        audio_route_verified=True,
        vad_verified=True,
        wake_word_verified=True,
        echo_isolation_verified=True,
        asr_tts_concurrent=True,
        cancel_asr=True,
        cancel_generation=True,
        cancel_tts=True,
        cancel_playback=True,
        playback_verified=True,
        resource_budget_verified=True,
    )


def _ready_environment_report(device_id: str) -> EnvironmentProbeReport:
    return EnvironmentProbeReport(
        status=ProbeStatus.READY,
        dependencies=(("sounddevice", True),),
        devices=(DeviceProbe(device_id, "fake headset", 1, 2, 16_000),),
        device_query_attempted=True,
    )


def _bind_input_selection(
    runtime: TargetVoiceRuntime,
    report: EnvironmentProbeReport,
    device: DeviceDescriptor,
) -> None:
    runtime.set_input_selection(
        select_input_device(
            report,
            device.device_id,
            route=device.route,
            reference_available=device.reference_available,
        )
    )


class TargetVoiceRuntimeTests(unittest.TestCase):
    def test_stereo_probe_can_bind_an_explicit_mono_capture_selection(self) -> None:
        source = Source()
        chain = TargetVoiceChain(reasoner=Reasoner())
        media = MediaAdapter(source=source, vad=VAD([]))
        bridge = ASRBridge(asr=ASR([]), chain=chain)
        report = EnvironmentProbeReport(
            status=ProbeStatus.READY,
            dependencies=(("sounddevice", True),),
            devices=(DeviceProbe("stereo-capture", "stereo microphone", 2, 0, 16_000),),
            device_query_attempted=True,
        )
        runtime = TargetVoiceRuntime(
            media=media,
            asr=bridge,
            chain=chain,
            environment_report=report,
        )
        selection = select_input_device(report, "stereo-capture", input_channels=1)
        runtime.set_input_selection(selection)
        self.assertEqual(runtime.health()["input_selection"]["device"]["input_channels"], 1)

    def test_runtime_opens_and_closes_the_explicit_playback_port(self) -> None:
        async def scenario() -> None:
            source = Source()
            playback = LifecyclePlayback()
            chain = TargetVoiceChain(reasoner=Reasoner(), playback=playback)
            media = MediaAdapter(source=source, vad=VAD([]))
            bridge = ASRBridge(asr=ASR([]), chain=chain)
            runtime = TargetVoiceRuntime(media=media, asr=bridge, chain=chain)
            device = DeviceDescriptor(
                "playback-lifecycle",
                "fake headset",
                1,
                2,
                route=AudioRoute.HEADSET.value,
            )

            runtime.start(device, _caps())
            self.assertTrue(playback.started)
            self.assertFalse(playback.closed)
            self.assertEqual(runtime.health()["playback"]["state"], "ready")

            await runtime.stop()
            self.assertTrue(playback.closed)
            self.assertEqual(runtime.health()["playback"]["state"], "stopped")

        asyncio.run(scenario())

    def test_playback_error_is_relayed_and_classified_as_a_core_fault(self) -> None:
        async def scenario() -> None:
            source = Source()
            playback = LifecyclePlayback()
            chain = TargetVoiceChain(reasoner=Reasoner(), playback=playback)
            media = MediaAdapter(source=source, vad=VAD([]))
            bridge = ASRBridge(asr=ASR([]), chain=chain)
            runtime = TargetVoiceRuntime(media=media, asr=bridge, chain=chain)
            device = DeviceDescriptor(
                "playback-fault",
                "fake headset",
                1,
                2,
                route=AudioRoute.HEADSET.value,
            )

            runtime.start(device, _caps())
            playback.emit_error("VOICE-PLAYBACK-STREAM-STATUS")

            faults = runtime.health()["faults"]
            self.assertEqual(faults[-1]["code"], "VOICE-PLAYBACK-STREAM-STATUS")
            self.assertEqual(faults[-1]["importance"], FaultImportance.CORE.value)
            self.assertEqual(faults[-1]["action"], FaultAction.RESTART_WHEN_IDLE.value)
            relayed = [
                event
                for event in chain.kernel.recent_events()
                if event["kind"] == "ERROR"
                and event["payload"].get("component") == "playback"
            ]
            self.assertTrue(relayed)

            await runtime.stop()

        asyncio.run(scenario())

    def test_c_health_requires_explicit_current_acceptance_record(self) -> None:
        async def scenario() -> None:
            source = Source()
            chain = TargetVoiceChain(
                reasoner=Reasoner(),
                speech=DuplexSpeech(),
                playback=AcceptancePlayback(),
            )
            media = MediaAdapter(source=source, vad=VAD([]))
            bridge = ASRBridge(asr=AcceptanceASR([]), chain=chain)
            device = DeviceDescriptor(
                "accepted",
                "fake headset",
                1,
                2,
                route=AudioRoute.HEADSET.value,
            )
            report = _ready_environment_report(device.device_id)
            runtime = TargetVoiceRuntime(
                media=media,
                asr=bridge,
                chain=chain,
                environment_report=report,
            )
            _bind_input_selection(runtime, report, device)
            self.assertEqual(runtime.start(device, _caps()).mode, DuplexMode.C)

            pending = runtime.health()
            self.assertEqual(pending["capability_mode"], DuplexMode.C.value)
            self.assertEqual(pending["mode"], DuplexMode.B.value)
            self.assertFalse(pending["c_verified"])
            self.assertEqual(pending["acceptance"]["status"], AcceptanceStatus.NOT_RUN.value)
            self.assertEqual(pending["input_selection"]["device"]["device_id"], device.device_id)

            acceptance = await runtime.execute_full_duplex_acceptance(
                _acceptance_executor(runtime, device)
            )
            self.assertEqual(acceptance.status, AcceptanceStatus.PASSED)
            verified = runtime.health()
            self.assertEqual(verified["mode"], DuplexMode.C.value)
            self.assertTrue(verified["c_verified"])
            self.assertTrue(verified["acceptance"]["c_verified"])

            await runtime.stop()
            stopped = runtime.health()
            self.assertEqual(stopped["mode"], DuplexMode.B.value)
            self.assertFalse(stopped["c_verified"])
            self.assertEqual(
                stopped["acceptance"]["status"],
                AcceptanceStatus.INVALIDATED.value,
            )

        asyncio.run(scenario())

    def test_untrusted_report_and_legacy_boolean_map_cannot_certify_c(self) -> None:
        async def scenario() -> None:
            source = Source()
            chain = TargetVoiceChain(
                reasoner=Reasoner(),
                speech=DuplexSpeech(),
                playback=AcceptancePlayback(),
            )
            media = MediaAdapter(source=source, vad=VAD([]))
            bridge = ASRBridge(asr=AcceptanceASR([]), chain=chain)
            device = DeviceDescriptor(
                "proof-bound",
                "fake headset",
                1,
                2,
                route=AudioRoute.HEADSET.value,
            )
            report = _ready_environment_report(device.device_id)
            runtime = TargetVoiceRuntime(
                media=media,
                asr=bridge,
                chain=chain,
                environment_report=report,
            )
            _bind_input_selection(runtime, report, device)
            runtime.start(device, _caps())

            rejected_map = runtime.record_full_duplex_acceptance(
                {name: True for name in C_ACCEPTANCE_CHECKS}
            )
            self.assertEqual(rejected_map.status, AcceptanceStatus.FAILED)
            self.assertIn("structured_acceptance_report_required", rejected_map.missing)
            self.assertFalse(runtime.health()["c_verified"])

            executor = _acceptance_executor(runtime, device)
            detached_report = await executor.run(
                media_generation=media.generation,
                capabilities=media.capabilities,
            )
            detached = runtime.record_full_duplex_acceptance_report(detached_report)
            self.assertEqual(detached.status, AcceptanceStatus.FAILED)
            self.assertIn("acceptance_report_provenance", detached.missing)
            self.assertFalse(runtime.health()["c_verified"])
            self.assertFalse(
                runtime.health()["acceptance_execution"]["valid_for_current_runtime"]
            )

            accepted = await runtime.execute_full_duplex_acceptance(
                _acceptance_executor(runtime, device)
            )
            self.assertEqual(accepted.status, AcceptanceStatus.PASSED)
            self.assertTrue(runtime.health()["c_verified"])
            self.assertTrue(
                runtime.health()["acceptance_execution"]["valid_for_current_runtime"]
            )
            await runtime.stop()

        asyncio.run(scenario())

    def test_acceptance_executor_must_bind_current_device_adapters_and_thresholds(self) -> None:
        async def scenario() -> None:
            source = Source()
            chain = TargetVoiceChain(
                reasoner=Reasoner(),
                speech=DuplexSpeech(),
                playback=AcceptancePlayback(),
            )
            media = MediaAdapter(source=source, vad=VAD([]))
            bridge = ASRBridge(asr=AcceptanceASR([]), chain=chain)
            device = DeviceDescriptor(
                "bound-runtime",
                "fake headset",
                1,
                2,
                route=AudioRoute.HEADSET.value,
            )
            report = _ready_environment_report(device.device_id)
            runtime = TargetVoiceRuntime(
                media=media,
                asr=bridge,
                chain=chain,
                environment_report=report,
            )
            _bind_input_selection(runtime, report, device)
            runtime.start(device, _caps())

            wrong_device = DeviceDescriptor(
                "other-device",
                "fake headset",
                1,
                2,
                route=AudioRoute.HEADSET.value,
            )
            with self.assertRaises(MediaError):
                await runtime.execute_full_duplex_acceptance(
                    FullDuplexAcceptanceExecutor(
                        provider=PassingAcceptanceProvider(),
                        device=wrong_device,
                        adapters=AcceptanceAdapters(),
                        thresholds=runtime.acceptance_thresholds,
                    )
                )

            with self.assertRaises(MediaError):
                await runtime.execute_full_duplex_acceptance(
                    FullDuplexAcceptanceExecutor(
                        provider=PassingAcceptanceProvider(),
                        device=device,
                        adapters=AcceptanceAdapters(),
                        thresholds=runtime.acceptance_thresholds,
                    )
                )

            with self.assertRaises(MediaError):
                await runtime.execute_full_duplex_acceptance(
                    FullDuplexAcceptanceExecutor(
                        provider=PassingAcceptanceProvider(),
                        device=device,
                        adapters=AcceptanceAdapters(
                            input_source=runtime.media.source,
                            vad=runtime.media.vad,
                            asr=runtime.asr.asr,
                            reasoner=runtime.chain.reasoner,
                            speech=runtime.chain.speech,
                            playback=runtime.chain.playback,
                            aec=runtime.media.aec,
                        ),
                        thresholds=replace(
                            runtime.acceptance_thresholds,
                            max_stop_latency_ms=runtime.acceptance_thresholds.max_stop_latency_ms + 1,
                        ),
                    )
                )
            self.assertFalse(runtime.health()["c_verified"])
            await runtime.stop()

        asyncio.run(scenario())

    def test_stop_cancels_cooperative_sync_acceptance_before_restart(self) -> None:
        async def scenario() -> None:
            source = Source()
            chain = TargetVoiceChain(
                reasoner=Reasoner(),
                speech=DuplexSpeech(),
                playback=AcceptancePlayback(),
            )
            media = MediaAdapter(source=source, vad=VAD([]))
            bridge = ASRBridge(asr=AcceptanceASR([]), chain=chain)
            device = DeviceDescriptor(
                "acceptance-stop-cooperative",
                "fake headset",
                1,
                2,
                route=AudioRoute.HEADSET.value,
            )
            report = _ready_environment_report(device.device_id)
            runtime = TargetVoiceRuntime(
                media=media,
                asr=bridge,
                chain=chain,
                environment_report=report,
                stop_timeout_s=0.5,
            )
            _bind_input_selection(runtime, report, device)
            runtime.start(device, _caps())
            provider = CooperativeBlockingSyncAcceptanceProvider()
            acceptance_task = asyncio.create_task(
                runtime.execute_full_duplex_acceptance(
                    _acceptance_executor(runtime, device, provider)
                )
            )
            self.assertTrue(
                await asyncio.wait_for(
                    asyncio.to_thread(provider.started.wait, 1.0),
                    timeout=1.1,
                )
            )

            await runtime.stop("test_acceptance_stop")

            with self.assertRaises(asyncio.CancelledError):
                await acceptance_task
            self.assertTrue(provider.cancellation_seen)
            self.assertTrue(provider.finished.is_set())
            self.assertEqual(runtime.state, RuntimeState.STOPPED)
            self.assertIsNone(runtime.health()["acceptance_execution"])
            cancel_events = [
                event
                for event in chain.kernel.recent_events()
                if event["kind"] == "TASK"
                and event["payload"].get("action")
                == "full_duplex_acceptance_cancel_requested"
            ]
            self.assertEqual(len(cancel_events), 1)

            await runtime.restart(device, _caps())
            await runtime.stop()

        asyncio.run(scenario())

    def test_restart_refuses_unfinished_sync_acceptance_cleanup(self) -> None:
        async def scenario() -> None:
            source = Source()
            chain = TargetVoiceChain(
                reasoner=Reasoner(),
                speech=DuplexSpeech(),
                playback=AcceptancePlayback(),
            )
            media = MediaAdapter(source=source, vad=VAD([]))
            bridge = ASRBridge(asr=AcceptanceASR([]), chain=chain)
            device = DeviceDescriptor(
                "acceptance-stop-uncooperative",
                "fake headset",
                1,
                2,
                route=AudioRoute.HEADSET.value,
            )
            report = _ready_environment_report(device.device_id)
            runtime = TargetVoiceRuntime(
                media=media,
                asr=bridge,
                chain=chain,
                environment_report=report,
                stop_timeout_s=0.05,
            )
            _bind_input_selection(runtime, report, device)
            runtime.start(device, _caps())
            provider = UncooperativeBlockingSyncAcceptanceProvider()
            acceptance_task = asyncio.create_task(
                runtime.execute_full_duplex_acceptance(
                    _acceptance_executor(runtime, device, provider)
                )
            )
            self.assertTrue(
                await asyncio.wait_for(
                    asyncio.to_thread(provider.started.wait, 1.0),
                    timeout=1.1,
                )
            )

            await runtime.stop("test_acceptance_cleanup")

            with self.assertRaises(asyncio.CancelledError):
                await acceptance_task
            execution = runtime.health()["acceptance_execution"]
            self.assertIsNotNone(execution)
            self.assertTrue(execution["in_progress"])
            self.assertTrue(execution["cleanup_pending"])
            with self.assertRaises(MediaError):
                await runtime.restart(device, _caps())
            self.assertEqual(runtime.state, RuntimeState.STOPPED)
            cleanup_errors = [
                event
                for event in chain.kernel.recent_events()
                if event["kind"] == "ERROR"
                and event["payload"].get("code")
                == "VOICE-C-ACCEPTANCE-CLEANUP-PENDING"
            ]
            self.assertEqual(len(cleanup_errors), 1)

            provider.release.set()
            for _ in range(100):
                await asyncio.sleep(0.01)
                if runtime.health()["acceptance_execution"] is None:
                    break
            self.assertTrue(provider.finished.is_set())
            self.assertIsNone(runtime.health()["acceptance_execution"])
            await runtime.restart(device, _caps())
            await runtime.stop()

        asyncio.run(scenario())

    def test_acceptance_thresholds_intersect_live_runtime_budgets(self) -> None:
        source = Source()
        chain = TargetVoiceChain(reasoner=Reasoner())
        media = MediaAdapter(
            source=source,
            vad=VAD([]),
            queue_capacity=4,
            max_queue_duration_ms=200,
        )
        bridge = ASRBridge(
            asr=ASR([]),
            chain=chain,
            assembler=SpeechSegmentAssembler(min_frames=3),
            cancel_timeout_s=0.1,
        )
        runtime = TargetVoiceRuntime(
            media=media,
            asr=bridge,
            chain=chain,
            stop_timeout_s=0.5,
            acceptance_thresholds=AcceptanceThresholds(
                per_check_timeout_s=5.0,
                total_timeout_s=60.0,
                max_stop_latency_ms=3_000,
                min_capture_frames=1,
                max_queue_depth=32,
                max_queue_duration_ms=5_000,
            ),
        )
        thresholds = runtime.acceptance_thresholds
        self.assertEqual(thresholds.max_stop_latency_ms, 100)
        self.assertEqual(thresholds.min_capture_frames, 3)
        self.assertEqual(thresholds.max_queue_depth, 4)
        self.assertEqual(thresholds.max_queue_duration_ms, 200)
        self.assertEqual(
            runtime.config_snapshot().to_dict()["acceptance_thresholds"],
            thresholds.to_dict(),
        )

    def test_failed_acceptance_is_journaled_without_claiming_c(self) -> None:
        async def scenario() -> None:
            source = Source()
            chain = TargetVoiceChain(reasoner=Reasoner())
            media = MediaAdapter(source=source, vad=VAD([]))
            bridge = ASRBridge(asr=ASR([]), chain=chain)
            runtime = TargetVoiceRuntime(media=media, asr=bridge, chain=chain)
            device = DeviceDescriptor(
                "unverified",
                "fake headset",
                1,
                2,
                route=AudioRoute.HEADSET.value,
            )
            runtime.start(device, _caps())

            acceptance = await runtime.execute_full_duplex_acceptance(
                _acceptance_executor(runtime, device)
            )
            self.assertEqual(acceptance.status, AcceptanceStatus.NOT_RUN)
            self.assertIn("environment_probe", acceptance.missing)
            self.assertIn("playback_stop_observable", acceptance.missing)
            self.assertIn("asr_stop_observable", acceptance.missing)
            self.assertIn("explicit_input_selection", acceptance.missing)
            self.assertIn(
                "playback_play",
                runtime.health()["acceptance_execution"]["missing_ports"],
            )
            self.assertFalse(runtime.health()["c_verified"])
            errors = [
                event
                for event in chain.kernel.recent_events()
                if event["kind"] == "ERROR"
                and event["payload"].get("code") == "VOICE-C-ACCEPTANCE-NOT-EXECUTED"
            ]
            self.assertTrue(errors)
            await runtime.stop()

        asyncio.run(scenario())

    def test_asr_stop_timeout_invalidates_acceptance_and_downgrades_runtime(self) -> None:
        async def scenario() -> None:
            source = Source()
            asr = UnconfirmedStopASR()
            chain = TargetVoiceChain(
                reasoner=Reasoner(),
                speech=DuplexSpeech(),
                playback=AcceptancePlayback(),
            )
            media = MediaAdapter(source=source, vad=VAD([True, False, True, False]))
            bridge = ASRBridge(
                asr=asr,
                chain=chain,
                assembler=SpeechSegmentAssembler(preroll_frames=0),
                cancel_timeout_s=0.1,
            )
            device = DeviceDescriptor(
                "asr-stop",
                "fake headset",
                1,
                2,
                route=AudioRoute.HEADSET.value,
            )
            report = _ready_environment_report(device.device_id)
            runtime = TargetVoiceRuntime(
                media=media,
                asr=bridge,
                chain=chain,
                environment_report=report,
            )
            _bind_input_selection(runtime, report, device)
            runtime.start(device, _caps())
            self.assertEqual(
                (
                    await runtime.execute_full_duplex_acceptance(
                        _acceptance_executor(runtime, device)
                    )
                ).status,
                AcceptanceStatus.PASSED,
            )
            self.assertTrue(runtime.health()["c_verified"])
            worker = asyncio.create_task(runtime.run())

            self.assertTrue(runtime.ingest(b"first"))
            self.assertTrue(runtime.ingest(b"first-end"))
            await asr.started.wait()
            self.assertTrue(runtime.ingest(b"second"))
            self.assertTrue(runtime.ingest(b"second-end"))
            await runtime.wait_idle()

            health = runtime.health()
            self.assertFalse(health["c_verified"])
            self.assertEqual(health["mode"], DuplexMode.B.value)
            self.assertEqual(
                health["acceptance"]["status"],
                AcceptanceStatus.INVALIDATED.value,
            )
            asr_faults = [
                item for item in health["faults"]
                if item["code"] == "ASR-CANCEL-TIMEOUT"
            ]
            self.assertEqual(len(asr_faults), 1)
            self.assertEqual(
                asr_faults[0]["importance"],
                FaultImportance.CORE.value,
            )
            capability_errors = [
                event
                for event in chain.kernel.recent_events()
                if event["kind"] == "ERROR"
                and event["payload"].get("code") == "VOICE-CAPABILITY-DEGRADED"
                and event["payload"].get("component") == "asr"
            ]
            self.assertTrue(capability_errors)

            await runtime.stop()
            await asyncio.wait_for(worker, timeout=1.0)

        asyncio.run(scenario())

    def test_bound_input_selection_rejects_a_different_runtime_device(self) -> None:
        source = Source()
        chain = TargetVoiceChain(reasoner=Reasoner())
        media = MediaAdapter(source=source, vad=VAD([]))
        bridge = ASRBridge(asr=ASR([]), chain=chain)
        selected = DeviceDescriptor(
            "selected",
            "fake headset",
            1,
            2,
            route=AudioRoute.HEADSET.value,
        )
        report = _ready_environment_report(selected.device_id)
        runtime = TargetVoiceRuntime(
            media=media,
            asr=bridge,
            chain=chain,
            environment_report=report,
        )
        _bind_input_selection(runtime, report, selected)
        different = DeviceDescriptor(
            "different",
            "other headset",
            1,
            2,
            route=AudioRoute.HEADSET.value,
        )
        with self.assertRaises(MediaError):
            runtime.start(different, _caps())
        self.assertFalse(source.started)

    def test_health_uses_injected_environment_report_without_probing(self) -> None:
        chain = TargetVoiceChain(reasoner=Reasoner())
        media = MediaAdapter(source=Source(), vad=VAD([]))
        bridge = ASRBridge(asr=ASR([]), chain=chain)
        report = EnvironmentProbeReport(
            status=ProbeStatus.UNAVAILABLE,
            dependencies=(("sounddevice", False),),
            reasons=("missing_dependencies:sounddevice",),
        )
        runtime = TargetVoiceRuntime(
            media=media,
            asr=bridge,
            chain=chain,
            environment_report=report,
        )
        health = runtime.health()
        self.assertEqual(health["environment"]["status"], ProbeStatus.UNAVAILABLE.value)
        self.assertFalse(health["environment"]["c_verified"])
        runtime.set_environment_report(None)
        self.assertIsNone(runtime.health()["environment"])

    def test_fault_policy_exposes_importance_without_triggering_recovery(self) -> None:
        policy = RuntimeFaultPolicy()
        aec = policy.decide("MEDIA-AEC-FAILED")
        self.assertEqual(aec.importance, FaultImportance.IMPORTANT)
        self.assertEqual(aec.action, FaultAction.DEGRADE_B)
        vad = policy.decide("MEDIA-VAD-FAILED")
        self.assertEqual(vad.importance, FaultImportance.CORE)
        self.assertEqual(vad.action, FaultAction.RESTART_WHEN_IDLE)
        unknown = policy.decide("SOMETHING-NEW")
        self.assertEqual(unknown.action, FaultAction.DEGRADE_B)

    def test_continuous_capture_allows_playback_barge_in_without_stale_audio_done(self) -> None:
        async def scenario() -> None:
            source = Source()
            reasoner = DuplexReasoner()
            playback = GatePlayback()
            chain = TargetVoiceChain(
                reasoner=reasoner,
                speech=DuplexSpeech(),
                playback=playback,
            )
            media = MediaAdapter(
                source=source,
                vad=VAD([True, False, True, False, True, False]),
            )
            bridge = ASRBridge(
                asr=ScriptedDuplexASR(["元亨", "开始", "打断"]),
                chain=chain,
                assembler=SpeechSegmentAssembler(preroll_frames=0),
            )
            runtime = TargetVoiceRuntime(media=media, asr=bridge, chain=chain)
            device = DeviceDescriptor("duplex", "fake headset", 1, 2, route=AudioRoute.HEADSET.value)
            runtime.start(device, _caps())
            worker = asyncio.create_task(runtime.run())

            # Idle activation, then a command that reaches a blocked playback.
            for payload in (b"wake", b"wake-end", b"command", b"command-end"):
                self.assertTrue(runtime.ingest(payload))
            await playback.started.wait()
            first_generation = chain.kernel.snapshot()["generation"]

            # Input remains accepted while the first response is speaking.
            self.assertTrue(runtime.ingest(b"barge-in"))
            self.assertTrue(runtime.ingest(b"barge-in-end"))
            await runtime.wait_idle()

            self.assertEqual(reasoner.seen, ["开始", "打断"])
            self.assertEqual(playback.interrupts, 1)
            self.assertGreater(chain.kernel.snapshot()["generation"], first_generation)
            self.assertEqual(runtime.health()["media"]["queue_depth"], 0)

            events = chain.kernel.recent_events()
            turn_ids = [
                event["turn_id"]
                for event in events
                if event["kind"] == "AUDIO_START"
            ]
            self.assertEqual(len(turn_ids), 2)
            done_turns = [
                event["turn_id"]
                for event in events
                if event["kind"] == "AUDIO_DONE"
            ]
            self.assertEqual(done_turns, [turn_ids[-1]])
            self.assertEqual(
                [event["seq"] for event in events],
                sorted(event["seq"] for event in events),
            )

            await runtime.stop()
            await asyncio.wait_for(worker, timeout=1.0)

        asyncio.run(scenario())

    def test_synthetic_microphone_reaches_reasoner_through_one_runtime(self) -> None:
        async def scenario() -> None:
            source = Source()
            reasoner = Reasoner()
            chain = TargetVoiceChain(reasoner=reasoner)
            media = MediaAdapter(source=source, vad=VAD([True, False, True, False]))
            bridge = ASRBridge(
                asr=ASR(["元亨", "继续"]),
                chain=chain,
                assembler=SpeechSegmentAssembler(preroll_frames=0),
            )
            runtime = TargetVoiceRuntime(media=media, asr=bridge, chain=chain)
            device = DeviceDescriptor("fake", "fake headset", 1, 2, route=AudioRoute.HEADSET.value)
            self.assertEqual(runtime.start(device, _caps()).mode, DuplexMode.C)
            self.assertEqual(runtime.state, RuntimeState.RUNNING)
            worker = asyncio.create_task(runtime.run())
            await asyncio.sleep(0)
            self.assertTrue(runtime.health()["run_task"])
            with self.assertRaises(MediaError):
                await runtime.run()

            self.assertTrue(runtime.ingest(b"wake"))
            self.assertTrue(runtime.ingest(b"wake-end"))
            self.assertTrue(runtime.ingest(b"utterance"))
            self.assertTrue(runtime.ingest(b"utterance-end"))
            await runtime.wait_idle()
            self.assertEqual(reasoner.seen, ["继续"])
            self.assertEqual(runtime.health()["session"]["duplex_mode"], DuplexMode.C.value)
            config = runtime.config_snapshot()
            self.assertEqual(config.version, "target-chain-v1")
            self.assertEqual(config.media_queue_capacity, 32)
            self.assertEqual(config.segment_max_duration_ms, 10_000)
            self.assertEqual(runtime.health()["config"], config.to_dict())
            correlated = [
                event for event in runtime.chain.kernel.recent_events()
                if event["payload"].get("event_kind") == "ASR_COMPLETED"
            ]
            self.assertTrue(correlated)
            self.assertIsNotNone(correlated[-1]["turn_id"])
            self.assertEqual(correlated[-1]["trace_id"].startswith("trace_"), True)
            self.assertNotIn("继续", str(correlated[-1]["payload"]))

            await runtime.stop()
            await asyncio.wait_for(worker, timeout=1.0)
            self.assertFalse(runtime.health()["run_task"])
            self.assertEqual(runtime.state, RuntimeState.STOPPED)
            self.assertEqual(media.state, MediaState.STOPPED)
            self.assertTrue(source.stopped)

        asyncio.run(scenario())

    def test_runtime_media_failure_downgrades_kernel_without_touching_turn_data(self) -> None:
        async def scenario() -> None:
            source = Source()
            chain = TargetVoiceChain(
                reasoner=Reasoner(),
                speech=DuplexSpeech(),
                playback=AcceptancePlayback(),
            )
            media = MediaAdapter(source=source, vad=VAD([True]), aec=FailingAEC())
            bridge = ASRBridge(
                asr=AcceptanceASR([]),
                chain=chain,
                assembler=SpeechSegmentAssembler(preroll_frames=0),
            )
            device = DeviceDescriptor(
                "speaker",
                "fake speaker mic",
                1,
                2,
                route=AudioRoute.SPEAKER_MIC.value,
                reference_available=True,
            )
            report = _ready_environment_report(device.device_id)
            runtime = TargetVoiceRuntime(
                media=media,
                asr=bridge,
                chain=chain,
                environment_report=report,
            )
            _bind_input_selection(runtime, report, device)
            speaker_caps = replace(
                _caps(),
                audio_route=AudioRoute.SPEAKER_MIC.value,
                aec_reference_available=True,
                aec_verified=True,
                echo_isolation_verified=False,
            )
            self.assertEqual(runtime.start(device, speaker_caps).mode, DuplexMode.C)
            self.assertEqual(
                (
                    await runtime.execute_full_duplex_acceptance(
                        _acceptance_executor(runtime, device)
                    )
                ).status,
                AcceptanceStatus.PASSED,
            )
            self.assertTrue(runtime.health()["c_verified"])
            worker = asyncio.create_task(runtime.run())
            self.assertTrue(runtime.ingest(b"mic", reference_samples=b"reference"))
            await runtime.wait_idle()

            health = runtime.health()
            self.assertEqual(health["media"]["mode"], DuplexMode.B.value)
            self.assertEqual(health["session"]["duplex_mode"], DuplexMode.B.value)
            self.assertFalse(health["session"]["c_verified"])
            self.assertEqual(
                health["acceptance"]["status"],
                AcceptanceStatus.INVALIDATED.value,
            )
            self.assertFalse(health["c_verified"])
            faults = health["faults"]
            self.assertEqual(faults[-1]["code"], "MEDIA-AEC-FAILED")
            self.assertEqual(faults[-1]["importance"], FaultImportance.IMPORTANT.value)
            self.assertEqual(faults[-1]["action"], FaultAction.DEGRADE_B.value)
            self.assertEqual(faults[-1]["count"], 1)
            capability_errors = [
                event for event in runtime.chain.kernel.recent_events()
                if event["kind"] == "ERROR"
                and event["payload"].get("code") == "VOICE-CAPABILITY-DEGRADED"
                and event["payload"].get("runtime")
            ]
            self.assertTrue(capability_errors)
            self.assertEqual(capability_errors[-1]["payload"]["component"], "media")
            self.assertIn("MEDIA-AEC-FAILED", capability_errors[-1]["payload"]["missing_for_c"])

            await runtime.stop()
            await asyncio.wait_for(worker, timeout=1.0)

        asyncio.run(scenario())

    def test_explicit_restart_rearms_only_runtime_state_and_preserves_session_journal(self) -> None:
        async def scenario() -> None:
            source = Source()
            reasoner = Reasoner()
            chain = TargetVoiceChain(reasoner=reasoner)
            media = MediaAdapter(
                source=source,
                vad=VAD([True, False, True, False, True, False, True, False]),
            )
            bridge = ASRBridge(
                asr=ASR(["元亨", "第一次", "元亨", "第二次"]),
                chain=chain,
                assembler=SpeechSegmentAssembler(preroll_frames=0),
            )
            runtime = TargetVoiceRuntime(media=media, asr=bridge, chain=chain)
            device = DeviceDescriptor("fake", "fake headset", 1, 2, route=AudioRoute.HEADSET.value)
            session_id = chain.kernel.session_id

            runtime.start(device, _caps())
            first_generation = media.generation
            worker = asyncio.create_task(runtime.run())
            self.assertTrue(runtime.ingest(b"wake"))
            self.assertTrue(runtime.ingest(b"wake-end"))
            self.assertTrue(runtime.ingest(b"utterance"))
            self.assertTrue(runtime.ingest(b"utterance-end"))
            await runtime.wait_idle()
            await runtime.stop()
            await asyncio.wait_for(worker, timeout=1.0)

            self.assertEqual(chain.kernel.snapshot()["state"], "stopped")
            self.assertEqual(chain.kernel.session_id, session_id)
            journal_size = len(chain.kernel.recent_events())

            self.assertEqual((await runtime.restart(device, _caps())).mode, DuplexMode.C)
            self.assertGreater(media.generation, first_generation)
            self.assertEqual(chain.kernel.session_id, session_id)
            self.assertGreater(len(chain.kernel.recent_events()), journal_size)
            worker2 = asyncio.create_task(runtime.run())
            self.assertTrue(runtime.ingest(b"wake-2"))
            self.assertTrue(runtime.ingest(b"wake-2-end"))
            self.assertTrue(runtime.ingest(b"utterance-2"))
            self.assertTrue(runtime.ingest(b"utterance-2-end"))
            await runtime.wait_idle()
            self.assertEqual(reasoner.seen, ["第一次", "第二次"])
            await runtime.stop()
            await asyncio.wait_for(worker2, timeout=1.0)

        asyncio.run(scenario())

    def test_startup_failure_rolls_back_media_source(self) -> None:
        async def scenario() -> None:
            source = Source()
            chain = TargetVoiceChain(reasoner=Reasoner())
            chain.kernel.stop()
            media = MediaAdapter(source=source, vad=VAD([]))
            bridge = ASRBridge(
                asr=ASR([]),
                chain=chain,
                assembler=SpeechSegmentAssembler(preroll_frames=0),
            )
            runtime = TargetVoiceRuntime(media=media, asr=bridge, chain=chain)
            device = DeviceDescriptor("fake", "fake", 1, 2, route=AudioRoute.HEADSET.value)
            with self.assertRaises(KernelError):
                runtime.start(device, _caps())
            self.assertEqual(runtime.state, RuntimeState.FAILED)
            self.assertTrue(source.stopped)
            self.assertFalse(runtime.ingest(b"discard"))
            await runtime.stop()

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main(verbosity=2)
