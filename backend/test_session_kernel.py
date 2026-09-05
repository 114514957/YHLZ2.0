"""Isolated contract tests for the target session and data-safety boundaries."""

from __future__ import annotations

import json
import asyncio
import threading
import tempfile
import unittest
from pathlib import Path

from backend.memory_guard import MemoryWriteBlocked, ReadOnlyMemoryFacade
from backend.session_kernel import (
    AudioRoute,
    CancellationHandle,
    DuplexMode,
    ErrorCode,
    EventJournal,
    EventKind,
    KernelState,
    ProviderCapabilities,
    SessionKernel,
)
from backend.voice_gate import GateEvent, GateState, WakeWordGate


class _ControlledTask:
    def __init__(self, terminal: bool = True, fail_cancel: bool = False) -> None:
        self.terminal = terminal
        self.fail_cancel = fail_cancel
        self.cancelled = 0
        self.waited = []

    def cancel(self) -> None:
        self.cancelled += 1
        if self.fail_cancel:
            raise RuntimeError("cancel failed")

    def wait(self, timeout_s: float) -> bool:
        self.waited.append(timeout_s)
        return self.terminal


def _c_capabilities() -> ProviderCapabilities:
    return ProviderCapabilities(
        continuous_capture=True,
        concurrent_input_output=True,
        audio_route=AudioRoute.SPEAKER_MIC.value,
        audio_route_verified=True,
        vad_verified=True,
        wake_word_verified=True,
        aec_reference_available=True,
        aec_verified=True,
        echo_isolation_verified=False,
        asr_tts_concurrent=True,
        cancel_asr=True,
        cancel_generation=True,
        cancel_tts=True,
        cancel_playback=True,
        playback_verified=True,
        resource_budget_verified=True,
    )


