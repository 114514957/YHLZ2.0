"""Phase 3 fixed regressions (对话链路收口 · 阶段3 插话 + 第四批回归).

Batch regressions the plan calls for:
    * 20 轮文字回归           -> test_twenty_text_turns_one_audio_done_each
    * 10 次插话回归           -> test_ten_interjections_stop_playback_and_bump_generation
    * p50/p95 停止延迟         -> test_barge_in_stop_latency_reports_p50_p95

Plus unit coverage for the missing onset detector (``backend/barge_in.py``).
The runtime tests reuse the fake adapters from ``test_target_runtime``.
"""

from __future__ import annotations

import asyncio
import unittest

from backend.asr_bridge import ASRBridge
from backend.barge_in import BargeInConfig, BargeInDetector
from backend.media_adapter import DeviceDescriptor, MediaAdapter
from backend.session_kernel import AudioRoute
from backend.speech_segment import SpeechSegmentAssembler
from backend.target_chain import TargetVoiceChain
from backend.target_runtime import TargetVoiceRuntime
from backend.voice_trace import VoiceTrace, latency_report

from backend.test_target_runtime import (
    _caps,
    DuplexReasoner,
    DuplexSpeech,
    GatePlayback,
    ScriptedDuplexASR,
    Source,
    VAD,
)


class _Clock:
    def __init__(self, start: float = 1000.0) -> None:
        self.now = float(start)

    def __call__(self) -> float:
        return self.now

    def advance(self, ms: float) -> None:
        self.now += ms / 1000.0


class BargeInDetectorTests(unittest.TestCase):
    def test_short_burst_is_ignored(self) -> None:
        clock = _Clock()
        det = BargeInDetector(BargeInConfig(min_speech_ms=200, max_silence_gap_ms=120),
                              clock=clock)
        det.arm(clock.now)
        clock.advance(80)
        self.assertIsNone(det.poll())
        det.speech_end(clock.now)          # 80ms < 200ms -> noise
        self.assertFalse(det.armed)
        self.assertIsNone(det.poll())

    def test_sustained_speech_confirms_once(self) -> None:
        clock = _Clock()
        det = BargeInDetector(BargeInConfig(min_speech_ms=200), clock=clock)
        det.arm(clock.now)
        clock.advance(210)
        decision = det.poll()
        self.assertIsNotNone(decision)
        self.assertTrue(decision.confirmed)
        self.assertGreaterEqual(decision.speech_ms, 200)
        self.assertIsNone(det.poll())      # single-shot per arm

    def test_silence_gap_breaks_burst(self) -> None:
        clock = _Clock()
        det = BargeInDetector(BargeInConfig(min_speech_ms=200, max_silence_gap_ms=60),
                              clock=clock)
        det.arm(clock.now)
        clock.advance(50)
        self.assertIsNone(det.poll())
        det.speech_end(clock.now)          # 50ms burst -> noise, disarmed
        self.assertFalse(det.armed)
        clock.advance(500)
        self.assertIsNone(det.poll())

    def test_observe_requires_playing(self) -> None:
        clock = _Clock()
        det = BargeInDetector(BargeInConfig(min_speech_ms=100), clock=clock)
        for _ in range(5):
            self.assertIsNone(det.observe(True, playing=False, ts=clock.now))
            clock.advance(50)
        self.assertFalse(det.confirmed)
        self.assertFalse(det.armed)

    def test_observe_per_frame_confirms(self) -> None:
        clock = _Clock()
        det = BargeInDetector(BargeInConfig(min_speech_ms=100), clock=clock)
        decision = None
        for _ in range(12):
            decision = det.observe(True, playing=True, ts=clock.now)
            clock.advance(20)
            if decision:
                break
        self.assertIsNotNone(decision)
        self.assertTrue(decision.confirmed)

    def test_generation_change_resets(self) -> None:
        clock = _Clock()
        det = BargeInDetector(BargeInConfig(min_speech_ms=100), clock=clock)
        det.arm(clock.now, generation=1)
        clock.advance(150)
        self.assertTrue(det.poll().confirmed)
        det.arm(clock.now, generation=2)   # a new turn resets the latch
        self.assertTrue(det.armed)
        self.assertFalse(det.confirmed)
        self.assertEqual(det.generation, 2)


