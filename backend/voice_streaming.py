"""Bounded speech-content filtering and timed text segmentation (no model/device)."""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True, slots=True)
class TextChunkerConfig:
    first_min_chars: int = 8
    first_target_chars: int = 14
    first_max_chars: int = 20
    normal_min_chars: int = 15
    normal_max_chars: int = 45
    no_punctuation_flush_ms: int = 350
    hard_flush_ms: int = 600
    hard_max_chars: int = 60

    def __post_init__(self):
        if not (0 < self.first_min_chars <= self.first_target_chars <= self.first_max_chars
                <= self.hard_max_chars):
            raise ValueError("invalid first-segment limits")
        if not (0 < self.normal_min_chars <= self.normal_max_chars <= self.hard_max_chars):
            raise ValueError("invalid normal-segment limits")
        if not (0 < self.no_punctuation_flush_ms <= self.hard_flush_ms):
            raise ValueError("invalid flush deadlines")


class SpokenDeltaFilter:
    """Best-effort lexical guard, NOT a substitute for structured tool isolation.

    Only a suffix that is actually a marker prefix is held. Once a suspicious
    marker occurs, the rest of this stream is suppressed (bounded memory).
    A new final-answer round must use a new filter; do not resume after a tag.
    """

    _MARKERS = (
        "（思考模式", "(思考模式", "思考模式启动", "分析用户意图",
        "**分析", "**思考", "思考过程", "**回应策略", "**结论",
        "<analysis>", "<think>", "<tool_calls>", "<tool_call", "<|tool_call",
        "[[tool_code", "[[dev:", "<|channel>analysis", "<|channel>commentary",
    )

    def __init__(self, emit: Callable[[str], None]):
        self.emit = emit
        self._buffer = ""
        self._blocked = False
        self._closed = False

    def push(self, delta: str):
        if self._closed or self._blocked:
            return
        self._buffer += str(delta or "")
        lower = self._buffer.lower()
        cut = min((lower.find(m.lower()) for m in self._MARKERS
                   if m.lower() in lower), default=-1)
        if cut >= 0:
            safe = self._buffer[:cut]
            self._buffer = ""
            self._blocked = True
            if safe:
                self.emit(safe)
            return
        keep = max((n for m in self._MARKERS for n in range(1, len(m))
                    if lower.endswith(m[:n].lower())), default=0)
        safe = self._buffer[:-keep] if keep else self._buffer
        self._buffer = self._buffer[-keep:] if keep else ""
        if safe:
            self.emit(safe)

    def finish(self):
        # An incomplete marker prefix is ambiguous: fail closed at EOF.
        self._buffer = ""
        self._closed = True

    def cancel(self):
        self._buffer = ""
        self._blocked = self._closed = True


class StreamingTextChunker:
    """Synchronous state machine; owner MUST call tick() during delta silence.

    Idle deadline requires the segment minimum. Hard age flushes even a short
    fragment, including the first segment, so slow output cannot starve forever.
    finish/cancel are terminal; one instance belongs to exactly one turn.
    """

    _PUNCT = "。！？!?；;，,、…\n"

    def __init__(self, config: TextChunkerConfig | None = None,
                 clock: Callable[[], float] = time.monotonic):
        self.config = config or TextChunkerConfig()
        self._clock = clock
        self._text = ""
        self._started = self._last_delta = 0.0
        self._segments_emitted = 0
        self._closed = False

    @property
    def buffered(self):
        return self._text

    def push(self, delta: str) -> list[str]:
        if self._closed:
            return []
        now = self._clock()
        out = self._flush_ready(now)
        value = re.sub(r"\s+", " ", str(delta or ""))
        if value:
            if not self._text:
                self._started = now
            self._last_delta = now
            self._text += value
            out.extend(self._flush_ready(now))
        return out

    def tick(self) -> list[str]:
        return [] if self._closed else self._flush_ready(self._clock())

    def finish(self) -> list[str]:
        if self._closed:
            return []
        out = self._flush_ready(self._clock(), final=True)
        self._closed = True
        return out

    def cancel(self):
        self._closed = True
        self._text = ""

    def _flush_ready(self, now: float, *, final: bool = False) -> list[str]:
        out = []
        while self._text:
            first = self._segments_emitted == 0
            minimum = self.config.first_min_chars if first else self.config.normal_min_chars
            target = self.config.first_target_chars if first else self.config.normal_max_chars
            maximum = self.config.first_max_chars if first else self.config.normal_max_chars
            maximum = min(maximum, self.config.hard_max_chars)
            cuts = [i + 1 for i, ch in enumerate(self._text[:maximum])
                    if ch in self._PUNCT and i + 1 >= minimum]
            # First segment prefers an early natural clause, not arbitrary tokens.
            cut = next((n for n in cuts if n >= target), cuts[-1] if cuts else 0)
            if not cut:
                if len(self._text) >= maximum:
                    cut = maximum
                elif final or (now - self._started) * 1000 >= self.config.hard_flush_ms - 1e-6:
                    cut = min(len(self._text), target)
                elif (len(self._text) >= minimum and
                      (now - self._last_delta) * 1000 >= self.config.no_punctuation_flush_ms - 1e-6):
                    cut = min(len(self._text), target)
                else:
                    break
            part = self._text[:cut].strip()
            self._text = self._text[cut:].lstrip()
            if part:
                out.append(part)
                self._segments_emitted += 1
            if self._text:
                self._started = now
        return out


__all__ = ["SpokenDeltaFilter", "StreamingTextChunker", "TextChunkerConfig"]
