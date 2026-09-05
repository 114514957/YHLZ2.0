"""Isolated tests for VAD-to-segment assembly."""

from __future__ import annotations

import unittest

from backend.media_adapter import AudioFrame, ProcessedAudioFrame
from backend.speech_segment import (
    SegmentEventKind,
    SpeechSegmentAssembler,
)


def _frame(
    sequence: int,
    generation: int,
    speech,
    payload: bytes | None = None,
    duration_ms: int = 0,
    sample_rate: int = 16_000,
    channels: int = 1,
):
    raw = payload if payload is not None else bytes([sequence])
    source = AudioFrame(
        samples=raw,
        sample_rate=sample_rate,
        channels=channels,
        sequence=sequence,
        generation=generation,
        duration_ms=duration_ms,
    )
    return ProcessedAudioFrame(
        frame=source,
        samples=raw,
        speech=speech,
        aec_applied=False,
    )


class SpeechSegmentAssemblerTests(unittest.TestCase):
    def test_preroll_and_vad_end_emit_one_bounded_segment(self) -> None:
        events = []
        assembler = SpeechSegmentAssembler(
            preroll_frames=2,
            end_silence_frames=1,
            on_event=events.append,
        )
        self.assertIsNone(assembler.push(_frame(1, 4, False)))
        self.assertIsNone(assembler.push(_frame(2, 4, False)))
        self.assertIsNone(assembler.push(_frame(3, 4, True)))
        self.assertIsNone(assembler.push(_frame(4, 4, True)))
        segment = assembler.push(_frame(5, 4, False))

        self.assertIsNotNone(segment)
        self.assertEqual(segment.first_sequence, 1)
        self.assertEqual(segment.last_sequence, 5)
        self.assertEqual(segment.frame_count, 5)
        self.assertEqual(segment.reason, "vad_end")
        self.assertEqual(segment.samples[0], b"\x01")
        self.assertEqual(events[0].kind, SegmentEventKind.OPENED.value)
        self.assertEqual(events[-1].kind, SegmentEventKind.EMITTED.value)
        self.assertEqual([event.event_seq for event in events], list(range(1, len(events) + 1)))

    def test_end_silence_can_require_multiple_frames(self) -> None:
        assembler = SpeechSegmentAssembler(preroll_frames=0, end_silence_frames=2)
        assembler.push(_frame(1, 1, True))
        self.assertIsNone(assembler.push(_frame(2, 1, False)))
        segment = assembler.push(_frame(3, 1, False))
        self.assertEqual(segment.last_sequence, 3)

    def test_generation_change_resets_old_segment_and_stale_old_frame_is_dropped(self) -> None:
        events = []
        assembler = SpeechSegmentAssembler(preroll_frames=1, on_event=events.append)
        assembler.push(_frame(1, 10, True))
        self.assertIsNone(assembler.push(_frame(0, 9, True)))
        self.assertEqual(assembler.generation, 10)
        new = assembler.push(_frame(1, 11, True))
        self.assertIsNone(new)
        self.assertEqual(assembler.generation, 11)
        self.assertTrue(any(event.kind == SegmentEventKind.STALE.value for event in events))
        self.assertTrue(any(event.kind == SegmentEventKind.RESET.value for event in events))

    def test_max_frames_forces_close_and_flush_is_explicit(self) -> None:
        assembler = SpeechSegmentAssembler(preroll_frames=0, max_frames=2)
        assembler.push(_frame(1, 2, True))
        forced = assembler.push(_frame(2, 2, True))
        self.assertEqual(forced.reason, "max_frames")
        self.assertFalse(assembler.active)
        assembler.push(_frame(3, 2, True))
        flushed = assembler.flush("shutdown")
        self.assertEqual(flushed.reason, "shutdown")
        self.assertIsNone(assembler.flush())

    def test_vad_unavailable_is_not_treated_as_silence(self) -> None:
        events = []
        assembler = SpeechSegmentAssembler(on_event=events.append)
        self.assertIsNone(assembler.push(_frame(1, 1, None)))
        self.assertFalse(assembler.active)
        self.assertEqual(events[-1].payload["code"], "SEGMENT-VAD-UNAVAILABLE")

    def test_duration_budget_closes_before_frame_budget(self) -> None:
        assembler = SpeechSegmentAssembler(
            preroll_frames=0,
            max_frames=100,
            max_duration_ms=100,
        )
        self.assertIsNone(assembler.push(_frame(1, 1, True, duration_ms=80)))
        segment = assembler.push(_frame(2, 1, True, duration_ms=40))
        self.assertIsNotNone(segment)
        self.assertEqual(segment.reason, "max_duration")
        self.assertEqual(segment.duration_ms, 120)
        self.assertEqual(assembler.snapshot()["active_duration_ms"], 0)

    def test_minimum_duration_drops_short_segment_with_evidence(self) -> None:
        events = []
        assembler = SpeechSegmentAssembler(
            preroll_frames=0,
            min_duration_ms=200,
            on_event=events.append,
        )
        assembler.push(_frame(1, 2, True, duration_ms=100))
        self.assertIsNone(assembler.push(_frame(2, 2, False, duration_ms=50)))
        self.assertFalse(assembler.active)
        dropped = [event for event in events if event.kind == SegmentEventKind.DROPPED.value]
        self.assertEqual(dropped[-1].payload["duration_ms"], 150)

    def test_explicit_capture_duration_is_used_over_payload_length(self) -> None:
        assembler = SpeechSegmentAssembler(preroll_frames=0)
        assembler.push(_frame(1, 3, True, payload=b"x", duration_ms=37))
        segment = assembler.flush("test")
        self.assertEqual(segment.duration_ms, 37)

    def test_format_change_is_rejected_even_while_frames_are_only_preroll(self) -> None:
        events = []
        assembler = SpeechSegmentAssembler(preroll_frames=2, on_event=events.append)
        self.assertIsNone(assembler.push(_frame(1, 4, False, sample_rate=16_000)))
        self.assertIsNone(assembler.push(_frame(2, 4, False, sample_rate=48_000)))
        self.assertEqual(assembler.snapshot()["preroll_frames"], 0)
        self.assertTrue(any(
            event.kind == SegmentEventKind.ERROR.value
            and event.payload.get("code") == "SEGMENT-FORMAT-CHANGED"
            for event in events
        ))
        # The next frame establishes a clean format after the rejected one.
        self.assertIsNone(assembler.push(_frame(3, 4, True, sample_rate=48_000)))
        segment = assembler.push(_frame(4, 4, False, sample_rate=48_000))
        self.assertEqual(segment.sample_rate, 48_000)


if __name__ == "__main__":
    unittest.main(verbosity=2)