class _NonBlockingPlayback:
    """Plays immediately; used for the 20-round text regression."""

    def __init__(self) -> None:
        self.interrupts = 0
        self.played: list[str] = []

    async def play(self, chunk, lease, signal) -> None:
        self.played.append(lease.turn_id)

    def interrupt(self) -> None:
        self.interrupts += 1

    async def wait_stopped(self, timeout_s: float) -> bool:
        return True


def _build_runtime(vad_values, asr_values, *, playback, detector=None):
    chain = TargetVoiceChain(reasoner=DuplexReasoner(), speech=DuplexSpeech(),
                             playback=playback)
    media = MediaAdapter(source=Source(), vad=VAD(vad_values))
    bridge = ASRBridge(asr=ScriptedDuplexASR(asr_values), chain=chain,
                       assembler=SpeechSegmentAssembler(preroll_frames=0))
    runtime = TargetVoiceRuntime(media=media, asr=bridge, chain=chain,
                                 barge_in_detector=detector)
    return runtime, chain


_DEVICE = DeviceDescriptor("duplex", "fake headset", 1, 2,
                           route=AudioRoute.HEADSET.value)


class Phase3RegressionTests(unittest.TestCase):
    def test_ten_interjections_stop_playback_and_bump_generation(self) -> None:
        async def scenario() -> None:
            traces = []
            for _ in range(10):
                detector = BargeInDetector(
                    BargeInConfig(min_speech_ms=1.0, max_silence_gap_ms=500.0))
                playback = GatePlayback()
                runtime, chain = _build_runtime(
                    [True, False, True, False, True],   # wake, command, barge
                    ["元亨", "开始"], playback=playback, detector=detector)
                runtime.start(_DEVICE, _caps())
                worker = asyncio.create_task(runtime.run())
                trace = VoiceTrace(turn_id=1)
                for payload in (b"wake", b"wake-end", b"command", b"command-end"):
                    self.assertTrue(runtime.ingest(payload))
                await playback.started.wait()
                gen_before = chain.kernel.snapshot()["generation"]

                trace.mark("barge_in")             # user starts speaking
                self.assertTrue(runtime.ingest(b"barge"))   # sustained speech onset
                for _ in range(100):               # bounded wait for the onset stop
                    if playback.interrupts:
                        break
                    await asyncio.sleep(0.01)
                await asyncio.wait_for(runtime.wait_idle(), timeout=3)
                trace.mark("playback_stop")

                self.assertGreaterEqual(playback.interrupts, 1)
                self.assertGreater(
                    chain.kernel.snapshot()["generation"], gen_before)
                snapshot = runtime.barge_in_snapshot()
                self.assertTrue(snapshot["enabled"])
                self.assertIsNotNone(snapshot["last"])
                self.assertTrue(snapshot["last"]["confirmed"])

                traces.append(trace.to_dict())
                await runtime.stop()
                await asyncio.wait_for(worker, timeout=1.0)

            self.assertEqual(len(traces), 10)
            report = latency_report(traces)
            self.assertEqual(report["barge_in_stop"]["count"], 10)
            self.assertIn("p50_ms", report["barge_in_stop"])
            self.assertIn("p95_ms", report["barge_in_stop"])

        asyncio.run(scenario())

    def test_twenty_text_turns_one_audio_done_each(self) -> None:
        async def scenario() -> None:
            playback = _NonBlockingPlayback()
            vad = [True, False] * 21            # wake + 20 commands
            asr = ["元亨"] + [f"命令{i}" for i in range(20)]
            runtime, chain = _build_runtime(vad, asr, playback=playback)
            runtime.start(_DEVICE, _caps())
            worker = asyncio.create_task(runtime.run())

            self.assertTrue(runtime.ingest(b"wake"))
            self.assertTrue(runtime.ingest(b"wake-end"))
            for _ in range(20):
                self.assertTrue(runtime.ingest(b"command"))
                self.assertTrue(runtime.ingest(b"command-end"))
                await runtime.wait_idle()
            await runtime.wait_idle()

            events = chain.kernel.recent_events(limit=1000)
            starts = [e for e in events if e["kind"] == "AUDIO_START"]
            dones = [e for e in events if e["kind"] == "AUDIO_DONE"]
            self.assertEqual(len(starts), 20)
            self.assertEqual(len(dones), 20)
            # exactly one AUDIO_DONE per turn, no duplicates, no stale turn
            self.assertEqual(len({e["turn_id"] for e in dones}), 20)
            self.assertEqual([e["turn_id"] for e in dones],
                             [e["turn_id"] for e in starts])

            await runtime.stop()
            await asyncio.wait_for(worker, timeout=1.0)

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
