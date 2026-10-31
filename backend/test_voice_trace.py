"""Unit tests for per-turn voice tracing and latency aggregation."""
from __future__ import annotations

import json
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from backend import voice_trace
from backend.voice_trace import VoiceTrace, latency_report, load_recent


class VoiceTraceTests(unittest.TestCase):
    def test_concurrent_marks_are_retained_and_flush_is_idempotent(self) -> None:
        with TemporaryDirectory() as tmp:
            with mock.patch.object(voice_trace, "_METRICS_DIR", Path(tmp)):
                trace = VoiceTrace(session_id="test", turn_id=7)
                workers = []

                def mark_many(worker_id: int) -> None:
                    for index in range(25):
                        trace.mark("worker_event", f"{worker_id}:{index}")

                for worker_id in range(8):
                    worker = threading.Thread(target=mark_many, args=(worker_id,))
                    workers.append(worker)
                    worker.start()
                for worker in workers:
                    worker.join()

                first = trace.flush()
                second = trace.flush()
                self.assertEqual(first, second)
                self.assertTrue(first.exists())
                self.assertIn(trace.trace_id, first.name)
                record = json.loads(first.read_text(encoding="utf-8"))
                events = [event for event in record["events"]
                          if event["event"] == "worker_event"]
                self.assertEqual(len(events), 8 * 25)

                trace.mark("late_event")
                record_after = json.loads(first.read_text(encoding="utf-8"))
                self.assertFalse(any(event["event"] == "late_event"
                                     for event in record_after["events"]))

    def test_two_traces_have_independent_files(self) -> None:
        with TemporaryDirectory() as tmp:
            with mock.patch.object(voice_trace, "_METRICS_DIR", Path(tmp)):
                first = VoiceTrace(session_id="same", turn_id=1)
                second = VoiceTrace(session_id="same", turn_id=1)
                first.mark("capture_start")
                second.mark("capture_start")
                first_path = first.flush()
                second_path = second.flush()
                self.assertNotEqual(first.trace_id, second.trace_id)
                self.assertNotEqual(first_path, second_path)
                self.assertEqual(len(list(Path(tmp).glob("*.jsonl"))), 2)

    def test_latency_report_exposes_counts_and_handles_single_sample(self) -> None:
        records = [
            {
                "events": [
                    {"event": "speech_start", "elapsed_ms": 0},
                    {"event": "asr_final", "elapsed_ms": 120},
                    {"event": "llm_first_delta", "elapsed_ms": 220},
                    {"event": "barge_in", "elapsed_ms": 300},
                    {"event": "playback_stop", "elapsed_ms": 340},
                ]
            },
            {
                "events": [
                    {"event": "speech_start", "elapsed_ms": 0},
                    {"event": "asr_final", "elapsed_ms": 80},
                ]
            },
        ]
        report = latency_report(records)
        speech = report["speech_to_final"]
        self.assertEqual(speech["count"], 2)
        self.assertEqual(speech["p50_ms"], 80.0)
        self.assertEqual(speech["p95_ms"], 120.0)
        self.assertEqual(speech["missing_event_count"], 0)

        delta = report["final_to_llm_delta"]
        self.assertEqual(delta["count"], 1)
        self.assertEqual(delta["p50_ms"], 100.0)
        self.assertEqual(delta["p95_ms"], 100.0)
        self.assertEqual(delta["missing_end_count"], 1)

        barge = report["barge_in_stop"]
        self.assertEqual(barge["count"], 1)
        self.assertEqual(barge["p50_ms"], 40.0)
        self.assertEqual(barge["p95_ms"], 40.0)

    def test_load_recent_skips_invalid_json(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            with mock.patch.object(voice_trace, "_METRICS_DIR", root):
                (root / "a.jsonl").write_text(
                    '{"trace_id":"ok"}\nnot-json\n', encoding="utf-8")
                records = load_recent()
                self.assertEqual(records, [{"trace_id": "ok"}])


if __name__ == "__main__":
    unittest.main()
