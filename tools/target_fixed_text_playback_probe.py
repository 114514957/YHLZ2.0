"""Real chain/playback, synthetic TTS and soundcard: software evidence ONLY."""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import sys
import threading
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np
from backend.session_kernel import EventKind, ProviderCapabilities, SessionKernel
from backend.target_chain import AudioChunk, PipelineError, TargetVoiceChain
from backend.target_playback import PlaybackConfig, SoundDevicePlaybackPort
from backend.tts_provider_port import (
    PCMChunk, PCM_FRAME_SAMPLES, TTSEventKind, TTSProviderCapabilities, TTSProviderEvent,
)

FIXED_TRANSCRIPT = "元亨，能听到吗"
FIXED_REPLY = "进步始于思想，元亨开拓未来。"
FAULTS = ("missing-done", "no-pcm", "tts-stop-timeout", "playback-stop-timeout")


class Timeline:
    def __init__(self):
        self.events = []
        self.lock = threading.Lock()

    def mark(self, name, **fields):
        with self.lock:
            event = dict(name=name, perf_counter_s=time.perf_counter(), **fields)
            self.events.append(event)
        return event

    def find(self, name, turn_id=None):
        with self.lock:
            return [e for e in self.events if e["name"] == name
                    and (turn_id is None or e.get("turn_id") == turn_id)]


class ObservedKernel(SessionKernel):
    def __init__(self, timeline):
        super().__init__()
        self.timeline = timeline

    def record_system_event(self, kind, payload=None, **kwargs):
        event = super().record_system_event(kind, payload, **kwargs)
        if (payload or {}).get("event_kind") == "FIRST_CHUNK":
            self.timeline.mark("first_pcm", turn_id=kwargs.get("turn_id"),
                               generation=kwargs.get("generation"))
        return event

    def publish_output(self, lease, kind, payload=None):
        event = super().publish_output(lease, kind, payload)
        if event is not None:
            self.timeline.mark("kernel_output", kind=getattr(kind, "value", kind),
                               turn_id=lease.turn_id, generation=lease.generation)
        return event


class FixedReasoner:
    async def generate(self, text, signal):
        await asyncio.sleep(0.001)  # Simulation scheduling, NOT real model latency.
        if not signal.is_cancelled():
            yield FIXED_REPLY


class ProbeSession:
    def __init__(self, request, timeline, *, mode, amplitude, confirm_stop=True):
        self.request, self.timeline = request, timeline
        self.mode, self.amplitude, self.confirm_stop = mode, amplitude, confirm_stop
        self.text = []
        self.committed, self.stopped = asyncio.Event(), asyncio.Event()
        self.cancelled = False

    async def push_text(self, delta):
        self.text.append(delta)

    async def commit_text(self):
        self.committed.set()

    def event(self, kind, sequence=0):
        chunk = None
        if kind == TTSEventKind.PCM_CHUNK:
            data = np.full(PCM_FRAME_SAMPLES, self.amplitude, dtype="<i2").tobytes()
            chunk = PCMChunk(data, sequence)
        return TTSProviderEvent(kind, self.request.speech_id,
                                self.request.provider_epoch, sequence=sequence, chunk=chunk)

    async def audio_events(self):
        sequence = 0
        try:
            yield self.event(TTSEventKind.READY)
            await self.committed.wait()
            await asyncio.sleep(0.002)
            if self.mode != "no-pcm":
                for sequence in range(20 if self.mode == "hold" else 3):
                    yield self.event(TTSEventKind.PCM_CHUNK, sequence)
            if self.mode == "hold":
                await asyncio.Future()
            if self.mode != "missing-done":
                yield self.event(TTSEventKind.DONE)
        except asyncio.CancelledError:
            self.timeline.mark("late_provider_pcm_attempt", turn_id=self.request.turn_id)
            yield self.event(TTSEventKind.PCM_CHUNK, sequence + 1)
        finally:
            if not self.cancelled or self.confirm_stop:
                self.stopped.set()

    def cancel(self, reason="cancelled"):
        self.cancelled = True
        self.timeline.mark("tts_cancel", turn_id=self.request.turn_id)
        if self.confirm_stop:
            self.stopped.set()

    async def wait_stopped(self, timeout_s):
        try:
            await asyncio.wait_for(self.stopped.wait(), timeout=max(timeout_s, 0.0001))
        except asyncio.TimeoutError:
            return False
        self.timeline.mark("tts_stop_observed", turn_id=self.request.turn_id)
        return True

    def health(self):
        return {"state": "stopped" if self.stopped.is_set() else "ready"}

    def metrics(self):
        return {"text_deltas": len(self.text), "cancelled": self.cancelled}


