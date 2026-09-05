"""Contract tests for target-runtime event classification and redaction."""

from __future__ import annotations

from types import SimpleNamespace
import unittest

from backend.runtime_events import RuntimeEventRelay
from backend.session_kernel import AudioRoute, EventKind, ProviderCapabilities, SessionKernel


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


class RuntimeEventRelayTests(unittest.TestCase):
    def test_backpressure_is_an_error_and_payload_is_redacted(self) -> None:
        kernel = SessionKernel("sess_relay")
        kernel.start(_caps())
        relay = RuntimeEventRelay(kernel)
        relay.media(
            SimpleNamespace(
                kind="MEDIA_BACKPRESSURE",
                code="MEDIA-BACKPRESSURE-DURATION",
                event_seq=7,
                generation=0,
                payload={"text": "private", "queue_depth": 3},
            )
        )

        event = kernel.recent_events()[-1]
        self.assertEqual(event["kind"], EventKind.ERROR.value)
        self.assertEqual(event["payload"]["details"]["text"], "[redacted]")
        self.assertEqual(event["payload"]["details"]["queue_depth"], 3)
        self.assertIsNone(event["turn_id"])

    def test_asr_correlation_fields_are_forwarded_as_public_event_fields(self) -> None:
        kernel = SessionKernel("sess_asr_relay")
        kernel.start(_caps())
        turn = kernel.begin_turn("microphone", "transcript")
        relay = RuntimeEventRelay(kernel)
        relay.asr(
            SimpleNamespace(
                kind="ASR_COMPLETED",
                code=None,
                event_seq=2,
                generation=turn.generation,
                turn_id=turn.turn_id,
                trace_id=turn.trace_id,
                payload={"text_length": 4},
            )
        )

        event = kernel.recent_events()[-1]
        self.assertEqual(event["kind"], EventKind.TASK.value)
        self.assertEqual(event["turn_id"], turn.turn_id)
        self.assertEqual(event["trace_id"], turn.trace_id)
        self.assertEqual(event["generation"], turn.generation)


if __name__ == "__main__":
    unittest.main(verbosity=2)
