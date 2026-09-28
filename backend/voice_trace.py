"""Per-turn voice pipeline tracing and latency reporting."""
from __future__ import annotations

import json
import math
import threading
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
    """Thread-safe, immutable-on-flush trace for exactly one voice turn."""

    def __init__(self, session_id: str = "", turn_id: int = 0,
                 generation: int = 0, trace_id: str = ""):
        self.session_id = session_id or f"s-{uuid.uuid4().hex[:8]}"
        self.turn_id = turn_id
        self.generation = generation
        self.trace_id = trace_id or f"trace_{uuid.uuid4().hex[:12]}"
        self._events: list[dict] = []
        self._t0 = time.monotonic()
        self._closed = False
        self._lock = threading.RLock()
        self._path: Optional[Path] = None

    def mark(self, event: str, detail: str = "") -> None:
        """Append an event from any ASR/TTS/playback thread."""
        with self._lock:
            if self._closed:
                return
            ts = time.monotonic()
            self._events.append({
                "event": str(event),
                "ts_mono_ms": round(ts * 1000, 1),
                "elapsed_ms": round((ts - self._t0) * 1000, 1),
                "detail": str(detail)[:120],
            })

    def latency(self, start_event: str, end_event: str) -> Optional[float]:
        """Return the first end minus the first start, or None."""
        with self._lock:
            e0 = next((e for e in self._events
                       if e["event"] == start_event), None)
            e1 = next((e for e in self._events
                       if e["event"] == end_event), None)
        if e0 and e1:
            return round(e1["elapsed_ms"] - e0["elapsed_ms"], 1)
        return None

    def to_dict(self) -> dict:
        with self._lock:
            return {
                "session_id": self.session_id,
                "turn_id": self.turn_id,
                "generation": self.generation,
                "trace_id": self.trace_id,
                "events": [dict(e) for e in self._events],
                "total_ms": round((time.monotonic() - self._t0) * 1000, 1),
            }

    def flush(self) -> Path:
        """Write one JSONL file; repeated calls return the same path."""
        _METRICS_DIR.mkdir(parents=True, exist_ok=True)
        # Keep path publication and file writing under the same lock.  A second
        # caller may flush from a cleanup thread; it must not observe a path
        # whose JSONL body is still being written.
        with self._lock:
            if self._path is not None:
                return self._path
            self._closed = True
            record = self.to_dict()
            stamp = time.strftime("%Y%m%d_%H%M%S")
            millis = int(time.time() * 1000) % 1000
            filename = (f"{stamp}_{millis:03d}_{self.session_id}_t"
                        f"{self.turn_id}_{self.trace_id}.jsonl")
            path = _METRICS_DIR / filename
            with path.open("w", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
            self._path = path
            return path

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        if self._path is None:
            self.flush()
        return False


def load_recent(limit: int = 50) -> list[dict]:
    """Load recent per-turn trace records."""
    if not _METRICS_DIR.exists():
        return []
    files = sorted(_METRICS_DIR.glob("*.jsonl"), reverse=True)[:limit]
    out = []
    for path in files:
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        except OSError:
            continue
    return out


def latency_report(records: list[dict]) -> dict:
    """Report p50/p95 plus missing-event counts for key stages."""
    stages = [
        ("speech_to_final", "speech_start", "asr_final"),
        ("final_to_llm_delta", "asr_final", "llm_first_delta"),
        ("sentence_to_playback", "sentence_ready", "playback_start"),
        ("total_speech_to_playback", "speech_start", "playback_start"),
        ("barge_in_stop", "barge_in", "playback_stop"),
    ]
    report: dict[str, dict] = {}
    total = len(records)
    for name, ev_start, ev_end in stages:
        latencies = []
        missing_start = 0
        missing_end = 0
        for rec in records:
            events = rec.get("events", [])
            e0 = next((e for e in events if e.get("event") == ev_start), None)
            e1 = next((e for e in events if e.get("event") == ev_end), None)
            if e0 is None:
                missing_start += 1
            if e1 is None:
                missing_end += 1
            if e0 is not None and e1 is not None:
                latencies.append(float(e1["elapsed_ms"]) -
                                 float(e0["elapsed_ms"]))
        if latencies:
            latencies.sort()
            report[name] = {
                "count": len(latencies),
                "p50_ms": round(latencies[(len(latencies) - 1) // 2], 1),
                "p95_ms": round(latencies[max(0, math.ceil(len(latencies) * .95) - 1)], 1),
                "min_ms": round(latencies[0], 1),
                "max_ms": round(latencies[-1], 1),
                "missing_event_count": total - len(latencies),
                "missing_start_count": missing_start,
                "missing_end_count": missing_end,
            }
        else:
            report[name] = {
                "count": 0,
                "missing_event_count": total,
                "missing_start_count": missing_start,
                "missing_end_count": missing_end,
            }
    return report
