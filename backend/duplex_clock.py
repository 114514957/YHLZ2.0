"""Map each PortAudio stream clock to process monotonic time.

This is callback-clock estimation, not a claim of hardware clock sync. Missing
or discontinuous timestamps fail closed. Acoustic/device delay is separate.
No I/O, filtering, model work or locking is performed here.
"""
from collections import deque
import math


def clock_value(info, name):
    try:
        value = info.get(name) if isinstance(info, dict) else getattr(info, name)
        value = float(value)
        return value if math.isfinite(value) and value >= 0 else None
    except (AttributeError, TypeError, ValueError):
        return None


class CallbackClock:
    def __init__(self):
        self.epoch = 0
        self.reset()

    def reset(self):
        self.epoch += 1
        self._offsets = deque(maxlen=64)
        self._last = None
        self.invalid = 0
        self.jumps = 0

    def map(self, sample_time, current_time, observed_at):
        if (sample_time is None or current_time is None or
                not all(math.isfinite(v) for v in (sample_time, current_time, observed_at)) or
                abs(sample_time - current_time) > 5.0):
            self.invalid += 1
            return None
        if self._last is not None:
            prev_clock, prev_mono = self._last
            if (current_time < prev_clock or
                    abs((current_time - prev_clock) - (observed_at - prev_mono)) > .100):
                self._offsets.clear()
                self.epoch += 1
                self.jumps += 1
                self._last = (current_time, observed_at)
                self.invalid += 1
                return None
        self._last = (current_time, observed_at)
        self._offsets.append(observed_at - current_time)
        # Lower envelope limits callback scheduling-delay contamination.
        return sample_time + min(self._offsets)

    def snapshot(self):
        return {"epoch": self.epoch, "invalid": self.invalid, "jumps": self.jumps,
                "offset_spread_ms": ((max(self._offsets) - min(self._offsets)) * 1000
                                      if self._offsets else None),
                "basis": "callback_monotonic_estimate_not_hardware_sync"}
