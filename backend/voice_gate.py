"""Deterministic idle activation gate for the target microphone chain."""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional


WAKE_WORD = "元亨"


class GateState(str, Enum):
    IDLE = "idle"
    ACTIVE = "active"


class GateEvent(str, Enum):
    IGNORED = "ignored"
    ACTIVATED = "activated"
    INPUT_ACCEPTED = "input_accepted"
    SLEEP = "sleep"


@dataclass(frozen=True)
class GateDecision:
    event: GateEvent
    state: GateState
    text: str = ""
    wake_word: str = WAKE_WORD
    timestamp: float = 0.0


def _normalize(text: str) -> str:
    # Keep Chinese characters intact while ignoring spacing/punctuation variants.
    return re.sub(r"[\s\u3000,，。.!！?？:：;；、\-]+", "", str(text or "")).strip()


# Near-homophone characters for "亨(hēng)" that far-field ASR commonly emits
# (元亨 -> 元衡/元恒/元横/元哼...).
_NEAR_HENG = frozenset("亨衡恒横哼哄宏鸿虹弘弘弘")


def _near_wake(normalized: str) -> bool:
    """Tolerant wake-word matcher (far-field ASR variants, ledger 0132)."""
    if WAKE_WORD in normalized:
        return True
    pos = normalized.find(WAKE_WORD[0])
    if pos < 0:
        return False
    if normalized[pos + 1 : pos + 2] in _NEAR_HENG:
        return True
    tail = normalized[pos + 1 : pos + 1 + 4]
    return WAKE_WORD[1] in tail


class WakeWordGate:
    """Only the idle state consumes the single wake word.

    The gate is deliberately transcript-agnostic: a real wake-word detector or
    ASR adapter can call ``observe`` after VAD has produced a final candidate.
    Once active, subsequent VAD-final candidates are accepted without requiring
    the wake word again.  ``sleep`` is the only path back to idle.
    """

    def __init__(self, wake_word: str = WAKE_WORD) -> None:
        normalized = _normalize(wake_word)
        if normalized != WAKE_WORD:
            raise ValueError("the production wake word is fixed to 元亨")
        self._state = GateState.IDLE
        self._lock = threading.RLock()
        self._activated_at: Optional[float] = None

    @property
    def state(self) -> GateState:
        with self._lock:
            return self._state

    def observe(self, transcript: str, *, timestamp: Optional[float] = None) -> GateDecision:
        now = time.time() if timestamp is None else float(timestamp)
        raw = str(transcript or "").strip()
        normalized = _normalize(raw)
        with self._lock:
            if self._state == GateState.IDLE:
                if not _near_wake(normalized):
                    return GateDecision(GateEvent.IGNORED, self._state, timestamp=now)
                self._state = GateState.ACTIVE
                self._activated_at = now
                # Do not leak the wake word into the first user turn.  Any
                # trailing words are a candidate utterance after activation.
                remainder = normalized.replace(WAKE_WORD, "", 1).strip()
                if remainder:
                    return GateDecision(GateEvent.INPUT_ACCEPTED, self._state, remainder, timestamp=now)
                return GateDecision(GateEvent.ACTIVATED, self._state, timestamp=now)

            if not normalized:
                return GateDecision(GateEvent.IGNORED, self._state, timestamp=now)
            return GateDecision(GateEvent.INPUT_ACCEPTED, self._state, raw, timestamp=now)

    def sleep(self, *, timestamp: Optional[float] = None) -> GateDecision:
        now = time.time() if timestamp is None else float(timestamp)
        with self._lock:
            self._state = GateState.IDLE
            self._activated_at = None
            return GateDecision(GateEvent.SLEEP, self._state, timestamp=now)

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "state": self._state.value,
                "wake_word": WAKE_WORD,
                "activated_at": self._activated_at,
            }


__all__ = ["GateDecision", "GateEvent", "GateState", "WAKE_WORD", "WakeWordGate"]
