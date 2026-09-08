"""Voice front-end (ledger 0218, 刀1): adaptive gain + noise-floor gate +
speech flag. Fixes the weak-mic failure mode documented in 0158/0159:
user speech RMS ~0.002 sits BELOW fixed gates (0.002-0.003), so raw audio was
swallowed as noise. Front-end normalises to a target level before VAD/ASR and
derives the speech decision RELATIVE to the running noise floor instead of an
absolute threshold.

Design:
- 100 ms frames at 16 kHz (1600 samples), matching existing capture.
- noise floor: fast-follow min with slow recovery (robust to non-stationary).
- AGC: gain -> target_rms / rms (clamped, smoothed); speech frames only.
- speech flag: rms > max(noise_floor * ratio, abs_min), with hangover so
  trailing low-energy syllables are not cut off.
"""

from __future__ import annotations

import numpy as np


class VoiceFrontend:
    def __init__(
        self,
        *,
        sample_rate: int = 16000,
        target_rms: float = 0.04,
        floor_ratio: float = 4.0,
        abs_min_rms: float = 0.001,
        max_gain: float = 40.0,
        hangover_frames: int = 4,   # 400 ms after last speech frame
        nf_recover: float = 0.002,  # noise floor slow-recovery coefficient
    ) -> None:
        self.sample_rate = int(sample_rate)
        self.target_rms = float(target_rms)
        self.floor_ratio = float(floor_ratio)
        self.abs_min_rms = float(abs_min_rms)
        self.max_gain = float(max_gain)
        self.hangover_frames = int(hangover_frames)
        self._nf_recover = float(nf_recover)
        self.reset()

    def reset(self) -> None:
        self._noise_floor: float = 0.0
        self._gain: float = 1.0
        self._hangover = 0
        self._seen = False

    @property
    def noise_floor(self) -> float:
        return self._noise_floor

    @property
    def gain(self) -> float:
        return self._gain

    def process(self, audio: np.ndarray) -> tuple[np.ndarray, bool]:
        """Return (enhanced_frame, is_speech). Enhanced frame is AGC'd to the
        target level and safe to feed VAD/ASR; noise-only frames stay near the
        floor (gate) so background doesn't inflate ASR."""
        x = np.asarray(audio, dtype="float32").reshape(-1)
        if x.size == 0:
            return x, False
        rms = float(np.sqrt(np.mean(np.square(x))) + 1e-9)

        # noise floor tracking: fast down, slow recovery
        if not self._seen:
            self._noise_floor = rms
            self._seen = True
        elif rms < self._noise_floor:
            self._noise_floor = rms
        else:
            self._noise_floor += (rms - self._noise_floor) * self._nf_recover

        threshold = max(self._noise_floor * self.floor_ratio, self.abs_min_rms)
        speech = rms > threshold

        # adaptive gain on speech frames, smoothed
        if speech:
            want = self.target_rms / max(rms, self._noise_floor)
            want = float(np.clip(want, 1.0, self.max_gain))
            self._gain += (want - self._gain) * 0.35
            self._hangover = self.hangover_frames
        else:
            if self._hangover > 0:
                self._hangover -= 1
            # slow decay back toward 1 during silence (avoids pumping)
            self._gain += (1.0 - self._gain) * 0.01
            self._gain = max(self._gain, 1.0)

        is_speech = speech or self._hangover > 0
        out = x * self._gain
        out = np.clip(out, -1.0, 1.0).astype("float32")
        return out, bool(is_speech)
