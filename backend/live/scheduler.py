"""S5 选题编排：候选池（TTL/容量/聚合）→ 每轮一个主题（最多 3 条来源）。

程序筛选候选 + 一次元亨生成；不逐条弹幕两次 LLM，不无限自说。
优先级：主人控制 > 重点事件 > 普通相关弹幕 > 冷场话题。
冷场稿可被新弹幕取消（由后续生成/播放代际负责）。
"""
from __future__ import annotations

import difflib
import re
import threading
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from backend.live.events import LiveEvent

_PUNCT_RE = re.compile(r"[\s，。！？!?,.、~～…·:：;；\"'“”‘’()（）\[\]【】]+")


def normalize_text(text: str) -> str:
    return _PUNCT_RE.sub("", str(text or "")).lower()


@dataclass
class Candidate:
    event: LiveEvent
    added_at: float
    state: str = "pending"
    sources: list[LiveEvent] = field(default_factory=list)

    @property
    def priority(self) -> str:
        return self.event.priority

    def all_sources(self) -> list[LiveEvent]:
        return [self.event] + list(self.sources)


class TopicScheduler:
    def __init__(self, *, ttl_s: float = 30.0, capacity: int = 100,
                 aggregation_window_s: float = 0.8,
                 max_turn_sources: int = 3,
                 cold_idle_s: float = 30.0,
                 cold_min_interval_s: float = 90.0,
                 similarity_ratio: float = 0.86,
                 time_fn: Callable[[], float] = time.monotonic):
        self.ttl_s = float(ttl_s)
        self.capacity = max(1, int(capacity))
        self.aggregation_window_s = float(aggregation_window_s)
        self.max_turn_sources = max(1, int(max_turn_sources))
        self.cold_idle_s = float(cold_idle_s)
        self.cold_min_interval_s = float(cold_min_interval_s)
        self.similarity_ratio = float(similarity_ratio)
        self._time = time_fn
        self.lock = threading.RLock()
        self._pending: list[Candidate] = []
        self._turn_seq = 0
        self._last_event_at: Optional[float] = None
        self._last_pick_at: Optional[float] = None
        self._last_cold_at: Optional[float] = None
        self.counters: Counter[str] = Counter()

    def offer(self, event: LiveEvent) -> dict[str, Any]:
        with self.lock:
            now = self._time()
            self._expire_locked(now)
            self._last_event_at = now
            self.counters["offered"] += 1
            if len(self._pending) >= self.capacity:
                dropped = self._pending.pop(0)
                dropped.state = "dropped"
                self.counters["dropped_capacity"] += 1
            merged = self._try_coalesce_locked(event, now)
            if merged is not None:
                self.counters["coalesced"] += 1
                return {"state": "coalesced", "candidate_id": id(merged)}
            self._pending.append(Candidate(event=event, added_at=now))
            return {"state": "pending", "pending": len(self._pending)}

    def _try_coalesce_locked(self, event: LiveEvent, now: float) -> Optional[Candidate]:
        if event.kind != "chat":
            return None
        norm = normalize_text(event.text)
        for candidate in self._pending:
            if candidate.state != "pending" or candidate.event.kind != "chat":
                continue
            if candidate.event.priority != event.priority:
                continue
            if now - candidate.added_at > self.aggregation_window_s:
                continue
            if candidate.event.sender_id and candidate.event.sender_id == event.sender_id:
                candidate.sources.append(event)
                return candidate
            other = normalize_text(candidate.event.text)
            if norm and other and (
                    norm == other or difflib.SequenceMatcher(None, norm, other).ratio()
                    >= self.similarity_ratio):
                candidate.sources.append(event)
                return candidate
        return None

    def _expire_locked(self, now: float) -> None:
        for candidate in self._pending:
            if candidate.state == "pending" and now - candidate.added_at > self.ttl_s:
                candidate.state = "expired"
                self.counters["expired"] += 1
        self._pending = [c for c in self._pending if c.state == "pending"]

    def pick(self) -> Optional[dict[str, Any]]:
        with self.lock:
            now = self._time()
            self._expire_locked(now)
            if self._pending:
                candidate = self._select_locked()
                return self._build_turn_locked(candidate, now)
            idle = None
            if self._last_event_at is not None:
                idle = now - self._last_event_at
            cold_ok = (idle is not None and idle >= self.cold_idle_s
                       and (self._last_cold_at is None
                            or now - self._last_cold_at >= self.cold_min_interval_s))
            if cold_ok:
                self._last_cold_at = now
                self.counters["cold"] += 1
                self._turn_seq += 1
                return {
                    "turn_id": f"cold-{self._turn_seq:06d}",
                    "kind": "cold",
                    "idle_s": round(idle, 2),
                    "sources": [],
                }
            return None

    def _select_locked(self) -> Candidate:
        order = {"owner": 0, "key": 1, "normal": 2}
        return min(self._pending, key=lambda c: (order.get(c.priority, 9), c.added_at))

    def _build_turn_locked(self, topic: Candidate, now: float) -> dict[str, Any]:
        topic.state = "selected"
        self._pending.remove(topic)
        sources = topic.all_sources()
        norm = normalize_text(topic.event.text)
        related: list[Candidate] = []
        for candidate in list(self._pending):
            if len(sources) + sum(len(c.all_sources()) for c in related) >= self.max_turn_sources:
                break
            same_sender = (candidate.event.sender_id
                           and candidate.event.sender_id == topic.event.sender_id)
            other = normalize_text(candidate.event.text)
            similar = bool(norm and other) and (
                norm == other or difflib.SequenceMatcher(None, norm, other).ratio()
                >= self.similarity_ratio)
            if same_sender or similar:
                candidate.state = "selected"
                related.append(candidate)
                self._pending.remove(candidate)
        for candidate in related:
            sources.extend(candidate.all_sources())
        sources = sources[:self.max_turn_sources]
        self._last_pick_at = now
        self._turn_seq += 1
        self.counters["selected"] += 1
        return {
            "turn_id": f"turn-{self._turn_seq:06d}",
            "kind": "reply",
            "priority": topic.priority,
            "topic_text": topic.event.text,
            "sources": [s.to_dict() for s in sources],
            "source_count": len(sources),
            "coalesced_count": max(0, len(topic.sources)),
            "age_s": round(now - topic.added_at, 2),
        }

    def summary(self) -> dict[str, Any]:
        with self.lock:
            return {
                "pending": len(self._pending),
                "capacity": self.capacity,
                "ttl_s": self.ttl_s,
                "counters": dict(sorted(self.counters.items())),
                "last_event_age_s": (round(self._time() - self._last_event_at, 2)
                                     if self._last_event_at is not None else None),
            }
