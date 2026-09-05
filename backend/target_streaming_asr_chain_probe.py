"""No-device VAD-to-streaming-ASR chain probe using a fixed upstream sample."""

from __future__ import annotations

import argparse
import asyncio
import json
import time
import wave
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Sequence

import numpy as np

from backend.media_adapter import AudioFrame, ProcessedAudioFrame
from backend.session_kernel import ProviderCapabilities
from backend.streaming_asr_bridge import StreamingASRBridge
from backend.target_chain import TargetVoiceChain
from backend.target_sherpa_asr import DEFAULT_ASR_ASSET_DIR, SherpaOnlineASRProvider
from backend.target_vad import TargetVADProvider


_PROJECT_ROOT = Path(__file__).resolve().parent.parent


class _NoopReasoner:
    """A no-output reasoner in case the fixed sample contains the wake word."""

    async def generate(self, _text: str, _signal: Any):
        if False:
            yield ""


def _default_output_dir() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return _PROJECT_ROOT / "artifacts" / "asr_probe" / ("chain_" + stamp)


def _read_sample(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as source:
        if (
            source.getnchannels() != 1
            or source.getsampwidth() != 2
            or source.getframerate() != 16_000
        ):
            raise ValueError("probe sample must be mono 16-bit 16000 Hz PCM")
        raw = source.readframes(source.getnframes())
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


async def run_probe(
    output_dir: Path,
    *,
    sample_path: Path,
    chunk_samples: int = 1_600,
) -> dict:
    """Run VAD and live ASR over bounded in-memory non-user PCM only."""
    if int(chunk_samples) <= 0 or int(chunk_samples) > 3_200:
        raise ValueError("chunk_samples must be within (0, 3200]")
    output_dir.mkdir(parents=True, exist_ok=False)
    vad = TargetVADProvider()
    asr = SherpaOnlineASRProvider()
    events = []
    chain = TargetVoiceChain(reasoner=_NoopReasoner())
    chain.start(ProviderCapabilities(continuous_capture=True))
    bridge = StreamingASRBridge(asr=asr, chain=chain, on_event=events.append)
    started = time.perf_counter()
    summary: dict[str, Any] = {
        "probe": "target_vad_streaming_asr_chain_v1",
        "status": "failed",
        "device_opened": False,
        "playback_started": False,
        "audio_persisted": False,
        "transcript_persisted": False,
        "memory_written": False,
        "sample_source": "bundled_upstream_test_asset",
        "chunk_samples": int(chunk_samples),
    }
    try:
        samples = _read_sample(sample_path)
        vad.start()
        bridge.start()
        sequence = 0

        async def feed(chunk: np.ndarray) -> None:
            nonlocal sequence
            sequence += 1
            speech = vad.detect_speech(chunk, 16_000)
            frame = AudioFrame(
                samples=chunk,
                sample_rate=16_000,
                channels=1,
                sequence=sequence,
                generation=1,
                duration_ms=int(round(chunk.size * 1000 / 16_000)),
            )
            await bridge.accept_frame(
                ProcessedAudioFrame(frame=frame, samples=chunk, speech=speech, aec_applied=False)
            )
            # Synthetic feed is much faster than wall-clock capture. Let the
            # bounded ASR worker make progress so this probe exercises normal
            # flow rather than intentionally triggering backpressure.
            for _ in range(200):
                if bridge.snapshot()["queue_depth"] <= 1:
                    break
                await asyncio.sleep(0.001)

        for offset in range(0, samples.size, int(chunk_samples)):
            await feed(samples[offset : offset + int(chunk_samples)])
        # Flush the VAD hysteresis with bounded synthetic silence. This is
        # not saved and is necessary for a final ASR stream disposition.
        for _ in range(5):
            await feed(np.zeros(int(chunk_samples), dtype=np.float32))
        await bridge.wait_idle()
        await chain.wait_idle()
        counts = Counter(str(event.kind) for event in events)
        error_codes = [
            str(event.payload.get("code"))
            for event in events
            if isinstance(getattr(event, "payload", None), dict)
            and event.payload.get("code")
        ]
        completed = int(counts.get("ASR_COMPLETED", 0))
        summary.update(
            {
                "status": "passed" if completed > 0 and not error_codes else "failed",
                "input_samples": int(samples.size),
                "input_duration_s": round(samples.size / 16_000, 6),
                "event_counts": dict(sorted(counts.items())),
                "error_codes": error_codes,
                "completed_streams": completed,
                "partial_updates": int(counts.get("ASR_PARTIAL", 0)),
                "bridge_before_close": bridge.snapshot(),
                "vad_before_stop": vad.health(),
                "chain_state": chain.kernel.snapshot(),
            }
        )
    except Exception as exc:
        code = getattr(exc, "code", None)
        summary.update(
            {
                "error_code": str(code)[:160] if code else "ASR-CHAIN-PROBE-FAILED",
                "error_type": type(exc).__name__,
                "detail": str(exc)[:160],
            }
        )
    finally:
        try:
            await bridge.close("chain_probe_complete")
        finally:
            vad.stop("chain_probe_complete")
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
    parser.add_argument(
        "--sample-path",
        type=Path,
        default=DEFAULT_ASR_ASSET_DIR / "test_wavs" / "0.wav",
    )
    parser.add_argument("--chunk-samples", type=int, default=1_600)
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args(argv)
    summary = asyncio.run(
        run_probe(
            args.output_dir or _default_output_dir(),
            sample_path=args.sample_path,
            chunk_samples=args.chunk_samples,
        )
    )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0 if summary.get("status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
