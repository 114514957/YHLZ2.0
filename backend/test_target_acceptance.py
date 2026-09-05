"""Isolation tests for the explicit target full-duplex acceptance executor."""

from __future__ import annotations

import asyncio
import threading
import unittest

from backend.media_adapter import DeviceDescriptor
from backend.session_kernel import AudioRoute, ProviderCapabilities
from backend.target_acceptance import (
    AcceptanceAdapters,
    AcceptanceCheckEvidence,
    AcceptanceCheckStatus,
    AcceptanceRunStatus,
    AcceptanceThresholds,
    C_ACCEPTANCE_CHECKS,
    FullDuplexAcceptanceExecutor,
    inspect_acceptance_adapters,
)
from backend.tts_provider_port import TTSProviderCapabilities


def _device() -> DeviceDescriptor:
    return DeviceDescriptor(
        "probe-0",
        "test headset",
        1,
        2,
        sample_rate=16_000,
        route=AudioRoute.HEADSET.value,
    )


def _thresholds(**overrides) -> AcceptanceThresholds:
    values = {
        "per_check_timeout_s": 0.2,
        "total_timeout_s": 2.5,
        "max_stop_latency_ms": 50,
        "min_capture_frames": 2,
        "max_queue_depth": 4,
        "max_queue_duration_ms": 100,
    }
    values.update(overrides)
    return AcceptanceThresholds(**values)


def _capabilities() -> ProviderCapabilities:
    return ProviderCapabilities(audio_route=AudioRoute.HEADSET.value)


def _metrics(check: str) -> tuple[tuple[str, object], ...]:
    values = {
        "continuous_capture": {"capture_frames": 3},
        "route_and_echo_control": {
            "route_verified": True,
            "echo_control_verified": True,
        },
        "vad_and_wake_word": {
            "vad_segments": 1,
            "wake_word_detected": True,
        },
        "asr_tts_concurrent": {"concurrent_observed": True},
        "cancel_asr": {"cancelled": True, "stop_latency_ms": 5},
        "asr_stop_confirmed": {"stop_latency_ms": 5},
        "cancel_generation": {"cancelled": True},
        "cancel_tts": {"cancelled": True},
        "cancel_playback": {"cancelled": True, "stop_latency_ms": 5},
        "playback_stop_confirmed": {"stop_latency_ms": 5},
        "resource_budget": {"queue_depth": 1, "queue_duration_ms": 10},
    }
    return tuple(values[check].items())


class PassingProvider:
    def __init__(self) -> None:
        self.calls = []

    async def run_check(self, check, context):
        self.calls.append((check, context.media_generation, context.device.device_id))
        return AcceptanceCheckEvidence(
            check=check,
            status=AcceptanceCheckStatus.PASSED,
            duration_ms=1,
            code="CHECK-OBSERVED",
            metrics=_metrics(check),
        )


class SyncPassingProvider:
    def run_check(self, check, context):
        return AcceptanceCheckEvidence(
            check=check,
            status=AcceptanceCheckStatus.PASSED,
            duration_ms=1,
            code="CHECK-SYNC",
            metrics=_metrics(check),
        )


class PortInput:
    def start(self, callback, device):
        return None

    def stop(self):
        return None

    def health(self):
        return {"ok": True}


class PortVAD:
    def detect_speech(self, samples, sample_rate):
        return False


class PortASR:
    async def transcribe(self, segment, signal):
        return ""

    def interrupt(self):
        return None

    async def wait_stopped(self, timeout_s):
        return True


class PortReasoner:
    async def generate(self, text, signal):
        if False:
            yield ""


class PortSpeech:
    async def synthesize(self, text, signal):
        if False:
            yield b""

    def interrupt(self):
        return None

    async def wait_stopped(self, timeout_s):
        return True


class PortTTSProvider:
    def describe_capabilities(self):
        return TTSProviderCapabilities(
            provider_id="acceptance-provider",
            true_audio_stream=True,
            text_stream=True,
            cancel_observable=True,
            worker_isolated=True,
            worker_persistent=True,
        )

    def open(self, request):
        raise RuntimeError("not opened by static port inspection")

    def health(self):
        return {"state": "ready"}

    def metrics(self):
        return {"queue_depth": 0}


