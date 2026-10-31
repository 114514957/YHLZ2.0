"""Barge-in onset detector (对话链路收口 · 阶段3).

While the assistant is speaking, the user may start talking; the plan asks for
"连续有效语音 → 忽略极短噪声" — i.e. stop playback on *sustained* user speech,
not on the first VAD edge (a cough, a door, a lip smack must not cut her off).

This module turns speech-edge observations into **one confirmed onset decision
per turn/generation**.  It never touches audio or devices; it is pure timing
logic so both the live runtime and the fixed regressions can drive it.

Two usage styles are supported:

* edge + poll (the runtime): ``arm()`` on SPEECH_STARTED, ``poll()`` on a timer,
  ``speech_end()`` on SPEECH_ENDED;
* per-frame: ``observe(active, playing=..., ts=...)`` which composes the above.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

__all__ = ["BargeInConfig", "BargeInDecision", "BargeInDetector"]


@dataclass(frozen=True, slots=True)
class BargeInConfig:
    """Onset thresholds.  Durations are milliseconds."""

    min_speech_ms: float = 200.0      # sustained speech required to confirm
    max_silence_gap_ms: float = 120.0  # a gap longer than this breaks the burst

    def __post_init__(self) -> None:
        if self.min_speech_ms <= 0:
            raise ValueError("min_speech_ms must be positive")
        if self.max_silence_gap_ms < 0:
            raise ValueError("max_silence_gap_ms must not be negative")


@dataclass(frozen=True, slots=True)
class BargeInDecision:
    """A confirmed (or explicitly rejected) barge-in onset."""

    confirmed: bool
    speech_ms: float
    generation: Optional[int]
    reason: str

    def to_dict(self) -> dict:
        return {
            "confirmed": self.confirmed,
            "speech_ms": self.speech_ms,
            "generation": self.generation,
            "reason": self.reason,
        }


class BargeInDetector:
    """Sustained-speech onset detector; generation-aware; single-shot per arm."""

    def __init__(self, config: Optional[BargeInConfig] = None, *, clock=None) -> None:
        self.config = config or BargeInConfig()
        self._clock = clock or time.monotonic
        self._arm_started_at: Optional[float] = None
        self._silence_since: Optional[float] = None
        self._confirmed = False
        self._generation: Optional[int] = None

    # -- introspection -----------------------------------------------------
    @property
    def armed(self) -> bool:
        return self._arm_started_at is not None

    @property
    def confirmed(self) -> bool:
        return self._confirmed

    @property
    def generation(self) -> Optional[int]:
        return self._generation

    def held_ms(self, ts: Optional[float] = None) -> float:
        if self._arm_started_at is None:
            return 0.0
        now = self._clock() if ts is None else float(ts)
        return max(0.0, (now - self._arm_started_at) * 1000.0)

    def _disarm(self) -> None:
        self._arm_started_at = None
        self._silence_since = None
        self._confirmed = False

    # -- lifecycle ---------------------------------------------------------
    def reset(self, generation: Optional[int] = None) -> None:
        self._disarm()
        self._generation = generation

    def arm(self, ts: Optional[float] = None,
            generation: Optional[int] = None) -> None:
        """Speech observed (a VAD edge / frame).  Idempotent while armed."""
        now = self._clock() if ts is None else float(ts)
        if generation is not None and generation != self._generation:
            self.reset(generation)
        if not self._confirmed and self._arm_started_at is None:
            self._arm_started_at = now
        self._silence_since = None

    def speech_end(self, ts: Optional[float] = None) -> None:
        """Explicit end edge: a burst shorter than ``min_speech_ms`` is noise."""
        if self._arm_started_at is None:
            return
        now = self._clock() if ts is None else float(ts)
        if self.held_ms(now) < self.config.min_speech_ms:
            self._disarm()

    def poll(self, ts: Optional[float] = None) -> Optional[BargeInDecision]:
        """Confirm once the armed burst has held long enough (single-shot)."""
        if self._arm_started_at is None or self._confirmed:
            return None
        now = self._clock() if ts is None else float(ts)
        held = self.held_ms(now)
        if held >= self.config.min_speech_ms:
            self._confirmed = True
            return BargeInDecision(
                confirmed=True, speech_ms=round(held, 1),
                generation=self._generation, reason="sustained_speech")
        return None

    def observe(self, speech: bool, *, playing: bool,
                ts: Optional[float] = None,
                generation: Optional[int] = None) -> Optional[BargeInDecision]:
        """Per-frame convenience.

        ``speech=True`` (re)arms.  ``speech=False`` only disarms once the silence
        has persisted longer than ``max_silence_gap_ms`` — so a single silent
        frame inside an utterance does not reset the burst.
        """
        now = self._clock() if ts is None else float(ts)
        if generation is not None and generation != self._generation:
            self.reset(generation)
        if not playing:
            self.reset(self._generation)
            return None
        if speech:
            self.arm(now)
        else:
            if self._silence_since is None:
                self._silence_since = now
            if (now - self._silence_since) * 1000.0 > self.config.max_silence_gap_ms:
                self._disarm()
        return self.poll(now)