class SessionKernelTests(unittest.TestCase):
    def test_capability_assessment_only_claims_c_when_all_requirements_hold(self) -> None:
        kernel = SessionKernel("sess_capability")
        assessment = kernel.start(
            ProviderCapabilities(
                continuous_capture=True,
                audio_route=AudioRoute.SPEAKER_MIC.value,
            )
        )

        self.assertEqual(assessment.mode, DuplexMode.B)
        self.assertIn("aec_verified", assessment.missing_for_c)
        self.assertEqual(kernel.state, KernelState.READY)
        errors = [event for event in kernel.recent_events() if event["kind"] == EventKind.ERROR.value]
        self.assertEqual(errors[-1]["payload"]["code"], ErrorCode.CAPABILITY_DEGRADED.value)

        full = SessionKernel("sess_c")
        self.assertEqual(full.start(_c_capabilities()).mode, DuplexMode.C)
        self.assertTrue(full.snapshot()["c_verified"])

    def test_headset_route_uses_isolation_evidence_instead_of_aec(self) -> None:
        headset = ProviderCapabilities(
            continuous_capture=True,
            concurrent_input_output=True,
            audio_route=AudioRoute.HEADSET.value,
            audio_route_verified=True,
            vad_verified=True,
            wake_word_verified=True,
            asr_tts_concurrent=True,
            cancel_asr=True,
            cancel_generation=True,
            cancel_tts=True,
            cancel_playback=True,
            playback_verified=True,
            resource_budget_verified=True,
            echo_isolation_verified=True,
        )
        self.assertEqual(SessionKernel("sess_headset").start(headset).mode, DuplexMode.C)

    def test_runtime_capability_downgrade_is_monotonic_and_keeps_turn_identity(self) -> None:
        kernel = SessionKernel("sess_runtime_degrade")
        kernel.start(_c_capabilities())
        turn = kernel.begin_turn("microphone", "audio")
        self.assertTrue(kernel.mark_input_final(turn))

        assessment = kernel.degrade_capability(
            "MEDIA-AEC-FAILED",
            reason="reference stream stopped",
            component="media",
        )
        self.assertEqual(assessment.mode, DuplexMode.B)
        self.assertEqual(kernel.snapshot()["active_turn_id"], turn.turn_id)
        self.assertFalse(kernel.snapshot()["c_verified"])

        events = kernel.recent_events()
        capability = [
            event for event in events
            if event["kind"] == EventKind.CAPABILITY.value
            and event["payload"].get("runtime")
        ]
        self.assertEqual(capability[-1]["turn_id"], turn.turn_id)
        self.assertEqual(capability[-1]["trace_id"], turn.trace_id)
        self.assertEqual(capability[-1]["payload"]["previous_mode"], DuplexMode.C.value)
        errors = [
            event for event in events
            if event["kind"] == EventKind.ERROR.value
            and event["payload"].get("code") == ErrorCode.CAPABILITY_DEGRADED.value
            and event["payload"].get("runtime")
        ]
        self.assertEqual(len(errors), 1)
        # Repeated adapter callbacks do not flood the Kernel with duplicate
        # capability transitions, while the original media events remain
        # independently observable through the relay.
        kernel.degrade_capability("MEDIA-AEC-FAILED", reason="reference stream stopped", component="media")
        repeated_errors = [
            event for event in kernel.recent_events()
            if event["kind"] == EventKind.ERROR.value
            and event["payload"].get("code") == ErrorCode.CAPABILITY_DEGRADED.value
            and event["payload"].get("runtime")
        ]
        self.assertEqual(len(repeated_errors), 1)

    def test_reopen_advances_generation_and_rejects_old_leases(self) -> None:
        kernel = SessionKernel("sess_reopen")
        kernel.start(_c_capabilities())
        old = kernel.begin_turn("text", "text")
        self.assertTrue(kernel.mark_input_final(old))
        kernel.stop()
        stopped_generation = kernel.snapshot()["generation"]

        kernel.reopen()
        self.assertGreater(kernel.snapshot()["generation"], stopped_generation)
        kernel.start(_c_capabilities())
        self.assertIsNone(kernel.publish_output(old, EventKind.TOKEN, {"text": "late"}))
        fresh = kernel.begin_turn("text", "text")
        self.assertNotEqual(fresh.generation, old.generation)
        self.assertTrue(kernel.mark_input_final(fresh))
        self.assertTrue(kernel.complete_turn(fresh))

    def test_superseded_turn_cannot_publish_late_output(self) -> None:
        kernel = SessionKernel("sess_stale")
        kernel.start(_c_capabilities())
        first = kernel.begin_turn("microphone", "audio")
        self.assertTrue(kernel.mark_input_final(first))

        second = kernel.begin_turn("microphone", "audio")
        self.assertTrue(kernel.mark_input_final(second))
        self.assertNotEqual(first.generation, kernel.snapshot()["generation"])
        self.assertIsNone(kernel.publish_output(first, EventKind.TOKEN, {"text": "old"}))
        self.assertIsNotNone(kernel.publish_output(second, EventKind.TOKEN, {"text": "new"}))

        stale = [event for event in kernel.recent_events() if event["kind"] == EventKind.STALE.value]
        self.assertEqual(stale[-1]["turn_id"], first.turn_id)
        self.assertTrue(kernel.complete_turn(second))
        self.assertEqual(kernel.state, KernelState.READY)

    def test_abort_waits_for_registered_tasks_and_records_timeout(self) -> None:
        kernel = SessionKernel("sess_abort")
        kernel.start(_c_capabilities())
        turn = kernel.begin_turn("websocket", "audio")
        completed = _ControlledTask(terminal=True)
        timed_out = _ControlledTask(terminal=False)
        kernel.register_cancellable(turn, CancellationHandle("llm", completed.cancel, completed.wait))
        kernel.register_cancellable(turn, CancellationHandle("tts", timed_out.cancel, timed_out.wait))

        result = kernel.abort_active_turn("barge_in", timeout_s=0.01)

        self.assertTrue(result.requested)
        self.assertEqual(completed.cancelled, 1)
        self.assertEqual(timed_out.cancelled, 1)
        self.assertIn("llm", result.completed_tasks)
        self.assertIn("tts", result.timed_out_tasks)
        self.assertEqual(kernel.snapshot()["generation"], 1)
        self.assertEqual(kernel.state, KernelState.READY)
        timeout_errors = [
            event for event in kernel.recent_events()
            if event["kind"] == EventKind.ERROR.value
            and event["payload"].get("code") == ErrorCode.TASK_CANCEL_TIMEOUT.value
        ]
        self.assertEqual(len(timeout_errors), 1)

    def test_async_abort_awaits_async_provider_terminal_state(self) -> None:
        async def scenario() -> None:
            kernel = SessionKernel("sess_async_abort")
            kernel.start(_c_capabilities())
            turn = kernel.begin_turn("websocket", "audio")
            cancelled = asyncio.Event()
            terminal = asyncio.Event()

            async def cancel() -> None:
                cancelled.set()
                await asyncio.sleep(0)
                terminal.set()

            async def wait_terminal(timeout_s: float) -> bool:
                try:
                    await asyncio.wait_for(terminal.wait(), timeout=max(timeout_s, 0.001))
                    return True
                except asyncio.TimeoutError:
                    return False

            kernel.register_cancellable(turn, CancellationHandle("async_llm", cancel, wait_terminal))
            result = await kernel.abort_active_turn_async("async_barge_in", timeout_s=0.2)
            self.assertTrue(cancelled.is_set())
            self.assertEqual(result.completed_tasks, ("async_llm",))
            self.assertEqual(result.timed_out_tasks, ())
            self.assertEqual(kernel.state, KernelState.READY)

        asyncio.run(scenario())

    def test_async_abort_bounds_a_hanging_sync_terminal_observer(self) -> None:
        async def scenario() -> None:
            kernel = SessionKernel("sess_sync_terminal")
            kernel.start(_c_capabilities())
            turn = kernel.begin_turn("websocket", "audio")
            entered = threading.Event()
            release = threading.Event()

            def cancel() -> None:
                return None

            def wait_terminal(timeout_s: float) -> bool:
                entered.set()
                release.wait(1.0)
                return True

            kernel.register_cancellable(
                turn,
                CancellationHandle("sync_wait", cancel, wait_terminal),
            )
            result = await asyncio.wait_for(
                kernel.abort_active_turn_async("sync_barge_in", timeout_s=0.01),
                timeout=0.1,
            )
            self.assertEqual(result.timed_out_tasks, ("sync_wait",))
            self.assertTrue(entered.is_set())
            self.assertEqual(kernel.state, KernelState.READY)
            release.set()
            await asyncio.sleep(0.01)

        asyncio.run(scenario())

    def test_failed_turn_has_failed_outcome_instead_of_interrupt(self) -> None:
        kernel = SessionKernel("sess_failed")
        kernel.start(_c_capabilities())
        turn = kernel.begin_turn("text", "text")
        kernel.mark_input_final(turn)
        self.assertTrue(kernel.fail_active_turn("PROVIDER_DOWN", "offline"))
        completes = [event for event in kernel.recent_events() if event["kind"] == EventKind.COMPLETE.value]
        self.assertEqual(completes[-1]["payload"]["outcome"], "failed")
        self.assertFalse(any(event["kind"] == EventKind.INTERRUPT.value for event in kernel.recent_events()))

    def test_completion_is_idempotent_from_the_kernel_perspective(self) -> None:
        kernel = SessionKernel("sess_complete")
        kernel.start(_c_capabilities())
        turn = kernel.begin_turn("text", "text")
        self.assertTrue(kernel.mark_input_final(turn))
        self.assertTrue(kernel.complete_turn(turn, committed=False))
        self.assertFalse(kernel.complete_turn(turn, committed=False))
        completes = [event for event in kernel.recent_events() if event["kind"] == EventKind.COMPLETE.value]
        self.assertEqual(len(completes), 1)

    def test_state_machine_rejects_speaking_before_input_is_final(self) -> None:
        kernel = SessionKernel("sess_transition")
        kernel.start(_c_capabilities())
        turn = kernel.begin_turn("microphone", "audio")
        self.assertFalse(kernel.mark_speaking(turn, "speech-early"))
        self.assertEqual(kernel.snapshot()["state"], KernelState.LISTENING.value)
        errors = [event for event in kernel.recent_events() if event["kind"] == EventKind.ERROR.value]
        self.assertEqual(errors[-1]["payload"]["code"], ErrorCode.INVALID_TRANSITION.value)

    def test_event_timestamp_is_utc_iso8601(self) -> None:
        kernel = SessionKernel("sess_time")
        kernel.start(_c_capabilities())
        timestamp = kernel.recent_events()[0]["timestamp"]
        self.assertIsInstance(timestamp, str)
        self.assertTrue(timestamp.endswith("+00:00"))

    def test_recent_events_are_defensive_copies(self) -> None:
        kernel = SessionKernel("sess_copy")
        kernel.start(_c_capabilities())
        snapshot = kernel.recent_events()
        snapshot[0]["payload"]["mode"] = "tampered"
        self.assertNotEqual(kernel.recent_events()[0]["payload"].get("mode"), "tampered")

    def test_system_event_relay_keeps_kernel_sequence_and_redaction_boundary(self) -> None:
        kernel = SessionKernel("sess_system_event")
        kernel.start(_c_capabilities())
        kernel.record_system_event(
            EventKind.TASK,
            {"component": "test", "text": "private", "details": {"nested": True}},
        )
        event = kernel.recent_events()[-1]
        self.assertEqual(event["kind"], EventKind.TASK.value)
        self.assertEqual(event["payload"]["text"], "[redacted]")

    def test_journal_writes_only_to_explicit_path_and_redacts_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "runtime" / "events.jsonl"
            journal = EventJournal(path=path)
            kernel = SessionKernel("sess_journal", journal=journal)
            kernel.start(_c_capabilities())
            turn = kernel.begin_turn("text", "text")
            kernel.publish_output(turn, EventKind.TOKEN, {"text": "private answer", "index": 1})

            self.assertTrue(path.is_file())
            rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            token = [row for row in rows if row["kind"] == EventKind.TOKEN.value][-1]
            self.assertEqual(token["payload"]["text"], "[redacted]")
            self.assertEqual(token["payload"]["index"], 1)

    def test_read_only_memory_facade_never_calls_a_writer(self) -> None:
        reads = []

        def reader(key: str) -> str:
            reads.append(key)
            return "value:" + key

        facade = ReadOnlyMemoryFacade(reader=reader)
        self.assertEqual(facade.get("identity"), "value:identity")
        self.assertEqual(reads, ["identity"])
        facade.reconnect()
        facade.restart_runtime()
        facade.reset_runtime()
        self.assertEqual(facade.runtime_status()["runtime_resets"], 1)
        with self.assertRaises(MemoryWriteBlocked):
            facade.clear()
        with self.assertRaises(MemoryWriteBlocked):
            facade.commit({"forbidden": True})


