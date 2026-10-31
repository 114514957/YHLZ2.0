"""Stateful, causal polyphase FIR resampling with an exact global phase.

No chunk is replayed. The bounded input history is filter state, not output.
The known group delay is exposed for ADC/DAC alignment. Runs off callbacks.
"""
from math import gcd
import numpy as np
from scipy.signal import firwin


class PolyphaseResampler:
    def __init__(self, source_rate, target_rate):
        self.source_rate, self.target_rate = int(source_rate), int(target_rate)
        if self.source_rate <= 0 or self.target_rate <= 0:
            raise ValueError("sample rates must be positive")
        g = gcd(self.source_rate, self.target_rate)
        self.up, self.down = self.target_rate // g, self.source_rate // g
        size = max(self.up, self.down)
        if size > 1024:
            raise ValueError("unsupported resampling ratio")
        self._h = (np.ones(1) if size == 1 else
                   firwin(20 * size + 1, 1.0 / size, window=("kaiser", 5.0)) * self.up)
        self._lags = np.arange((len(self._h) + self.up - 1) // self.up)
        self.delay_seconds = (len(self._h) - 1) / (2 * self.up * self.source_rate)
        self.reset()

    def reset(self):
        self.input_samples = self.output_samples = 0
        self._carry = np.zeros(0, dtype=np.float32)
        self._finished = False

    def _render(self, end, data, base):
        # Vectorised polyphase evaluation: O(output samples * taps per phase),
        # not an upsampled array and never a per-sample Python audio callback.
        k = np.arange(self.output_samples, end, dtype=np.int64)[:, None]
        high = k * self.down
        hidx = high % self.up + self._lags[None, :] * self.up
        xidx = high // self.up - self._lags[None, :] - base
        valid = (hidx < len(self._h)) & (xidx >= 0) & (xidx < len(data))
        if not len(data):
            return np.zeros(len(k), np.float32)
        weights = self._h[np.minimum(hidx, len(self._h) - 1)]
        values = data[np.clip(xidx, 0, len(data) - 1)]
        return np.sum(np.where(valid, weights * values, 0.), axis=1).astype(np.float32)

    def process(self, audio):
        if self._finished:
            raise ValueError("resampler is flushed; reset before next stream")
        data = np.asarray(audio, dtype=np.float32)
        if data.ndim == 2 and data.shape[1] > 0:
            data = data.mean(axis=1)
        if data.ndim != 1 or not np.isfinite(data).all():
            raise ValueError("expected finite mono or frames-by-channels audio")
        if len(data) > self.source_rate * 2:
            raise ValueError("resampler block exceeds two seconds")
        if not len(data):
            return np.zeros(0, np.float32)
        base = self.input_samples - len(self._carry)
        data = np.concatenate((self._carry, data))
        self.input_samples = base + len(data)
        end = (self.input_samples * self.up + self.down - 1) // self.down
        result = self._render(end, data, base)
        self.output_samples = end
        history = len(self._lags)
        self._carry = data[-history:].copy()
        return result

    def flush(self):
        if self._finished or not self.input_samples:
            return np.zeros(0, np.float32)
        end = ((self.input_samples - 1) * self.up + len(self._h) + self.down - 1) // self.down
        result = self._render(end, self._carry, self.input_samples - len(self._carry))
        self.output_samples = end
        self._carry = np.zeros(0, np.float32)
        self._finished = True
        return result


class StreamingAudioResampler:
    """MediaAdapter interface; a rate change requires an explicit reset."""
    def __init__(self):
        self._stream = None

    @property
    def delay_seconds(self):
        return self._stream.delay_seconds if self._stream is not None else 0.

    def process(self, audio, source_rate, target_rate):
        if self._stream is None:
            self._stream = PolyphaseResampler(source_rate, target_rate)
        elif (self._stream.source_rate, self._stream.target_rate) != (source_rate, target_rate):
            raise ValueError("resampler rate changed without reset")
        return self._stream.process(audio)

    def reset(self):
        self._stream = None
