"""Playback-reference speech admission gate (borrowed from 对话DEMO VAD).

The legacy demo proved usable by masking speech detection while the assistant
speaks: a mic frame only counts when its RMS clearly exceeds the assistant's
current playback RMS (``ECHO_GAIN_RATIO = 1.6``).  This adapter exposes the
same rule as a callable gate that MediaAdapter consults before the VAD; when
no playback reference is attached the chain keeps its previous behaviour.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

ECHO_GAIN_RATIO = 1.6


class PlaybackReferenceVoiceGate:
    """Allow a frame only when its RMS exceeds the playback reference by a gain.

    ``playback_rms`` is a zero-arg callable returning the latest output RMS
    (typically ``SoundDevicePlaybackPort.playback_rms``).  A near-silent
    reference (0.0) makes the gate permissive so idle capture is unaffected.
    """

    def __init__(
        self,
        playback_rms: Callable[[], float],
        *,
        gain: float = ECHO_GAIN_RATIO,
    ) -> None:
        if not callable(playback_rms):
            raise TypeError("playback_rms must be callable")
        if float(gain) <= 0:
            raise ValueError("gain must be positive")
        self._playback_rms = playback_rms
        self.gain = float(gain)

    def allow(self, frame_rms: float) -> bool:
        reference = float(self._playback_rms() or 0.0)
        if reference <= 0.0:
            return True
        return float(frame_rms) >= reference * self.gain


def is_voice_gate(value: Any) -> bool:
    return callable(getattr(value, "allow", None))


def auto_voice_gate(playback: Any) -> Optional[PlaybackReferenceVoiceGate]:
    """Build the gate when the playback port exposes ``playback_rms``."""
    rms = getattr(playback, "playback_rms", None)
    if not callable(rms):
        return None
    return PlaybackReferenceVoiceGate(rms)
