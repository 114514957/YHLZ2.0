"""Live human-in-the-loop probe: mic -> VAD -> streaming ASR -> 元亨 gate ->
hybrid LLM -> Qwen1.7B TTS -> physical speaker.

Runs the target composition root with real devices for a bounded window,
then records de-identified counts/timings.  No PCM/transcript/reply/log
persistence; the user speaks the fixed probe sentence once.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Sequence

from backend.llm_hybrid_compose import create_hybrid_reasoner
from backend.media_adapter import (
    AudioRoute,
    DeviceDescriptor,
    SoundDeviceInputSource,
)
from backend.session_kernel import ProviderCapabilities
from backend.target_composition import TargetVoiceComposition, TargetVoiceCompositionConfig
from backend.target_playback import PlaybackConfig, SoundDevicePlaybackPort
from backend.target_sherpa_asr import SherpaOnlineASRProvider
from backend.target_vad import TargetVADProvider
from backend.target_funasr_asr import FunasrOnlineASRProvider, FunasrASRConfig
from backend.tts_qwen_provider import QwenTTSConfig

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_MODEL_DIR = _PROJECT_ROOT / "models" / "qwen3-tts" / "Qwen3-TTS-12Hz-1.7B-CustomVoice"
# Voice/full-chain probe input sentence (distinct from the TTS/LLM text
# default "进步始于思想，元亨开拓未来" used for synthetic auditions).
SPOKEN_SENTENCE = "元亨，能听到吗"


class _TraceASR:
    """Streaming ASR wrapper that optionally records final texts (diag)."""

    def __init__(self, inner: Any, *, capture: bool = False) -> None:
        self.inner = inner
        self.capture = bool(capture)
        self.finals: list[str] = []

    def start(self) -> None:
        self.inner.start()

    def open_stream(self, *args, **kwargs) -> None:
        return self.inner.open_stream(*args, **kwargs)

    def push_audio(self, *args, **kwargs):
        return self.inner.push_audio(*args, **kwargs)

    def finish_stream(self, *args, **kwargs):
        update = self.inner.finish_stream(*args, **kwargs)
        if self.capture:
            text = str(getattr(update, "text", "") or "")
            if text:
                self.finals.append(text)
        return update

    def interrupt(self, reason: str = "interrupt") -> None:
        m = getattr(self.inner, "interrupt", None)
        if callable(m):
            m(reason)

    async def wait_stopped(self, timeout_s: float) -> bool:
        m = getattr(self.inner, "wait_stopped", None)
        if callable(m):
            result = m(timeout_s)
            if hasattr(result, "__await__"):
                return bool(await result)
            return bool(result)
        return True

    def stop(self, reason: str = "shutdown") -> None:
        self.inner.stop(reason)

    def health(self) -> dict:
        return dict(self.inner.health() or {})


class _RadarVAD:
    """VAD wrapper that prints per-frame RMS/probability for diagnosis."""

    def __init__(self, inner: Any, *, radar: bool = False, every: int = 10) -> None:
        self.inner = inner
        self.radar = bool(radar)
        self.every = int(every)
        self._n = 0
        self.max_rms = 0.0
        self.max_prob = 0.0
        self.speech_frames = 0
        self.frames = 0

    def start(self) -> None:
        self.inner.start()

    def detect_speech(self, audio: Any, sample_rate: int) -> bool:
        import numpy as np

        speech = bool(self.inner.detect_speech(audio, sample_rate))
        try:
            prob = float(self.inner.health().get("last_probability", 0.0) or 0.0)
        except Exception:
            prob = 0.0
        try:
            rms = float(np.sqrt(float(np.mean(np.square(np.asarray(audio, dtype="float32"))))))
        except Exception:
            rms = 0.0
        self.frames += 1
        self.max_rms = max(self.max_rms, rms)
        self.max_prob = max(self.max_prob, prob)
        if speech:
            self.speech_frames += 1
        self._n += 1
        if self.radar and (rms > 1e-4 or prob > 0.1 or self._n % self.every == 0):
            print(
                f"[radar #{self._n}] rms={rms:.5f} prob={prob:.4f} speech={speech}",
                flush=True,
            )
        return speech

    def stop(self, reason: str = "shutdown") -> None:
        self.inner.stop(reason)

    def wait_stopped(self, timeout_s: float) -> bool:
        waiter = getattr(self.inner, "wait_stopped", None)
        if callable(waiter):
            return bool(waiter(timeout_s))
        return True

    def health(self) -> dict:
        base = dict(self.inner.health() or {})
        base.update(
            {
                "radar_frames": self.frames,
                "radar_speech_frames": self.speech_frames,
                "radar_max_rms": round(self.max_rms, 6),
                "radar_max_prob": round(self.max_prob, 5),
            }
        )
        return base


def _default_output_dir() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return _PROJECT_ROOT / "artifacts" / "realtime_probe" / ("rt_" + stamp)


async def run_probe(
    output_dir: Path,
    *,
    device_id: int = 1,
    capture_sample_rate: int = 16_000,
    duration_s: float = 30.0,
    model_dir: Path = _DEFAULT_MODEL_DIR,
    playback_device: int = 3,
    max_tokens: int = 64,
    disable_denoiser: bool = False,
    capture_final_text: bool = False,
    asr_backend: str = "sherpa",
) -> dict:
    output_dir.mkdir(parents=True, exist_ok=False)
    import sounddevice as sd
    from pathlib import Path as _Path

    if asr_backend == "funasr":
        asr_provider = FunasrOnlineASRProvider(
            FunasrASRConfig(model_dir=_Path(_DEFAULT_MODEL_DIR).parents[1] / "asr" / "paraformer-zh-streaming")
        )
    else:
        asr_provider = SherpaOnlineASRProvider()

    summary: dict[str, Any] = {
        "probe": "target_realtime_rt_v1",
        "status": "failed",
        "device_opened": False,
        "playback_started": False,
        "audio_persisted": False,
        "memory_written": False,
    }
    playback = SoundDevicePlaybackPort(
        PlaybackConfig(device=playback_device, channels=2, volume=1.0)
    )
    reasoner = create_hybrid_reasoner(max_tokens=max_tokens)
    composition = TargetVoiceComposition(
        TargetVoiceCompositionConfig(
            qwen=QwenTTSConfig(model_dir=model_dir),
            noise_suppressor_enabled=not disable_denoiser,
        ),
        reasoner=reasoner,
        playback=playback,
    )
    runtime = None
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
        radar_vad = _RadarVAD(TargetVADProvider(), radar=True, every=10)
        trace_asr = _TraceASR(asr_provider, capture=capture_final_text)
        runtime = composition.create_runtime(
            asr=trace_asr,
            source=SoundDeviceInputSource(sd, blocksize=1600),
            vad=radar_vad,
        )
        assessment = composition.start(device, ProviderCapabilities(continuous_capture=True))
        summary["device_opened"] = True
        summary["capability_mode"] = assessment.mode.value
        run_task = asyncio.create_task(composition.run())
        for i in range(3, 0, -1):
            print(f"[rt-probe] collecting in {i}s... countdown")
            await asyncio.sleep(1.0)
        print("=" * 48)
        print(f"[rt-probe] READY — speak now: “{SPOKEN_SENTENCE}”")
        print("[rt-probe] then wait for the reply; whisper once playback starts.")
        print("=" * 48)
        await asyncio.sleep(max(1.0, float(duration_s) - 3.0))
        await composition.stop("probe_window_end")
        try:
            await asyncio.wait_for(run_task, timeout=5.0)
        except asyncio.TimeoutError:
            summary["run_task_timeout"] = True
            run_task.cancel()
        await composition.chain.wait_idle()
        events = composition.kernel.recent_events(1024)
        from collections import Counter

        counts = Counter(str(e.get("kind", "")) for e in events)
        error_samples = [
            str(e.get("payload", {}))[:300]
            for e in events
            if str(e.get("kind", "")) == "ERROR"
        ][:5]
        summary.update(
            {
                "status": "passed" if counts.get("AUDIO_DONE", 0) >= 1 else "failed",
                "event_counts": dict(sorted(counts.items())),
                "error_samples": error_samples,
                "task_events_seen": int(counts.get("TOKEN", 0)),
                "reasoner_first_token_ms": reasoner.last_first_token_ms,
                "reasoner_tokens": reasoner.last_tokens,
                "hybrid_using_backup": bool(reasoner.provider.using_backup),
                "media_health": runtime.media.health() if runtime else None,
                "bridge_snapshot": runtime.asr.snapshot() if runtime else None,
                "vad_radar": radar_vad.health(),
                "asr_finals_captured": list(trace_asr.finals),
                "chain_snapshot": composition.chain.snapshot(),
            }
        )
    except Exception as exc:
        summary["error_code"] = getattr(exc, "code", None) or "REALTIME-PROBE-FAILED"
        summary["error_type"] = type(exc).__name__
        summary["detail"] = str(exc)[:200]
    finally:
        try:
            if runtime is not None:
                await runtime.stop("probe_finalize")
        except Exception as stop_exc:
            summary["stop_error"] = type(stop_exc).__name__
        try:
            await composition.shutdown("realtime_probe_complete")
        except Exception as shutdown_exc:
            summary["shutdown_error"] = type(shutdown_exc).__name__
        summary["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 1)
        (output_dir / "summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    return summary


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device-id", type=int, default=1)
    parser.add_argument("--capture-sample-rate", type=int, default=16_000)
    parser.add_argument("--duration-s", type=float, default=30.0)
    parser.add_argument("--model-dir", type=Path, default=_DEFAULT_MODEL_DIR)
    parser.add_argument("--playback-device", type=int, default=3)
    parser.add_argument("--max-tokens", type=int, default=64)
    parser.add_argument("--disable-denoiser", action="store_true")
    parser.add_argument("--capture-final-text", action="store_true")
    parser.add_argument("--asr-backend", choices=["sherpa", "funasr"], default="sherpa")
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args(argv)
    summary = asyncio.run(
        run_probe(
            args.output_dir or _default_output_dir(),
            device_id=args.device_id,
            capture_sample_rate=args.capture_sample_rate,
            duration_s=args.duration_s,
            model_dir=args.model_dir,
            playback_device=args.playback_device,
            max_tokens=args.max_tokens,
            disable_denoiser=args.disable_denoiser,
            capture_final_text=args.capture_final_text,
            asr_backend=args.asr_backend,
        )
    )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0 if summary.get("status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
