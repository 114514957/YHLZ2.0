"""S5 入站事件存储：有界热队列 + 保守去重 + JSONL 证据。

reader 侧只做收包与落库，不做昵称补查/LLM/TTS 等待；
native id 长窗去重，weak id 短窗去重（避免把两次真实重复发言永久合并）。
"""
from __future__ import annotations

import json
import threading
import time
from collections import Counter, deque
from pathlib import Path
from typing import Any, Optional

from backend.live.events import LiveEvent, now_ms

ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_LOG_PATH = ROOT / "cache" / "live" / "events.jsonl"


class EventStore:
    def __init__(self, path: Optional[Path] = None,
                 hot_capacity: int = 256,
                 native_dedup_window_s: float = 600.0,
                 weak_dedup_window_s: float = 10.0,
                 persist: bool = True,
                 time_fn=time.monotonic):
        self.path = Path(path) if path else DEFAULT_LOG_PATH
        self.hot_capacity = max(1, int(hot_capacity))
        self.native_dedup_window_s = float(native_dedup_window_s)
        self.weak_dedup_window_s = float(weak_dedup_window_s)
        self.persist = persist
        self._time = time_fn
        self.lock = threading.RLock()
        self._hot: deque[LiveEvent] = deque(maxlen=self.hot_capacity)
        self._seen: dict[str, float] = {}
        self.counters: Counter[str] = Counter()
        self.last_event_at_ms: Optional[int] = None

    def ingest(self, event: LiveEvent) -> dict[str, Any]:
        with self.lock:
            now = self._time()
            window = (self.weak_dedup_window_s if event.id_quality == "weak"
                      else self.native_dedup_window_s)
            seen_at = self._seen.get(event.dedup_key)
            if seen_at is not None and now - seen_at < window:
                self.counters["dup_dropped"] += 1
                return {"accepted": False, "reason": "duplicate",
                        "dedup_key": event.dedup_key, "event_id": event.event_id}
            self._seen[event.dedup_key] = now
            self._prune_seen(now)
            self._hot.append(event)
            self.counters["received"] += 1
            self.counters[f"kind:{event.kind}"] += 1
            self.last_event_at_ms = event.received_at
            if self.persist:
                self._append(event)
        return {"accepted": True, "reason": "ok", "event_id": event.event_id}

    def _prune_seen(self, now: float) -> None:
        if len(self._seen) <= 4096:
            return
        keep_after = now - max(self.native_dedup_window_s, self.weak_dedup_window_s)
        stale = [key for key, at in self._seen.items() if at < keep_after]
        for key in stale[:len(self._seen) - 2048]:
            self._seen.pop(key, None)

    def _append(self, event: LiveEvent) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            record = event.to_dict()
            record["ingested_at"] = now_ms()
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError:
            self.counters["persist_errors"] += 1

    def recent_raw(self, n: int = 8) -> list[dict[str, Any]]:
        with self.lock:
            events = list(self._hot)[-max(0, int(n)):]
            return [e.to_dict() for e in events]

    def summary(self) -> dict[str, Any]:
        with self.lock:
            return {
                "hot_len": len(self._hot),
                "hot_capacity": self.hot_capacity,
                "dedup_keys": len(self._seen),
                "counters": dict(sorted(self.counters.items())),
                "last_event_at_ms": self.last_event_at_ms,
            }
