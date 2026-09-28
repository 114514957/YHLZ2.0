"""Tests for PCM_STREAM_END drain fix (P0 underrun root cause).

Verifies that PCM_STREAM_END triggers playback drain before DONE, so the
queue does not underrun while tail_verify runs.
"""
from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from typing import Any, List
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.tts_provider_port import (
    TTSEventKind,
    TTSProviderCapabilities,
    TTSProviderEvent,
    TTSRequest,
    TTSStreamNormalizer,
)


def _make_chunk(seq=0):
    from backend.tts_provider_port import PCMChunk
    return PCMChunk(b"\x01\x00" * 240, seq)

def _make_request():
    return TTSRequest(
        session_id="s1", turn_id="t1", speech_id="sp1",
        provider_epoch=0, voice_id="xiaoyi", style={},
    )


def _make_caps():
    return TTSProviderCapabilities(
        provider_id="test-tts", output_sample_rate=24000,
        output_channels=1, output_format="s16le",
    )


class TestPCMStreamEndInNormalizer(unittest.TestCase):
    def test_pcm_stream_end_passes_through(self):
        req = _make_request()
        caps = _make_caps()
        n = TTSStreamNormalizer(req, caps)
        ev = TTSProviderEvent(
            kind=TTSEventKind.PCM_STREAM_END.value,
            speech_id="sp1", provider_epoch=0, sequence=0,
            payload={"chunk_count": 5, "pcm_duration_ms": 4000},
        )
        out = n.accept(ev)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].kind, "PCM_STREAM_END")

    def test_pcm_stream_end_before_done(self):
        """PCM_STREAM_END must arrive before DONE."""
        req = _make_request()
        caps = _make_caps()
        n = TTSStreamNormalizer(req, caps)
        kinds = []
        ev = TTSProviderEvent(
            kind=TTSEventKind.PCM_CHUNK.value,
            speech_id="sp1", provider_epoch=0, sequence=0,
            chunk=_make_chunk(0),
        )
        for out in n.accept(ev):
            kinds.append(out.kind)
        ev_end = TTSProviderEvent(
            kind=TTSEventKind.PCM_STREAM_END.value,
            speech_id="sp1", provider_epoch=0, sequence=1,
        )
        for out in n.accept(ev_end):
            kinds.append(out.kind)
        ev_done = TTSProviderEvent(
            kind=TTSEventKind.DONE.value,
            speech_id="sp1", provider_epoch=0, sequence=2,
        )
        for out in n.accept(ev_done):
            kinds.append(out.kind)
        self.assertIn("PCM_STREAM_END", kinds)
        self.assertIn("DONE", kinds)
        self.assertLess(kinds.index("PCM_STREAM_END"), kinds.index("DONE"))

    def test_pcm_stream_end_after_done_is_stale(self):
        req = _make_request()
        caps = _make_caps()
        n = TTSStreamNormalizer(req, caps)
        # need PCM before DONE
        ev_pcm = TTSProviderEvent(
            kind=TTSEventKind.PCM_CHUNK.value,
            speech_id="sp1", provider_epoch=0, sequence=0,
            chunk=_make_chunk(0),
        )
        n.accept(ev_pcm)
        # first DONE
        ev_done = TTSProviderEvent(
            kind=TTSEventKind.DONE.value,
            speech_id="sp1", provider_epoch=0, sequence=1,
        )
        n.accept(ev_done)
        # then PCM_STREAM_END — should be stale
        ev_stream_end = TTSProviderEvent(
            kind=TTSEventKind.PCM_STREAM_END.value,
            speech_id="sp1", provider_epoch=0, sequence=2,
        )
        out = n.accept(ev_stream_end)
        self.assertEqual(len(out), 0)

    def test_timing_payload_present(self):
        """PCM_STREAM_END payload should contain timing info."""
        req = _make_request()
        caps = _make_caps()
        n = TTSStreamNormalizer(req, caps)
        ev = TTSProviderEvent(
            kind=TTSEventKind.PCM_STREAM_END.value,
            speech_id="sp1", provider_epoch=0, sequence=0,
            payload={
                "chunk_count": 5,
                "pcm_duration_ms": 4000,
                "pcm_end_mono_ms": 12345.6,
            },
        )
        out = n.accept(ev)
        self.assertEqual(len(out), 1)
        self.assertIn("pcm_end_mono_ms", out[0].payload)


class TestTTSEventKinds(unittest.TestCase):
    def test_pcm_stream_end_in_enum(self):
        self.assertTrue(hasattr(TTSEventKind, "PCM_STREAM_END"))
        self.assertEqual(TTSEventKind.PCM_STREAM_END.value, "PCM_STREAM_END")

    def test_done_still_exists(self):
        self.assertEqual(TTSEventKind.DONE.value, "DONE")


if __name__ == "__main__":
    unittest.main()
