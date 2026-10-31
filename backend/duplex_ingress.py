"""Clocked 16 kHz microphone/reference/AEC pipeline, outside capture callbacks."""
import time
import threading
from collections import deque
import numpy as np
from backend.duplex_resampler import PolyphaseResampler

class DuplexIngress:
    sample_rate=16000
    def __init__(self, timeline, aec, *, reference_wait_s=.005):
        self.timeline=timeline; self.aec=aec; self.reference_wait_s=reference_wait_s
        self._lock=threading.RLock()
        self.reset()

    def reset(self):
        with self._lock:
            self._reset()

    def _reset(self):
        self._resampler=None; self._sequence=None; self._clock_epoch=None
        self._expected=None; self._reference_epoch=None; self._last_ready=False
        self._processing_ms=deque(maxlen=256)
        self._stats=dict(processed=0,reference_applied=0,missing=0,discontinuities=0,
                         aec_errors=0,aec_resets=0,last_reason="not_started",processing_ms=0.,max_processing_ms=0.)
        self.timeline.reset()
        reset=getattr(self.aec,"reset",None)
        if callable(reset): reset()

    def close(self):
        """Release transient audio/filter state while retaining diagnostics."""
        with self._lock:
            self._resampler=None; self._sequence=None; self._clock_epoch=None
            self._expected=None; self._reference_epoch=None; self._last_ready=False
            self.timeline.reset(); self._reset_aec()
            self._stats["last_reason"]="stopped"

    def _reset_aec(self):
        reset=getattr(self.aec,"reset",None)
        if callable(reset): reset()
        self._stats["aec_resets"]+=1

    def process(self, frame, *, use_aec=True):
        with self._lock:
            return self._process(frame, use_aec=use_aec)

    def _process(self, frame, *, use_aec=True):
        began=time.perf_counter()
        data=np.asarray(frame.samples,dtype=np.float32)
        if data.ndim==2 and data.shape[1]: data=data.mean(axis=1)
        if data.ndim!=1 or not np.isfinite(data).all(): raise ValueError("invalid microphone samples")
        valid=bool(frame.clock_valid and frame.adc_at is not None and not frame.capture_status)
        discontinuity=(self._sequence is not None and frame.sequence!=self._sequence+1)
        discontinuity|=(self._clock_epoch is not None and frame.clock_epoch!=self._clock_epoch)
        discontinuity|=(self._resampler is not None and frame.sample_rate!=self._resampler.source_rate)
        if valid and self._expected is not None: discontinuity|=abs(frame.adc_at-self._expected)>.005
        if discontinuity or not valid:
            self._resampler=None; self._expected=None; self._reset_aec()
            self._stats["discontinuities"]+=1
        self._sequence=frame.sequence; self._clock_epoch=frame.clock_epoch
        if self._resampler is None: self._resampler=PolyphaseResampler(frame.sample_rate,self.sample_rate)
        r=self._resampler
        start=(frame.adc_at+(r.output_samples*r.down/r.up-r.input_samples)/frame.sample_rate-r.delay_seconds) if valid else None
        mic=r.process(data)
        self._expected=frame.adc_at+len(data)/frame.sample_rate if valid else None
        match=self.timeline.lookup(start,len(mic),wait_s=self.reference_wait_s) if valid and use_aec else None
        ready=match is not None and match.available
        reason=match.reason if match is not None else ("headset_aec_not_required" if not use_aec else "invalid_input_clock_or_status")
        epoch=match.epoch if match is not None else None
        if epoch!=self._reference_epoch or ready!=self._last_ready: self._reset_aec()
        self._reference_epoch=epoch; self._last_ready=ready
        erl=None; applied=False
        if ready:
            try:
                result=self.aec.process(mic,match.samples,self.sample_rate)
                clean,erl=result if isinstance(result,tuple) else (result,None)
                clean=np.asarray(clean,dtype=np.float32)
                if clean.shape!=mic.shape or not np.isfinite(clean).all(): raise ValueError("AEC output contract")
                mic=clean; applied=True; self._stats["reference_applied"]+=1
            except Exception:
                self._stats["aec_errors"]+=1; reason="aec_failed"; self._reset_aec()
        elif use_aec: self._stats["missing"]+=1
        self._stats["processed"]+=1; self._stats["last_reason"]=reason
        elapsed=(time.perf_counter()-began)*1000
        self._processing_ms.append(elapsed)
        self._stats["processing_ms"]=elapsed
        self._stats["max_processing_ms"]=max(self._stats["max_processing_ms"],elapsed)
        return mic,start,applied,erl,reason

    def health(self):
        return dict(self._stats,processing_sample_rate=self.sample_rate,
                    processing_ms_p95_recent=float(np.percentile(list(self._processing_ms),95)) if self._processing_ms else None,
                    acoustic_verified=False,reference=self.timeline.health())
