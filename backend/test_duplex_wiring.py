"""Phase9.1 fake callbacks/runtime tests. Never open hardware or model weights."""
import asyncio
import time
import unittest
from dataclasses import replace
from unittest.mock import patch
import numpy as np
from backend.duplex_reference import PlaybackReferenceTimeline
from backend.duplex_ingress import DuplexIngress
from backend.media_adapter import AudioFrame, DeviceDescriptor, MediaAdapter
from backend.session_kernel import ProviderCapabilities
from backend.target_playback import PlaybackConfig, PlaybackReferenceFrame, SoundDevicePlaybackPort
from backend.target_composition import TargetVoiceComposition
from backend.target_device_binding import TargetDeviceBinding, resolve_devices, DeviceBindingError
from backend.test_target_playback import _FakeSoundDevice, _chunk, _lease, _Signal
from backend.test_target_composition import _config, _Reasoner, _Provider, _Source, _VAD, _ASR
from backend.test_target_device_binding import _make_sd


def reference(seq=0, start=10., rate=48000, value=0., **kw):
    return PlaybackReferenceFrame(np.full((rate//50,2),value,np.float32),rate,1,seq,
                                  played_at=start,clock_valid=True,clock_epoch=1,**kw)

class SpyAEC:
    def __init__(self): self.calls=[]; self.resets=0
    def reset(self): self.resets+=1
    def process(self,mic,ref,rate):
        self.calls.append((mic.copy(),ref.copy(),rate))
        return mic,0.

class TimelineTests(unittest.TestCase):
    def fill(self,t,count=10,rate=48000,value=.1):
        for i in range(count): t.push(reference(i,10.+i*.02,rate,value))
    def test_lookup_resamples_matches_length_and_rate(self):
        for rate in (16000,24000,44100,48000):
            t=PlaybackReferenceTimeline(); self.fill(t,rate=rate)
            r=t.lookup(10.05,320)
            self.assertTrue(r.available); self.assertEqual(r.samples.shape,(320,))
            np.testing.assert_allclose(r.samples,.1,atol=.002)
    def test_cancel_retains_already_played_tail(self):
        t=PlaybackReferenceTimeline(); self.fill(t)
        t.push(reference(10,10.2,is_final=True,reason="interrupted"))
        self.assertTrue(t.lookup(10.05,320).available)
        self.assertTrue(t.recent_playback(10.25))
        t.push(reference(11,10.2,value=0.))
        self.assertTrue(t.lookup(10.1,320).available)
    def test_sequence_gap_never_fabricates_zero_reference(self):
        t=PlaybackReferenceTimeline(); self.fill(t,count=3)
        t.push(reference(4,10.08))
        self.assertFalse(t.lookup(10.04,640).available)
        self.assertEqual(t.health()["gaps"],1)
    def test_bad_clock_and_status_clear_history(self):
        for change in ({"clock_valid":False},{"status":"underflow"},{"played_at":None}):
            t=PlaybackReferenceTimeline(); self.fill(t,count=3)
            t.push(replace(reference(3,10.06),**change))
            self.assertFalse(t.lookup(10.02,320).available)
    def test_clock_epoch_rate_and_large_jump_reset(self):
        for f in (replace(reference(3,10.06),clock_epoch=2),reference(3,11.),reference(3,10.06,44100)):
            t=PlaybackReferenceTimeline(); self.fill(t,count=3); before=t.health()["epoch"]
            t.push(f); self.assertGreater(t.health()["epoch"],before)
            self.assertFalse(t.lookup(10.02,320).available)
    def test_bounds_and_stale_queries(self):
        t=PlaybackReferenceTimeline(window_s=.1,max_blocks=8); self.fill(t,count=100)
        self.assertLessEqual(t.health()["blocks"],8)
        self.assertLess(t.health()["samples"],3000)
        self.assertFalse(t.lookup(10.01,320).available)
        self.assertFalse(t.lookup(20.,320).available)
        t.reset(); self.assertFalse(t.lookup(11.98,10).available)
    def test_small_drift_has_no_missing_blocks(self):
        t=PlaybackReferenceTimeline()
        for i in range(80): t.push(reference(i,10.+i*.020002,value=.2))
        self.assertEqual(t.health()["resets"],0)
        self.assertTrue(t.lookup(11.,320).available)
    def test_close_clears_and_restart_accepts_new_sequence(self):
        t=PlaybackReferenceTimeline(); self.fill(t)
        t.push(reference(10,10.2,is_final=True,reason="closed"))
        self.assertEqual(t.health()["blocks"],0)
        t.reset(); t.push(reference(80,30.)); self.assertEqual(t.health()["blocks"],1)
    def test_wait_is_bounded_off_callback(self):
        t=PlaybackReferenceTimeline(); began=time.perf_counter()
        self.assertFalse(t.lookup(10.,320,wait_s=.005).available)
        self.assertLess(time.perf_counter()-began,.1)

class IngressTests(unittest.TestCase):
    def setup_pipe(self):
        t=PlaybackReferenceTimeline(); a=SpyAEC(); p=DuplexIngress(t,a,reference_wait_s=0)
        TimelineTests().fill(t)
        return p,a
    def frame(self,**kw):
        args=dict(samples=np.zeros(960,np.float32),sample_rate=48000,sequence=1,
                  adc_at=10.08,clock_valid=True,clock_epoch=1)
        args.update(kw); return AudioFrame(**args)
    def test_resample_before_aec_and_exact_mic_length(self):
        p,a=self.setup_pipe(); mic,_,ok,_,_=p.process(self.frame())
        self.assertTrue(ok); self.assertEqual(mic.shape,(320,))
        self.assertEqual(a.calls[0][0].shape,a.calls[0][1].shape)
        self.assertEqual(a.calls[0][2],16000)
        self.assertFalse(p.health()["acoustic_verified"])
    def test_adc_delay_compensation_matches_dac_filter(self):
        for source in (44100,48000):
            p,a=self.setup_pipe(); p.timeline.reset()
            for i in range(20):
                x=np.sin(2*np.pi*150*(np.arange(960)/48000+i*.02)).astype(np.float32)
                p.timeline.push(replace(reference(i,10.+i*.02),samples=x))
            x=np.sin(2*np.pi*150*(np.arange(source//50)/source+.08)).astype(np.float32)
            p.process(self.frame(samples=x,sample_rate=source))
            mic,ref,_=a.calls[-1]
            self.assertGreater(np.corrcoef(mic[32:],ref[32:])[0,1],.999)
    def test_invalid_capture_preserves_samples_but_not_aec_claim(self):
        p,a=self.setup_pipe(); out=p.process(self.frame(clock_valid=False))
        self.assertEqual(len(out[0]),320); self.assertFalse(out[2]); self.assertEqual(a.calls,[])
    def test_input_drop_resets_filter_state(self):
        p,a=self.setup_pipe(); p.process(self.frame()); resets=a.resets
        p.process(self.frame(sequence=3,adc_at=10.12))
        self.assertGreater(a.resets,resets); self.assertEqual(p.health()["discontinuities"],1)
    def test_bad_aec_length_rejected_without_deleting_user_samples(self):
        p,a=self.setup_pipe(); a.process=lambda *args: (np.zeros(4),0.)
        out=p.process(self.frame()); self.assertEqual(len(out[0]),320)
        self.assertFalse(out[2]); self.assertEqual(p.health()["aec_errors"],1)
    def test_close_releases_audio_state_and_retains_diagnostics(self):
        p,a=self.setup_pipe(); p.process(self.frame()); p.close()
        self.assertIsNone(p._resampler)
        self.assertEqual(p.timeline.health()["blocks"],0)
        self.assertEqual(p.health()["reference_applied"],1)
        self.assertEqual(p.health()["last_reason"],"stopped")

    def test_headset_still_resamples_without_requiring_aec(self):
        p,a=self.setup_pipe(); out=p.process(self.frame(clock_valid=False),use_aec=False)
        self.assertEqual(len(out[0]),320); self.assertFalse(out[2]); self.assertEqual(a.calls,[])

class DeviceNegotiationTests(unittest.TestCase):
    def sd(self):
        return _make_sd(devices=[dict(name="mic",hostapi=0,max_input_channels=1,max_output_channels=0),
                                dict(name="BT",hostapi=0,max_input_channels=0,max_output_channels=1)])
    def test_bluetooth_mono_and_native_input_rate(self):
        sd=self.sd()
        def check_in(**k):
            if k["samplerate"]!=48000: raise ValueError()
        def check_out(**k):
            if (k["samplerate"],k["channels"])!=(16000,1): raise ValueError()
        sd.check_input_settings.side_effect=check_in; sd.check_output_settings.side_effect=check_out
        r=resolve_devices(sd,TargetDeviceBinding("mic","BT",route="headset"))
        self.assertEqual((r.input_sample_rate,r.output_sample_rate,r.output_channels),(48000,16000,1))
        self.assertEqual(r.descriptor().output_channels,1); self.assertFalse(r.descriptor().reference_available)
        self.assertTrue(all(c.kwargs["device"]==1 for c in sd.check_output_settings.call_args_list))
    def test_verify_rejects_format_change_on_same_endpoint(self):
        sd=self.sd(); b=TargetDeviceBinding("mic","BT"); r=resolve_devices(sd,b)
        sd.check_output_settings.side_effect=lambda **kw: None if kw["samplerate"]==48000 else (_ for _ in ()).throw(ValueError())
        with self.assertRaisesRegex(DeviceBindingError,"CHANGED"): r.verify(sd)

class RuntimeWiringTests(unittest.IsolatedAsyncioTestCase):
    async def make(self,rate=48000):
        sd=_FakeSoundDevice()
        playback=SoundDevicePlaybackPort(PlaybackConfig(device=0,device_sample_rate=rate,initial_buffer_ms=0),sounddevice_module=sd)
        c=TargetVoiceComposition(_config(),reasoner=_Reasoner(),provider_factory=lambda _: _Provider(),playback=playback)
        source=_Source(); a=SpyAEC()
        runtime=c.create_runtime(asr=_ASR(),source=source,vad=_VAD(),aec=a,duplex_enabled=True)
        c.start(DeviceDescriptor("1","fake",1,2,48000,"speaker_mic"),ProviderCapabilities(continuous_capture=True))
        self.addAsyncCleanup(c.shutdown)
        return c,playback,source,a
    async def feed(self,c,p,source,*,missing_clock=False):
        # Model distinct stream clock origins but a shared physical time.
        now=time.monotonic()
        for i in range(5):
            out=np.empty((p.config.block_frames,p.config.channels),np.float32)
            p._callback(out,len(out),{"currentTime":500.,"outputBufferDacTime":500.-.1+i*.02},None)
        self.assertTrue(p.wait_reference_idle())
        source.callback(np.zeros((960,1),np.float32),960,
                        {} if missing_clock else {"currentTime":900.,"inputBufferAdcTime":900.-.06},None)
        return await c.runtime.media.process_one()
    async def test_real_composition_callback_to_aec_and_health(self):
        c,p,src,a=await self.make(); result=await self.feed(c,p,src)
        self.assertIsNotNone(result); self.assertTrue(result.aec_applied)
        self.assertEqual(a.calls[-1][2],16000); self.assertEqual(len(result.samples),320)
        h=c.runtime.media.health(); self.assertTrue(h["device"]["reference_available"])
        self.assertFalse(c.runtime.media.capabilities.aec_verified); self.assertFalse(h["c_verified"])
    async def test_missing_adc_does_not_claim_reference_alignment(self):
        c,p,src,a=await self.make(); result=await self.feed(c,p,src,missing_clock=True)
        self.assertIsNotNone(result); self.assertFalse(result.aec_applied)
        self.assertEqual(a.calls,[])
    async def test_interrupt_and_next_turn_keep_actual_reference(self):
        c,p,src,a=await self.make(); p._enqueue(_chunk(),_lease(),_Signal())
        await self.feed(c,p,src)
        p.interrupt(); await self.feed(c,p,src)
        p._enqueue(_chunk(),_lease("next"),_Signal()); await self.feed(c,p,src)
        self.assertGreaterEqual(c.runtime.media.health()["duplex"]["reference_applied"],3)
        self.assertGreater(c.runtime.media.health()["duplex_safety_gated_frames"],0)
    async def test_close_worker_and_restart_no_history(self):
        c,p,src,a=await self.make(); await self.feed(c,p,src)
        await c.stop(); self.assertFalse(p.reference_health()["worker_alive"])
        self.assertEqual(c.runtime.media.duplex_pipeline.timeline.health()["blocks"],0)
        # SessionKernel is intentionally terminal after stop; a new runtime
        # owns a new clock/reference session rather than reviving the old one.
        c2,p2,src2,a2=await self.make()
        self.assertEqual(c2.runtime.media.duplex_pipeline.timeline.health()["blocks"],0)
        result=await self.feed(c2,p2,src2); self.assertTrue(result.aec_applied)
    async def test_resampler_tail_drains_in_actual_callback(self):
        sd=_FakeSoundDevice(); p=SoundDevicePlaybackPort(PlaybackConfig(device=0,device_sample_rate=44100,initial_buffer_ms=0),sounddevice_module=sd)
        p.start(); self.addCleanup(p.close); lease=_lease(); signal=_Signal()
        p._enqueue(_chunk(),lease,signal)
        task=asyncio.create_task(p.finish(lease,signal))
        for _ in range(50):
            await asyncio.sleep(.002)
            out=np.empty((882,2),np.float32); p._callback(out,882,None,None)
            if task.done(): break
        self.assertTrue(await asyncio.wait_for(task,1.))
        self.assertGreater(p._played_frames,882)
        p._enqueue(_chunk(),_lease("next"),_Signal()); p.interrupt()
        self.assertEqual(p._queued_frames,0)

class CallbackIsolationTests(unittest.TestCase):
    def test_slow_resample_does_not_lock_callback_and_cancel_drops_old_output(self):
        import threading
        from backend.target_playback import _StreamResampler
        entered=threading.Event(); release=threading.Event(); callback_done=threading.Event()
        real=_StreamResampler.process; result=[]
        def slow(obj,data):
            entered.set(); release.wait(2.); return real(obj,data)
        p=SoundDevicePlaybackPort(PlaybackConfig(device=0,device_sample_rate=48000,initial_buffer_ms=0),sounddevice_module=_FakeSoundDevice())
        p.start(); self.addCleanup(p.close)
        with patch.object(_StreamResampler,"process",slow):
            producer=threading.Thread(target=lambda: result.append(p._enqueue(_chunk(),_lease(),_Signal())))
            producer.start(); self.assertTrue(entered.wait(1.))
            def callback():
                p._callback(np.empty((960,2),np.float32),960,None,None); callback_done.set()
            consumer=threading.Thread(target=callback); consumer.start()
            try:
                self.assertTrue(callback_done.wait(.2),"FIR producer blocked audio callback")
                p.interrupt()
            finally:
                release.set(); producer.join(2.); consumer.join(2.)
            self.assertEqual(result,[False]); self.assertEqual(p._queued_frames,0)
    def test_reference_worker_exits_even_if_device_stop_fails(self):
        sd=_FakeSoundDevice(); frames=[]
        p=SoundDevicePlaybackPort(PlaybackConfig(device=0),sounddevice_module=sd,reference_tap=frames.append)
        p.start()
        with patch.object(sd.stream,"stop",side_effect=RuntimeError("fake stop failure")):
            with self.assertRaisesRegex(Exception,"CLOSE-FAILED"): p.close()
        self.assertFalse(p.reference_health()["worker_alive"])
        self.assertTrue(p.wait_reference_idle())
    def test_failed_output_start_closes_handle_and_reference_worker(self):
        sd=_FakeSoundDevice(); real=sd.OutputStream
        def stream(**kw):
            result=real(**kw)
            result.start=lambda: (_ for _ in ()).throw(RuntimeError("fake start failure"))
            return result
        sd.OutputStream=stream
        p=SoundDevicePlaybackPort(PlaybackConfig(device=0),sounddevice_module=sd,reference_tap=lambda _: None)
        with self.assertRaisesRegex(Exception,"START-FAILED"): p.start()
        self.assertFalse(p.reference_health()["worker_alive"])

class SafetyGateTests(unittest.IsolatedAsyncioTestCase):
    async def test_verified_aligned_frame_not_removed_by_legacy_rms_gate(self):
        class DenyLegacy:
            def allow(self,rms): return False
        a=SpyAEC(); t=PlaybackReferenceTimeline(); pipe=DuplexIngress(t,a,reference_wait_s=0)
        media=MediaAdapter(source=_Source(),vad=_VAD(),aec=a,duplex_pipeline=pipe,
                           target_sample_rate=16000,voice_gate=DenyLegacy())
        media.start(DeviceDescriptor("1","fake",1,2,48000,"speaker_mic"),
                    ProviderCapabilities(audio_route="speaker_mic",audio_route_verified=True,aec_verified=True))
        self.addCleanup(media.stop)
        TimelineTests().fill(t)
        media.ingest(np.zeros(960,np.float32),sample_rate=48000,adc_at=10.08,clock_valid=True)
        result=await media.process_one()
        self.assertIsNotNone(result); self.assertTrue(result.aec_applied)
    async def test_unverified_speaker_audio_is_visibly_gated_not_self_transcribed(self):
        a=SpyAEC(); t=PlaybackReferenceTimeline(); pipe=DuplexIngress(t,a,reference_wait_s=0)
        media=MediaAdapter(source=_Source(),vad=_VAD(),aec=a,duplex_pipeline=pipe,target_sample_rate=16000)
        media.start(DeviceDescriptor("1","fake",1,2,48000,"speaker_mic"),ProviderCapabilities())
        self.addCleanup(media.stop); TimelineTests().fill(t,value=.3)
        media.ingest(np.ones(960,np.float32),sample_rate=48000,adc_at=10.08,clock_valid=True)
        self.assertIsNone(await media.process_one())
        self.assertEqual(media.health()["duplex_safety_gated_frames"],1)
        self.assertEqual(media.health()["duplex"]["reference_applied"],1)
        self.assertFalse(media.capabilities.aec_verified)
