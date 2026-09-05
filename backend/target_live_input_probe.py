"""Live microphone VAD-to-streaming-ASR chain probe.

Opens a bounded real input device, runs the target input chain
(SoundDeviceInputSource -> MediaAdapter -> Silero VAD -> StreamingASRBridge
(sherpa-onnx) -> TargetVoiceChain with the "元亨" wake gate) for a single
bounded window, then records de-identified evidence.

Never writes PCM/WAV/transcripts or touches business data / memory. The
summary only keeps counts, error codes, final text length + SHA-256, and
wake-gate verdicts.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Sequence

import numpy as np

from backend.media_adapter import (
    AudioRoute,
    DeviceDescriptor,
    MediaAdapter,
    ProcessedAudioFrame,
    SoundDeviceInputSource,
)
from backend.session_kernel import ProviderCapabilities
from backend.streaming_asr_bridge import StreamingASRBridge
from backend.target_chain import TargetVoiceChain
from backend.voice_gate import WAKE_WORD
from backend.target_sherpa_asr import SherpaOnlineASRProvider
from backend.target_vad import TargetVADProvider
from backend.target_input_resampler import TargetInputResampler


_PROJECT_ROOT = Path(__file__).resolve().parent.parent


class _LiveNoopReasoner:
    """No-op reasoner: proves turn gating without generating output."""

    async def generate(self, _text: str, _signal: Any):
        if False:
            yield ""


def _default_output_dir() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return _PROJECT_ROOT / "artifacts" / "live_input_probe" / ("live_" + stamp)


def _speech_capabilities() -> ProviderCapabilities:
    return ProviderCapabilities(continuous_capture=True)


async def run_probe(
    output_dir: Path,
    *,
    device_id: int = 1,
    duration_s: float = 15.0,
    capture_sample_rate: int = 16_000,
    target_sample_rate: int = 16_000,
    chunks_per_second: int = 10,
) -> dict:
    """Run bounded live input through the target VAD/ASR chain."""
    if int(capture_sample_rate) <= 0 or int(target_sample_rate) != 16_000:
        raise ValueError("capture must be positive and target must stay 16000")
    if int(duration_s) <= 0 or float(duration_s) > 30.0:
        raise ValueError("duration_s must be within (0, 30]")
    output_dir.mkdir(parents=True, exist_ok=False)

    import sounddevice as sd

    summary: dict[str, Any] = {
        "probe": "target_live_input_chain_v1",
        "status": "failed",
        "device_opened": False,
        "audio_persisted": False,
        "transcript_persisted": False,
        "memory_written": False,
        "wake_word_verified": False,
        "turn_validated": False,
        "duration_budget_s": float(duration_s),
        "capture_sample_rate": int(capture_sample_rate),
        "processing_sample_rate": int(target_sample_rate),
    }

    vad = TargetVADProvider()
    asr = SherpaOnlineASRProvider()
    events: list[Any] = []
    chain = TargetVoiceChain(reasoner=_LiveNoopReasoner())
    bridge = StreamingASRBridge(asr=asr, chain=chain, on_event=events.append)
    adapter: Optional[MediaAdapter] = None
    worker: Optional[asyncio.Task] = None
    started = time.perf_counter()
    try:
        descriptor = sd.query_devices(device_id)
        sd.check_input_settings(
            device=device_id,
            samplerate=int(capture_sample_rate),
            channels=1,
            dtype="float32",
        )
        device = DeviceDescriptor(
            device_id=str(device_id),
            name=str(descriptor.get("name", "unknown"))[:160],
            input_channels=1,
            output_channels=0,
            sample_rate=int(capture_sample_rate),
            route=AudioRoute.UNKNOWN.value,
        )
        resampler = (
            TargetInputResampler()
            if int(capture_sample_rate) != int(target_sample_rate)
            else None
        )
        vad.start()
        bridge.start()
        chain.start(_speech_capabilities())
        blocksize = max(1, int(capture_sample_rate) // int(chunks_per_second))
        source = SoundDeviceInputSource(sd, blocksize=blocksize)
        adapter = MediaAdapter(
            source=source,
            vad=vad,
            resampler=resampler,
            target_sample_rate=int(target_sample_rate),
            on_event=events.append,
        )

        async def dispatch(frame: ProcessedAudioFrame) -> None:
            await bridge.accept_frame(frame)

        adapter.on_frame = dispatch
        assessment = adapter.start(device, _speech_capabilities())
        summary["device_opened"] = True
        summary["assessment_mode"] = assessment.mode
        worker = asyncio.create_task(adapter.run())
        print(f"[live-probe] collecting {duration_s:.1f}s; speak: “元亨，能听到吗”")
        await asyncio.sleep(float(duration_s))
        # Bounded drain so trailing speech finishes its ASR stream.
        try:
            await asyncio.wait_for(adapter.wait_idle(), timeout=2.0)
        except asyncio.TimeoutError:
            summary["drain_timed_out"] = True
        # Close the ASR bridge first (abort + flush per TargetVoiceRuntime
        # stop semantics), then stop media; never wait_idle on a live stream.
        try:
            await asyncio.wait_for(bridge.close("live_probe_complete"), timeout=6.0)
        except asyncio.TimeoutError:
            summary["bridge_close_timed_out"] = True
        adapter.stop()
        await asyncio.wait_for(worker, timeout=2.0)
        worker = None
        await asyncio.wait_for(chain.wait_idle(), timeout=3.0)

        counts = Counter(str(event.kind) for event in events)
        error_codes = [
            str(event.payload.get("code"))
            for event in events
            if isinstance(getattr(event, "payload", None), dict)
            and event.payload.get("code")
        ]
        completed_events = [
            event
            for event in events
            if str(event.kind) == "ASR_COMPLETED"
            and isinstance(getattr(event, "payload", None), dict)
        ]
        finals = [
            {
                "text_length": int(event.payload.get("text_length", 0) or 0),
                "elapsed_ms": int(event.payload.get("elapsed_ms", -1) or -1),
                "gate_event": str(event.payload.get("gate_event", "") or ""),
                "turn_id": str(getattr(event, "turn_id", "") or ""),
            }
            for event in completed_events
            if int(event.payload.get("text_length", 0) or 0) > 0
        ]
        wake_hit = any(f["gate_event"] == "activated" for f in finals)
        turn_id_valid = any(bool(f["turn_id"]) for f in finals)
        snapshot = chain.kernel.snapshot()
        summary.update(
            {
                "status": (
                    "passed"
                    if len(finals) > 0 and not error_codes
                    else "failed"
                ),
                "event_counts": dict(sorted(counts.items())),
                "error_codes": error_codes,
                "final_count": len(finals),
                "finals": finals,
                "wake_word_verified": bool(wake_hit),
                "turn_validated": bool(turn_id_valid),
                "chain_state": snapshot,
                "bridge_before_close": bridge.snapshot(),
                "vad_before_stop": vad.health(),
            }
        )
    except Exception as exc:
        code = getattr(exc, "code", None)
        summary.update(
            {
                "error_code": str(code)[:160] if code else "LIVE-INPUT-PROBE-FAILED",
                "error_type": type(exc).__name__,
                "detail": str(exc)[:160],
            }
        )
    finally:
        if worker is not None:
            worker.cancel()
            try:
                await worker
            except asyncio.CancelledError:
                pass
        if adapter is not None:
            try:
                adapter.stop()
            except Exception:
                pass
        try:
            await bridge.close("live_probe_finalize")
        finally:
            try:
                vad.stop("live_probe_finalize")
            finally:
                await chain.shutdown()
        summary["bridge_after_close"] = bridge.snapshot()
        summary["vad_after_stop"] = vad.health()
        summary["vad_stop_confirmed"] = vad.wait_stopped(1.0)
        summary["asr_stop_confirmed"] = asr.wait_stopped(1.0)
        summary["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 3)
        (output_dir / "summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    return summary


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device-id", type=int, default=1)
    parser.add_argument("--duration-s", type=float, default=15.0)
    parser.add_argument("--capture-sample-rate", type=int, default=16_000)
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args(argv)
    summary = asyncio.run(
        run_probe(
            args.output_dir or _default_output_dir(),
            device_id=args.device_id,
            duration_s=args.duration_s,
            capture_sample_rate=args.capture_sample_rate,
        )
    )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0 if summary.get("status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
