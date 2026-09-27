"""Voice pipeline trace instrumentation (Phase 0, ledger 0507).

Non-invasive latency recorder: wraps existing pipeline stages and writes
per-turn JSONL to cache/voice_metrics/. No behavioral changes.

Trace events per turn:
  capture_start, speech_start, first_partial, speech_end,
  asr_final, llm_start, llm_first_delta, sentence_ready,
  tts_first_synth, playback_start, barge_in, playback_stop, turn_done

Usage (from console_server.py or any caller):
    from backend.voice_trace import VoiceTrace
    vt = VoiceTrace(session_id="s-xxx", turn_id=1)
    vt.mark("capture_start")
    ...
    vt.mark("turn_done")
    vt.flush()  # writes JSONL

Or use the context manager:
    with VoiceTrace(session_id="s-xxx", turn_id=1) as vt:
        vt.mark("capture_start")
        ...
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Optional

_METRICS_DIR = Path(__file__).resolve().parent.parent / "cache" / "voice_metrics"

_EVENTS = (
    "capture_start", "speech_start", "first_partial", "speech_end",
    "asr_final", "llm_start", "llm_first_delta", "sentence_ready",
    "tts_first_synth", "playback_start", "barge_in", "playback_stop",
    "turn_done",
)


class VoiceTrace:
    """Per-turn latency recorder. Thread-safe via GIL (append-only)."""

    def __init__(self, session_id: str = "", turn_id: int = 0,
                 generation: int = 0, trace_id: str = ""):
        self.session_id = session_id or f"s-{uuid.uuid4().hex[:8]}"
        self.turn_id = turn_id
        self.generation = generation
        self.trace_id = trace_id or f"trace_{uuid.uuid4().hex[:12]}"
        self._events: list[dict] = []
        self._t0 = time.monotonic()
        self._closed = False

    def mark(self, event: str, detail: str = "") -> None:
        if self._closed:
            return
        ts = time.monotonic()
        elapsed_ms = round((ts - self._t0) * 1000, 1)
        self._events.append({
            "event": event,
            "ts_mono_ms": round(ts * 1000, 1),
            "elapsed_ms": elapsed_ms,
            "detail": detail[:120],
        })

    def latency(self, start_event: str, end_event: str) -> Optional[float]:
        """Return elapsed_ms between two events, or None."""
        e0 = e1 = None
        for e in self._events:
            if e["event"] == start_event:
                e0 = e
            if e["event"] == end_event:
                e1 = e
        if e0 and e1:
            return round(e1["elapsed_ms"] - e0["elapsed_ms"], 1)
        return None

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "generation": self.generation,
            "trace_id": self.trace_id,
            "events": self._events,
            "total_ms": round((time.monotonic() - self._t0) * 1000, 1),
        }

    def flush(self) -> Path:
        """Write JSONL to cache/voice_metrics/<date>_<session>_<turn>.jsonl."""
        self._closed = True
        _METRICS_DIR.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        fname = f"{ts}_{self.session_id}_{self.turn_id}.jsonl"
        path = _METRICS_DIR / fname
        with path.open("w", encoding="utf-8") as f:
            f.write(json.dumps(self.to_dict(), ensure_ascii=False) + "\n")
        return path

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        if not self._closed:
            self.flush()
        return False


def load_recent(limit: int = 50) -> list[dict]:
    """Load recent trace records from cache/voice_metrics/."""
    if not _METRICS_DIR.exists():
        return []
    files = sorted(_METRICS_DIR.glob("*.jsonl"), reverse=True)[:limit]
    out = []
    for p in files:
        for line in p.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


def latency_report(records: list[dict]) -> dict:
    """Compute p50/p95 latency for key pipeline stages."""
    stages = [
        ("speech_to_final", "speech_start", "asr_final"),
        ("final_to_llm_delta", "asr_final", "llm_first_delta"),
        ("sentence_to_playback", "sentence_ready", "playback_start"),
        ("total_speech_to_playback", "speech_start", "playback_start"),
        ("barge_in_stop", "barge_in", "playback_stop"),
    ]
    report: dict[str, dict] = {}
    for name, ev_start, ev_end in stages:
        latencies = []
        for rec in records:
            events = rec.get("events", [])
            e0 = next((e for e in events if e["event"] == ev_start), None)
            e1 = next((e for e in events if e["event"] == ev_end), None)
            if e0 and e1:
                latencies.append(e1["elapsed_ms"] - e0["elapsed_ms"])
        if latencies:
            latencies.sort()
            p50 = latencies[len(latencies) // 2]
            p95 = latencies[int(len(latencies) * 0.95)]
            report[name] = {
                "count": len(latencies),
                "p50_ms": round(p50, 1),
                "p95_ms": round(p95, 1),
                "min_ms": round(latencies[0], 1),
                "max_ms": round(latencies[-1], 1),
            }
        else:
            report[name] = {"count": 0}
    return report