class WakeWordGateTests(unittest.TestCase):
    def test_wake_word_only_activates_from_idle(self) -> None:
        gate = WakeWordGate()
        ignored = gate.observe("你好", timestamp=1.0)
        self.assertEqual(ignored.event, GateEvent.IGNORED)
        activated = gate.observe("元 亨", timestamp=2.0)
        self.assertEqual(activated.event, GateEvent.ACTIVATED)
        self.assertEqual(activated.state, GateState.ACTIVE)
        accepted = gate.observe("继续说话", timestamp=3.0)
        self.assertEqual(accepted.event, GateEvent.INPUT_ACCEPTED)
        self.assertEqual(accepted.text, "继续说话")

    def test_wake_word_and_first_utterance_can_share_one_candidate(self) -> None:
        gate = WakeWordGate()
        decision = gate.observe("元亨帮我记个任务", timestamp=4.0)
        self.assertEqual(decision.event, GateEvent.INPUT_ACCEPTED)
        self.assertEqual(decision.text, "帮我记个任务")
        self.assertEqual(gate.state, GateState.ACTIVE)

    def test_near_wake_variants_activate_from_idle(self) -> None:
        gate = WakeWordGate()
        decision = gate.observe("元衡能听到吗", timestamp=4.5)
        self.assertEqual(decision.event, GateEvent.INPUT_ACCEPTED)
        self.assertIn("能听到吗", decision.text)
        self.assertEqual(gate.state, GateState.ACTIVE)
        gate.sleep()
        far = gate.observe("他元去了远方", timestamp=5.0)
        self.assertEqual(far.event, GateEvent.IGNORED)
        gate.sleep()
        spaced = gate.observe("元，亨，你好", timestamp=6.0)
        self.assertEqual(spaced.event, GateEvent.INPUT_ACCEPTED)

    def test_sleep_is_explicit_and_wake_word_is_not_required_again(self) -> None:
        gate = WakeWordGate()
        gate.observe("元亨", timestamp=5.0)
        gate.sleep(timestamp=6.0)
        self.assertEqual(gate.state, GateState.IDLE)
        self.assertEqual(gate.observe("普通话", timestamp=7.0).event, GateEvent.IGNORED)


if __name__ == "__main__":
    unittest.main(verbosity=2)