class ProbeProvider:
    def __init__(self, timeline, fault=None):
        self.timeline, self.fault = timeline, fault
        self.mode = fault if fault in ("missing-done", "no-pcm") else "complete"
        self.sessions = []

    def describe_capabilities(self):
        return TTSProviderCapabilities(provider_id="synthetic-probe-only",
            true_audio_stream=True, text_stream=True, cancel_observable=True)

    def open(self, request):
        session = ProbeSession(request, self.timeline, mode=self.mode,
            amplitude=1024 * (len(self.sessions) + 1),
            confirm_stop=not (self.mode == "hold" and self.fault == "tts-stop-timeout"))
        self.sessions.append(session)
        return session

    def health(self):
        return {"state": "ready", "synthetic": True}

    def metrics(self):
        return {"sessions": len(self.sessions)}


class SimulatedOutputStream:
    def __init__(self, *, callback, channels, blocksize, **kwargs):
        self.callback, self.channels, self.blocksize = callback, channels, blocksize
        self.active = False

    def start(self):
        self.active = True

    def stop(self):
        self.active = False

    def close(self):
        self.active = False

    def pump(self):
        output = np.zeros((self.blocksize, self.channels), dtype=np.float32)
        self.callback(output, self.blocksize, {}, None)
        return sorted(int(n) for n in np.unique(np.rint(output * 32768)) if n)


class SimulatedSoundDevice:
    def OutputStream(self, **kwargs):
        self.stream = SimulatedOutputStream(**kwargs)
        return self.stream


class ObservedPlayback(SoundDevicePlaybackPort):
    def __init__(self, timeline, device):
        self.timeline, self.signals = timeline, {}
        super().__init__(PlaybackConfig(device="SIMULATED-NOT-HARDWARE", channels=1,
            initial_buffer_ms=20, max_queue_blocks=4, stop_timeout_s=0.5),
            sounddevice_module=device, on_event=self.observe_event)

    def observe_event(self, event):
        self.timeline.mark(event.kind.lower(), turn_id=event.payload.get("turn_id"),
                           adapter_generation=event.generation)

    async def play(self, chunk, lease, signal):
        self.signals[lease.turn_id] = signal
        accepted = await super().play(chunk, lease, signal)
        self.timeline.mark("enqueue" if accepted else "enqueue_rejected",
                           turn_id=lease.turn_id, generation=lease.generation)
        return accepted

    async def finish(self, lease, signal):
        self.timeline.mark("finish_requested", turn_id=lease.turn_id)
        result = await super().finish(lease, signal)
        if result:
            self.timeline.mark("drain_confirmed", turn_id=lease.turn_id)
        return result

    def interrupt(self, reason="interrupted"):
        result = super().interrupt(reason)
        self.timeline.mark("queue_cleared", queue_depth=self.health()["queue_depth"])
        return result

    async def wait_stopped(self, timeout_s):
        result = await super().wait_stopped(timeout_s)
        if result:
            self.timeline.mark("playback_stop_observed")
        return result


async def _until(predicate, timeout_s=2.0):
    deadline = time.perf_counter() + timeout_s
    while not predicate():
        if time.perf_counter() >= deadline:
            raise TimeoutError("probe evidence deadline exceeded")
        await asyncio.sleep(0.001)


def _delta(start, end):
    return None if start is None or end is None else (end - start) * 1000.0