class PortPlayback:
    async def play(self, chunk, lease, signal):
        return None

    def interrupt(self):
        return None

    async def wait_stopped(self, timeout_s):
        return True


class PortAEC:
    def process(self, microphone, reference, sample_rate):
        return microphone


def _adapters(*, aec=None) -> AcceptanceAdapters:
    return AcceptanceAdapters(
        input_source=PortInput(),
        vad=PortVAD(),
        asr=PortASR(),
        reasoner=PortReasoner(),
        speech=PortSpeech(),
        playback=PortPlayback(),
        aec=aec,
    )


class FullDuplexAcceptanceExecutorTests(unittest.TestCase):
    def _executor(self, provider, **thresholds):
        return FullDuplexAcceptanceExecutor(
            provider=provider,
            device=_device(),
            adapters=_adapters(),
            thresholds=_thresholds(**thresholds),
            run_id="acceptance_test",
        )

    def test_missing_provider_is_not_executed_and_never_passes(self) -> None:
        async def scenario() -> None:
            report = await self._executor(None).run(
                media_generation=7,
                capabilities=_capabilities(),
            )
            self.assertEqual(report.status, AcceptanceRunStatus.NOT_EXECUTED)
            self.assertEqual(report.media_generation, 7)
            self.assertFalse(report.all_checks_passed)
            self.assertEqual(set(report.missing), set(C_ACCEPTANCE_CHECKS))
            self.assertTrue(
                all(
                    item.status is AcceptanceCheckStatus.NOT_EXECUTED
                    for item in report.evidence
                )
            )

        asyncio.run(scenario())

    def test_port_contract_rejects_missing_required_ports_without_running_provider(self) -> None:
        async def scenario() -> None:
            provider = PassingProvider()
            adapters = _adapters()
            incomplete = AcceptanceAdapters(
                input_source=adapters.input_source,
                vad=adapters.vad,
                asr=adapters.asr,
                reasoner=adapters.reasoner,
                speech=adapters.speech,
                playback=adapters.playback,
            )
            self.assertEqual(
                inspect_acceptance_adapters(incomplete, route=AudioRoute.HEADSET.value),
                (),
            )
            self.assertIn(
                "aec_process",
                inspect_acceptance_adapters(incomplete, route=AudioRoute.SPEAKER_MIC.value),
            )

            missing_playback = AcceptanceAdapters(
                input_source=adapters.input_source,
                vad=adapters.vad,
                asr=adapters.asr,
                reasoner=adapters.reasoner,
                speech=adapters.speech,
            )
            executor = FullDuplexAcceptanceExecutor(
                provider=provider,
                device=_device(),
                adapters=missing_playback,
                thresholds=_thresholds(),
            )
            report = await executor.run(media_generation=1, capabilities=_capabilities())
            self.assertEqual(report.status, AcceptanceRunStatus.NOT_EXECUTED)
            self.assertIn("playback_play", report.missing_ports)
            self.assertIn("playback_cancel", report.missing_ports)
            self.assertIn("playback_stop_observer", report.missing_ports)
            self.assertEqual(provider.calls, [])

        asyncio.run(scenario())

    def test_provider_port_is_accepted_without_legacy_synthesize_methods(self) -> None:
        adapters = _adapters()
        provider_adapters = AcceptanceAdapters(
            input_source=adapters.input_source,
            vad=adapters.vad,
            asr=adapters.asr,
            reasoner=adapters.reasoner,
            speech=PortTTSProvider(),
            playback=adapters.playback,
            aec=adapters.aec,
        )
        self.assertEqual(
            inspect_acceptance_adapters(
                provider_adapters,
                route=AudioRoute.HEADSET.value,
            ),
            (),
        )

    def test_structured_async_provider_produces_all_evidence(self) -> None:
        async def scenario() -> None:
            provider = PassingProvider()
            report = await self._executor(provider).run(
                media_generation=3,
                capabilities=_capabilities(),
            )
            self.assertEqual(report.status, AcceptanceRunStatus.PASSED)
            self.assertTrue(report.all_checks_passed)
            self.assertEqual([item.check for item in report.evidence], list(C_ACCEPTANCE_CHECKS))
            self.assertEqual(len(provider.calls), len(C_ACCEPTANCE_CHECKS))
            self.assertEqual(report.to_dict()["checks"].get("continuous_capture"), True)

        asyncio.run(scenario())

    def test_boolean_provider_result_is_error_not_a_pass(self) -> None:
        class BooleanProvider:
            async def run_check(self, check, context):
                return True

        async def scenario() -> None:
            report = await self._executor(BooleanProvider()).run(
                media_generation=1,
                capabilities=_capabilities(),
            )
            self.assertEqual(report.status, AcceptanceRunStatus.ERROR)
            self.assertTrue(
                all(item.code == "ACCEPTANCE-EVIDENCE-INVALID" for item in report.evidence)
            )
            self.assertFalse(report.all_checks_passed)

        asyncio.run(scenario())

    def test_threshold_violation_turns_provider_pass_into_failure(self) -> None:
        class SlowCaptureProvider(PassingProvider):
            async def run_check(self, check, context):
                evidence = await super().run_check(check, context)
                if check == "continuous_capture":
                    return AcceptanceCheckEvidence(
                        check=check,
                        status=AcceptanceCheckStatus.PASSED,
                        duration_ms=1,
                        code="CHECK-OBSERVED",
                        metrics=(("capture_frames", 1),),
                    )
                return evidence

        async def scenario() -> None:
            report = await self._executor(SlowCaptureProvider()).run(
                media_generation=1,
                capabilities=_capabilities(),
            )
            self.assertEqual(report.status, AcceptanceRunStatus.FAILED)
            first = report.evidence[0]
            self.assertEqual(first.status, AcceptanceCheckStatus.FAILED)
            self.assertEqual(first.code, "ACCEPTANCE-THRESHOLD-EXCEEDED")

        asyncio.run(scenario())

    def test_timeout_is_bounded_and_remaining_checks_are_not_claimed(self) -> None:
        class HangingProvider:
            async def run_check(self, check, context):
                await asyncio.sleep(0.05)

        async def scenario() -> None:
            report = await self._executor(
                HangingProvider(),
                per_check_timeout_s=0.005,
                total_timeout_s=0.02,
            ).run(media_generation=2, capabilities=_capabilities())
            self.assertIn(report.status, {AcceptanceRunStatus.FAILED, AcceptanceRunStatus.ERROR})
            self.assertTrue(
                any(item.status is AcceptanceCheckStatus.TIMED_OUT for item in report.evidence)
            )
            self.assertFalse(report.all_checks_passed)

        asyncio.run(scenario())

    def test_sync_provider_returning_awaitable_uses_the_same_check_budget(self) -> None:
        class SyncAwaitableProvider:
            def run_check(self, check, context):
                async def delayed():
                    await asyncio.sleep(0.05)
                    return AcceptanceCheckEvidence(
                        check=check,
                        status=AcceptanceCheckStatus.PASSED,
                        duration_ms=1,
                        code="CHECK-LATE",
                        metrics=_metrics(check),
                    )

                return delayed()

        async def scenario() -> None:
            executor = self._executor(
                SyncAwaitableProvider(),
                per_check_timeout_s=0.005,
                total_timeout_s=0.02,
            )
            report = await executor.run(
                media_generation=1,
                capabilities=_capabilities(),
            )
            self.assertEqual(report.status, AcceptanceRunStatus.FAILED)
            self.assertTrue(
                any(item.status is AcceptanceCheckStatus.TIMED_OUT for item in report.evidence)
            )
            self.assertTrue(report.pending_sync_work)
            for _ in range(20):
                if not executor.sync_cleanup_pending:
                    break
                await asyncio.sleep(0.005)
            self.assertFalse(executor.sync_cleanup_pending)

        asyncio.run(scenario())

    def test_second_run_is_rejected_while_an_executor_run_is_active(self) -> None:
        class BlockingProvider(PassingProvider):
            def __init__(self) -> None:
                super().__init__()
                self.started = asyncio.Event()
                self.release = asyncio.Event()

            async def run_check(self, check, context):
                self.calls.append((check, context.media_generation, context.device.device_id))
                if check == "continuous_capture":
                    self.started.set()
                    await self.release.wait()
                return AcceptanceCheckEvidence(
                    check=check,
                    status=AcceptanceCheckStatus.PASSED,
                    duration_ms=1,
                    code="CHECK-OBSERVED",
                    metrics=_metrics(check),
                )

        async def scenario() -> None:
            provider = BlockingProvider()
            executor = self._executor(provider)
            first_task = asyncio.create_task(
                executor.run(media_generation=1, capabilities=_capabilities())
            )
            await provider.started.wait()
            self.assertTrue(executor.running)
            second = await executor.run(media_generation=1, capabilities=_capabilities())
            self.assertEqual(second.status, AcceptanceRunStatus.NOT_EXECUTED)
            self.assertEqual(second.reason, "run_in_progress")
            self.assertEqual(len(provider.calls), 1)
            provider.release.set()
            first = await first_task
            self.assertEqual(first.status, AcceptanceRunStatus.PASSED)
            self.assertFalse(executor.running)

        asyncio.run(scenario())

    def test_sync_provider_runs_in_worker_without_changing_contract(self) -> None:
        async def scenario() -> None:
            report = await self._executor(SyncPassingProvider()).run(
                media_generation=4,
                capabilities=_capabilities(),
            )
            self.assertEqual(report.status, AcceptanceRunStatus.PASSED)
            self.assertTrue(report.all_checks_passed)

        asyncio.run(scenario())

    def test_timed_out_sync_worker_blocks_a_follow_up_until_it_returns(self) -> None:
        class HangingSyncProvider:
            def __init__(self) -> None:
                self.release = threading.Event()
                self.calls = 0

            def run_check(self, check, context):
                self.calls += 1
                if self.calls == 1:
                    self.release.wait(1.0)
                return AcceptanceCheckEvidence(
                    check=check,
                    status=AcceptanceCheckStatus.PASSED,
                    duration_ms=1,
                    code="CHECK-SYNC",
                    metrics=_metrics(check),
                )

        async def scenario() -> None:
            provider = HangingSyncProvider()
            executor = self._executor(
                provider,
                per_check_timeout_s=0.05,
                total_timeout_s=1.0,
            )
            first = await executor.run(media_generation=1, capabilities=_capabilities())
            self.assertEqual(first.status, AcceptanceRunStatus.FAILED)
            self.assertTrue(first.pending_sync_work)
            self.assertTrue(executor.sync_cleanup_pending)

            calls_after_first = provider.calls
            second = await executor.run(media_generation=1, capabilities=_capabilities())
            self.assertEqual(second.status, AcceptanceRunStatus.NOT_EXECUTED)
            self.assertEqual(second.reason, "pending_sync_cleanup")
            self.assertTrue(second.pending_sync_work)
            self.assertEqual(provider.calls, calls_after_first)

            provider.release.set()
            for _ in range(20):
                if not executor.sync_cleanup_pending:
                    break
                await asyncio.sleep(0.005)
            self.assertFalse(executor.sync_cleanup_pending)

            third = await executor.run(media_generation=1, capabilities=_capabilities())
            self.assertEqual(third.status, AcceptanceRunStatus.PASSED)
            self.assertFalse(third.pending_sync_work)

        asyncio.run(scenario())

    def test_invalid_or_sensitive_metrics_cannot_be_serialized_as_evidence(self) -> None:
        class SensitiveProvider:
            async def run_check(self, check, context):
                return AcceptanceCheckEvidence(
                    check=check,
                    status=AcceptanceCheckStatus.PASSED,
                    metrics=(("transcript", "secret"),),
                )

        async def scenario() -> None:
            report = await self._executor(SensitiveProvider()).run(
                media_generation=1,
                capabilities=_capabilities(),
            )
            self.assertEqual(report.status, AcceptanceRunStatus.ERROR)
            serialized = str(report.to_dict())
            self.assertNotIn("secret", serialized)
            self.assertTrue(all(item.status is AcceptanceCheckStatus.ERROR for item in report.evidence))

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main(verbosity=2)
