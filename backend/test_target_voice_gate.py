"""Unit tests for the playback-reference voice gate (对话DEMO borrow)."""

from __future__ import annotations

import unittest

from backend.target_voice_gate import (
    ECHO_GAIN_RATIO,
    PlaybackReferenceVoiceGate,
    auto_voice_gate,
    is_voice_gate,
)


class PlaybackReferenceVoiceGateTests(unittest.TestCase):
    def test_permissive_when_playback_silent(self) -> None:
        gate = PlaybackReferenceVoiceGate(lambda: 0.0)
        self.assertTrue(gate.allow(0.001))
        self.assertTrue(gate.allow(0.0))

    def test_blocks_frame_below_ratio(self) -> None:
        gate = PlaybackReferenceVoiceGate(lambda: 0.10)
        self.assertFalse(gate.allow(0.05))
        self.assertFalse(gate.allow(0.159))
        self.assertTrue(gate.allow(0.16 * ECHO_GAIN_RATIO))

    def test_allows_clearly_above(self) -> None:
        gate = PlaybackReferenceVoiceGate(lambda: 0.20)
        self.assertTrue(gate.allow(0.33))

    def test_requires_callable(self) -> None:
        with self.assertRaises(TypeError):
            PlaybackReferenceVoiceGate(object())  # type: ignore[arg-type]

    def test_auto_gate_from_playback_port(self) -> None:
        class Port:
            def playback_rms(self) -> float:
                return 1.0

        gate = auto_voice_gate(Port())
        self.assertIsNotNone(gate)
        self.assertTrue(is_voice_gate(gate))
        self.assertFalse(gate.allow(1.0))  # 1.0 < 1.6

    def test_no_gate_without_reference(self) -> None:
        self.assertIsNone(auto_voice_gate(object()))


if __name__ == "__main__":
    unittest.main()