async def run_probe(*, fault=None):
    if fault is not None and fault not in FAULTS:
        raise ValueError("unknown fault")
    timeline, device = Timeline(), SimulatedSoundDevice()
    playback, provider = ObservedPlayback(timeline, device), ProbeProvider(timeline, fault)
    chain = TargetVoiceChain(kernel=ObservedKernel(timeline), reasoner=FixedReasoner(),
                             tts_provider=provider, playback=playback)
    chain.start(ProviderCapabilities())  # No fake headset/AEC/full-duplex attestation.
    playback.start()
    pump_enabled = True
    report = {"probe": "target-fixed-text-playback", "schema_version": 1,
        "batch_id": "fixed_" + uuid.uuid4().hex, "fixed_transcript": FIXED_TRANSCRIPT,
        "fixed_reply": FIXED_REPLY, "fault_injected": fault,
        "scope": "real-chain-real-playback-adapter-synthetic-tts-simulated-callback",
        "acoustic_evidence": {"speaker_output_verified": False,
            "bluetooth_output_verified": False, "physical_stop_verified": False},
        "backend_evidence": {"real_audio_device_opened": False},
        "latency_scope": "software probe only; includes simulated scheduling delays",
        "turns": [], "errors": []}
    evidence = dict(wake_accepted=False, first_pcm_seen=False, audio_chunk_seen=False,
        playback_started=False, playback_done=False, turn_completed=False,
        tts_stop_observed=False, playback_stop_observed=False, queue_cleared=False,
        late_pcm_rejected=False, old_generation_audio=False, followup_completed=False,
        drain_before_audio_done=False, cancelled_turn_has_no_audio_done=False,
        silent_callback_after_barge_in=False, stale_kernel_output_rejected=False)

    async def pump():
        while device.stream.active:
            await asyncio.sleep(0.02)
            if pump_enabled and device.stream.active:
                timeline.mark("callback", sample_codes=device.stream.pump())

    pump_task = asyncio.create_task(pump())
    first_turn, barge_at = None, None
    submit_at = time.perf_counter()
    timeline.mark("submit", boundary_perf_counter_s=submit_at)

    def record_turn(submission, outcome, scenario):
        lease = submission.lease
        report["turns"].append(dict(scenario=scenario, session_id=lease.session_id,
            turn_id=lease.turn_id, trace_id=lease.trace_id, generation=lease.generation,
            status=outcome.status, error_code=outcome.error_code))

    try:
        submission = await chain.submit_transcript(FIXED_TRANSCRIPT, source="fixed-text-probe")
        evidence["wake_accepted"] = submission.task is not None
        if submission.task is None:
            raise RuntimeError("wake gate did not accept fixed transcript")
        first_turn = submission.lease.turn_id
        outcome = await asyncio.wait_for(submission.task, 3.0)
        record_turn(submission, outcome, "normal")
        evidence["turn_completed"] = outcome.status == "completed" and outcome.text == FIXED_REPLY
        if outcome.status != "completed":
            report["errors"].append(outcome.error_code or outcome.status)
        else:
            provider.mode = "hold"
            interrupted = await chain.submit_transcript("继续说", source="fixed-text-probe")
            old_id = interrupted.lease.turn_id
            await _until(lambda: timeline.find("playback_started", old_id))
            if fault == "playback-stop-timeout":
                pump_enabled = False
            barge_at = time.perf_counter()
            timeline.mark("barge_in", turn_id=old_id, boundary_perf_counter_s=barge_at)
            aborted = await chain.interrupt("probe_barge_in", timeout_s=0.15)
            cancelled_outcome = await asyncio.wait_for(interrupted.task, 1.0)
            record_turn(interrupted, cancelled_outcome, "barge-in")
            report["cancel_result"] = dict(timed_out_tasks=list(aborted.timed_out_tasks),
                                           failed_tasks=list(aborted.failed_tasks))
            evidence["tts_stop_observed"] = bool(timeline.find("tts_stop_observed", old_id))
            evidence["playback_stop_observed"] = bool(timeline.find("playback_stop_observed"))
            evidence["queue_cleared"] = playback.health()["queue_depth"] == 0
            old_pcm = AudioChunk(np.full(PCM_FRAME_SAMPLES, 2048, dtype="<i2").tobytes(),
                                  24000, 1, "pcm_s16le")
            old_signal = playback.signals[old_id]
            timeline.mark("late_playback_attempt", turn_id=old_id)
            rejected = not await playback.play(old_pcm, interrupted.lease, old_signal)
            if not aborted.timed_out_tasks and not aborted.failed_tasks:
                provider.mode = "complete"
                following = await chain.submit_transcript("再回答一次", source="fixed-text-probe")
                following_outcome = await asyncio.wait_for(following.task, 3.0)
                record_turn(following, following_outcome, "followup")
                evidence["followup_completed"] = following_outcome.status == "completed"
                timeline.mark("late_playback_attempt", turn_id=old_id)
                rejected = rejected and not await playback.play(old_pcm, interrupted.lease, old_signal)
            else:
                report["errors"].append("cancellation stop not confirmed")
                try:
                    await chain.submit_transcript("禁止绕过停止确认", source="fixed-text-probe")
                except PipelineError:
                    report["followup_blocked"] = True
                else:
                    report["followup_blocked"] = False
            evidence["late_pcm_rejected"] = rejected
            evidence["stale_kernel_output_rejected"] = chain.kernel.publish_output(
                interrupted.lease, EventKind.AUDIO_CHUNK, {"probe_stale_attempt": True}
            ) is None
            await asyncio.sleep(0.04)
            evidence["silent_callback_after_barge_in"] = any(
                e["perf_counter_s"] >= barge_at and e["name"] == "callback"
                and not e["sample_codes"] for e in timeline.events
            )
            evidence["old_generation_audio"] = any(
                e["perf_counter_s"] >= barge_at and (
                    (e["name"] == "callback" and 2048 in e["sample_codes"]) or
                    (e["name"] == "enqueue" and e.get("turn_id") == old_id)
                ) for e in timeline.events)
            evidence["cancelled_turn_has_no_audio_done"] = not any(
                e.get("kind") == "AUDIO_DONE" and e.get("turn_id") == old_id
                for e in timeline.find("kernel_output"))
    except Exception as exc:
        report["errors"].append(type(exc).__name__ + ": " + str(exc)[:200])
    finally:
        # Cleanup evidence must not make the tested interrupt pass.
        acceptance_events = list(timeline.events)
        pump_enabled = True
        try:
            await chain.interrupt("probe_cleanup", timeout_s=0.1)
        finally:
            playback.close()
            pump_task.cancel()
            await asyncio.gather(pump_task, return_exceptions=True)

    def first_time(name, turn_id=None, kind=None):
        return next((e["perf_counter_s"] for e in acceptance_events if e["name"] == name
                     and (turn_id is None or e.get("turn_id") == turn_id)
                     and (kind is None or e.get("kind") == kind)), None)

    first_pcm = first_time("first_pcm", first_turn)
    playback_start = first_time("playback_started", first_turn)
    drained = first_time("drain_confirmed", first_turn)
    audio_done = first_time("kernel_output", first_turn, "AUDIO_DONE")
    tts_stopped, playback_stopped = first_time("tts_stop_observed"), first_time("playback_stop_observed")
    stopped = max(tts_stopped, playback_stopped) if tts_stopped and playback_stopped else None
    evidence.update(first_pcm_seen=first_pcm is not None,
        audio_chunk_seen=first_time("kernel_output", first_turn, "AUDIO_CHUNK") is not None,
        playback_started=playback_start is not None, playback_done=drained is not None,
        drain_before_audio_done=drained is not None and audio_done is not None and drained <= audio_done)
    report["software_evidence"] = evidence
    report["latency_ms"] = dict(submit_to_first_pcm=_delta(submit_at, first_pcm),
        first_pcm_to_playback_start=_delta(first_pcm, playback_start),
        playback_start_to_done=_delta(playback_start, drained),
        barge_in_to_stop_observed=_delta(barge_at, stopped))
    report["timing_boundaries_perf_counter_s"] = dict(submit=submit_at, first_pcm=first_pcm,
        playback_start=playback_start, playback_done=drained, barge_in=barge_at, stop_observed=stopped)
    report["events"] = acceptance_events
    report["kernel_events"] = chain.kernel.recent_events()
    report["passed"] = (not report["errors"] and all(
        not value if key == "old_generation_audio" else value for key, value in evidence.items())
        and all(isinstance(v, (int, float)) and math.isfinite(v) and v >= 0
                for v in report["latency_ms"].values()))
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "cache/voice_metrics/target_fixed_text_playback.json")
    parser.add_argument("--fault", choices=FAULTS)
    args = parser.parse_args(argv)
    report = asyncio.run(run_probe(fault=args.fault))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "output": str(args.output.resolve()),
                      "latency_ms": report["latency_ms"], "errors": report["errors"]}, ensure_ascii=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
