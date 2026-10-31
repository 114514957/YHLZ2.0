"""Bounded, content-free per-turn timings; callback output is NOT acoustic sound."""
from __future__ import annotations
import contextvars
import json
import re
import threading
import time
import uuid
from pathlib import Path

_save_lock = threading.Lock()
_TRACE_NAME = re.compile(r"[0-9a-f]{32}\.json\Z")

current_trace = contextvars.ContextVar("voice_turn_trace", default=None)

class VoiceTurnTrace:
    def __init__(self, route="unknown"):
        self.trace_id = uuid.uuid4().hex
        self.route = route
        self.turn_id = None
        self.generation = None
        self.events = {}
        self.status = "pending"
        self.error_code = None
        self._lock = threading.Lock()
        self.mark("request_received")

    def bind(self, lease):
        with self._lock:
            self.turn_id = lease.turn_id
            self.generation = lease.generation
        self.mark("turn_accepted")

    def mark(self, name):
        with self._lock:
            if name not in self.events and len(self.events) < 32:
                self.events[name] = time.perf_counter()

    def finish(self, status, error_code=None):
        with self._lock:
            self.status = status if status in {"completed", "failed", "cancelled", "ignored"} else "unknown"
            self.error_code = str(error_code)[:120] if error_code else None

    def snapshot(self):
        with self._lock:
            origin = self.events["request_received"]
            return {"trace_id": self.trace_id, "turn_id": self.turn_id,
                    "generation": self.generation, "route": self.route,
                    "status": self.status, "error_code": self.error_code,
                    "events_ms": {k: round((v-origin)*1000, 3) for k,v in self.events.items()},
                    "speech_end_measured": False, "acoustic_output_measured": False}

    def save(self, directory=None, *, max_files=500):
        if max_files < 1:
            raise ValueError("max_files must be positive")
        directory = Path(directory) if directory else Path(__file__).resolve().parents[1] / "artifacts" / "voice_turn_traces"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / (self.trace_id + ".json")
        # Only our UUID trace files are eligible; never traverse/delete folders.
        with _save_lock:
            path.write_text(json.dumps(self.snapshot(), ensure_ascii=False, indent=2), encoding="utf-8")
            files = [p for p in directory.iterdir()
                     if _TRACE_NAME.fullmatch(p.name) and p.is_file() and not p.is_symlink()]
            files.sort(key=lambda p: p.stat().st_mtime_ns, reverse=True)
            for stale in files[max_files:]:
                if stale != path:
                    stale.unlink(missing_ok=True)
        return path

def mark(name):
    trace = current_trace.get()
    if trace is not None:
        trace.mark(name)
