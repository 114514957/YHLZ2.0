"""Bounded DAC timeline queried in the same estimated monotonic domain as ADC.

No sound device/model access. Ingest runs on playback's reference dispatcher;
lookups run on the media processing worker, never a PortAudio callback.
This is software alignment, NOT evidence of acoustic/hardware synchronization.
"""
from collections import deque
from dataclasses import dataclass
import threading
import time
import numpy as np
from backend.duplex_resampler import PolyphaseResampler

@dataclass(frozen=True)
class ReferenceMatch:
    samples: object = None
    reason: str = "missing"
    epoch: int = 0
    @property
    def available(self):
        return self.samples is not None

class PlaybackReferenceTimeline:
    def __init__(self, sample_rate=16000, window_s=2., max_blocks=512):
        if sample_rate != 16000 or not 0.1 <= window_s <= 10 or not 2 <= max_blocks <= 4096:
            raise ValueError("invalid reference timeline bounds")
        self.sample_rate=sample_rate; self.window_s=window_s; self.max_blocks=max_blocks
        self._cv=threading.Condition(threading.RLock())
        self._segments=deque(); self._resampler=None; self._sequence=None
        self._clock_epoch=None; self._expected=None; self._end=None
        self._epoch=0; self._last_reason="not_started"; self._last_signal_end=None
        self._stats=dict(received=0, invalid=0, gaps=0, resets=0, matched=0, missing=0, boundaries=0, timing_adjust_ms=0.)

    def _clear(self, reason):
        self._segments.clear(); self._resampler=None; self._expected=None; self._end=None
        self._epoch+=1; self._last_reason=reason; self._stats["resets"]+=1

    def reset(self):
        with self._cv:
            self._last_signal_end=None
            self._clear("reset"); self._sequence=None; self._clock_epoch=None; self._cv.notify_all()

    def push(self, frame):
        with self._cv:
            if self._sequence is not None and frame.sequence != self._sequence+1:
                self._stats["gaps"]+=1; self._clear("sequence_gap")
            self._sequence=frame.sequence
            if frame.is_final:
                self._stats["boundaries"]+=1
                # A cancellation cannot unplay sound already in the room.
                if frame.reason == "closed": self._clear("closed")
                self._cv.notify_all(); return
            self._stats["received"]+=1
            if (not frame.clock_valid or frame.played_at is None or not np.isfinite(frame.played_at)
                    or frame.status):
                self._stats["invalid"]+=1; self._clear("invalid_output_clock_or_status")
                self._cv.notify_all(); return
            if self._clock_epoch is not None and frame.clock_epoch != self._clock_epoch:
                self._clear("output_clock_epoch")
            self._clock_epoch=frame.clock_epoch
            data=np.asarray(frame.samples,dtype=np.float32)
            if data.ndim==2 and data.shape[1]: data=data.mean(axis=1)
            if data.ndim!=1 or not np.isfinite(data).all() or not len(data):
                self._stats["invalid"]+=1; self._clear("invalid_output_samples"); return
            if np.any(np.abs(data)>1e-6): self._last_signal_end=frame.played_at+len(data)/frame.sample_rate
            if self._resampler is not None and self._resampler.source_rate!=frame.sample_rate:
                self._clear("output_rate_changed")
            if self._expected is not None and abs(frame.played_at-self._expected)>.005:
                self._clear("output_time_discontinuity")
            if self._resampler is None: self._resampler=PolyphaseResampler(frame.sample_rate,self.sample_rate)
            r=self._resampler
            start=frame.played_at+(r.output_samples*r.down/r.up-r.input_samples)/frame.sample_rate-r.delay_seconds
            audio=r.process(data)
            self._expected=frame.played_at+len(data)/frame.sample_rate
            if not len(audio): return
            end=start+len(audio)/self.sample_rate
            if self._end is not None:
                # Small estimated-clock drift/jitter is distributed over this
                # block; never interpolate across missing callbacks/large jumps.
                self._stats["timing_adjust_ms"]=(start-self._end)*1000
                start=self._end
            if end<=start:
                self._clear("non_monotonic_output"); return
            times=np.linspace(start,end,len(audio),endpoint=False)
            self._segments.append((times,audio)); self._end=end; self._last_reason="ready"
            while len(self._segments)>self.max_blocks or (self._segments and self._segments[0][0][-1]<end-self.window_s):
                self._segments.popleft()
            self._cv.notify_all()

    def lookup(self, start, count, *, wait_s=0.):
        if count<=0 or count>self.sample_rate*2 or start is None or not np.isfinite(start):
            return ReferenceMatch(reason="invalid_input_time_or_length",epoch=self._epoch)
        deadline=time.monotonic()+max(0.,min(.02,wait_s))
        with self._cv:
            while True:
                if self._segments:
                    first=self._segments[0][0][0]; last=self._segments[-1][0][-1]
                    end=start+(count-1)/self.sample_rate
                    if start>=first-1e-7 and end<=last+1e-7:
                        times=np.concatenate([s[0] for s in self._segments])
                        audio=np.concatenate([s[1] for s in self._segments])
                        out=np.interp(start+np.arange(count)/self.sample_rate,times,audio).astype(np.float32)
                        self._stats["matched"]+=1
                        return ReferenceMatch(out,"aligned",self._epoch)
                    reason="stale_or_warmup" if start<first else "reference_not_yet_available"
                else: reason=self._last_reason
                remaining=deadline-time.monotonic()
                if remaining<=0 or reason=="stale_or_warmup":
                    self._stats["missing"]+=1
                    return ReferenceMatch(reason=reason,epoch=self._epoch)
                self._cv.wait(remaining)

    def recent_playback(self, adc_at, tail_s=.3):
        with self._cv:
            if self._last_signal_end is None: return False
            now=time.monotonic() if adc_at is None else adc_at
            return now <= self._last_signal_end+tail_s

    def health(self):
        with self._cv:
            return dict(self._stats,epoch=self._epoch,blocks=len(self._segments),window_s=self.window_s,
                        samples=sum(len(s[1]) for s in self._segments),last_reason=self._last_reason,
                        sample_rate=self.sample_rate,alignment_basis="callback_monotonic_estimate_not_hardware_sync",
                        acoustic_verified=False)
