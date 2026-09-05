"""Bounded no-persistence microphone/VAD probe for the target input path."""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

from backend.media_adapter import DeviceDescriptor, MediaAdapter, SoundDeviceInputSource
from backend.session_kernel import AudioRoute, ProviderCapabilities
from backend.target_input_resampler import TargetInputResampler
from backend.target_vad import TargetVADProvider, VADProviderError


_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _default_output_dir() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return _PROJECT_ROOT / "artifacts" / "vad_probe" / ("input_" + stamp)


def _input_capabilities() -> ProviderCapabilities:
    """Describe only observed input capability; no unmeasured C assertions."""
    return ProviderCapabilities(
        continuous_capture=True,
        concurrent_input_output=False,
        audio_route=AudioRoute.UNKNOWN.value,
        audio_route_verified=False,
        vad_verified=False,
        wake_word_verified=False,
        asr_tts_concurrent=False,
        cancel_asr=False,
        cancel_generation=False,
        cancel_tts=False,
        cancel_playback=False,
        playback_verified=False,
        resource_budget_verified=False,
    )


async def run_input_probe(
    output_dir: Path,
    *,
    device_id: int,
    duration_s: float,
    capture_sample_rate: int = 16_000,
    target_sample_rate: int = 16_000,
    sounddevice_module: Any = None,
    provider_factory: Callable[[], Any] = TargetVADProvider,
) -> dict:
    """Open one explicit mono float32 input stream for at most five seconds."""
    if not 0.0 < float(duration_s) <= 5.0:
        raise ValueError("duration_s must be within (0, 5]")
    if int(target_sample_rate) != 16_000:
        raise ValueError("target_sample_rate must remain 16000 for TargetVADProvider")
    output_dir.mkdir(parents=True, exist_ok=False)
    if sounddevice_module is None:
        import sounddevice as sd
    else:
        sd = sounddevice_module

    summary: dict[str, Any] = {
        "probe": "target_input_vad_v1",
        "status": "failed",
        "duration_budget_s": float(duration_s),
        "capture_sample_rate": int(capture_sample_rate),
        "processing_sample_rate": int(target_sample_rate),
        "device_opened": False,
        "audio_persisted": False,
        "asr_started": False,
        "playback_started": False,
    }
    provider = provider_factory()
    adapter: Optional[MediaAdapter] = None
    worker: Optional[asyncio.Task] = None
    frames = 0
    events: list[Any] = []
    drain_timed_out = False
    started = time.perf_counter()
    try:
        descriptor = sd.query_devices(device_id)
        sd.check_input_settings(
            device=device_id,
            samplerate=capture_sample_rate,
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
        provider.start()
        resampler = (
            TargetInputResampler()
            if int(capture_sample_rate) != int(target_sample_rate)
            else None
        )

        def on_frame(_frame: Any) -> None:
            nonlocal frames
            frames += 1

        blocksize = max(1, int(capture_sample_rate) // 10)
        source = SoundDeviceInputSource(sd, blocksize=blocksize)
        adapter = MediaAdapter(
            source=source,
            vad=provider,
            resampler=resampler,
            target_sample_rate=target_sample_rate,
            on_frame=on_frame,
            on_event=events.append,
        )
        assessment = adapter.start(device, _input_capabilities())
        summary["device_opened"] = True
        worker = asyncio.create_task(adapter.run())
        await asyncio.sleep(float(duration_s))
        try:
            # Capture remains active during this bounded join; it only proves
            # that frames already accepted by the queue reached VAD before
            # stop invalidates the next media generation.
            await asyncio.wait_for(adapter.wait_idle(), timeout=1.0)
        except asyncio.TimeoutError:
            drain_timed_out = True
        adapter.stop()
        await asyncio.wait_for(worker, timeout=2.0)
        worker = None
        vad_before_stop = provider.health()
        # VAD remains intentionally loaded during capture; this explicit
        # stop releases only its in-memory state before the summary is made.
        provider.stop("input_probe_complete")
        stopped = provider.wait_stopped(1.0)
        event_codes = [
            str(getattr(event, "code", ""))
            for event in events
            if getattr(event, "code", None)
        ]
        errors = [code for code in event_codes if code]
        if drain_timed_out:
            errors.append("VAD-INPUT-DRAIN-TIMEOUT")
        summary.update(
            {
                "status": "passed" if frames > 0 and not errors and stopped else "failed",
                "device": device.to_dict(),
                "assessment": {
                    "mode": assessment.mode.value,
                    "missing_for_c": list(assessment.missing_for_c),
                },
                "frame_count": frames,
                "event_counts": {
                    str(kind): sum(1 for event in events if str(getattr(event, "kind", "")) == str(kind))
                    for kind in sorted({str(getattr(event, "kind", "")) for event in events})
                },
                "error_codes": errors,
                "drain_timed_out": drain_timed_out,
                "media_health": adapter.health(),
                "resampler": resampler.health() if resampler is not None else None,
                "vad_before_stop": vad_before_stop,
                "stop_confirmed": bool(stopped),
            }
        )
        if frames <= 0:
            summary["error_codes"] = [*summary["error_codes"], "VAD-INPUT-NO-FRAMES"]
    except VADProviderError as exc:
        summary.update(
            {
                "error_code": exc.code,
                "error_type": type(exc).__name__,
                "detail": exc.detail,
            }
        )
    except Exception as exc:
        cause = exc.__cause__ or exc.__context__
        summary.update(
            {
                "error_code": "VAD-INPUT-PROBE-FAILED",
                "error_type": type(exc).__name__,
                "detail": str(exc)[:160],
                "cause_type": type(cause).__name__ if cause is not None else None,
                "cause_detail": str(cause)[:160] if cause is not None else None,
            }
        )
    finally:
        if adapter is not None:
            adapter.stop()
        if worker is not None and not worker.done():
            worker.cancel()
            try:
                await worker
            except asyncio.CancelledError:
                pass
        provider.stop("input_probe_finally")
        summary["vad_after_stop"] = provider.health()
        summary["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 3)
        (output_dir / "summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    return summary


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device-id", type=int, default=1)
    parser.add_argument("--duration-s", type=float, default=5.0)
    parser.add_argument("--capture-sample-rate", type=int, default=16_000)
    parser.add_argument("--target-sample-rate", type=int, default=16_000)
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args(argv)
    summary = asyncio.run(
        run_input_probe(
            args.output_dir or _default_output_dir(),
            device_id=args.device_id,
            duration_s=args.duration_s,
            capture_sample_rate=args.capture_sample_rate,
            target_sample_rate=args.target_sample_rate,
        )
    )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0 if summary.get("status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
