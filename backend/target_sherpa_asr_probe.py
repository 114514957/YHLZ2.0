"""Bounded no-device probe for the verified local Sherpa streaming ASR path."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import time
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Sequence

import numpy as np

from backend.asr_provider_port import ASRProviderError, ASRStreamUpdateKind
from backend.target_chain import CancellationSignal
from backend.target_sherpa_asr import (
    DEFAULT_ASR_ASSET_DIR,
    SherpaOnlineASRConfig,
    SherpaOnlineASRProvider,
)


_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _default_output_dir() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return _PROJECT_ROOT / "artifacts" / "asr_probe" / ("isolated_" + stamp)


def _load_fixed_sample(path: Path) -> tuple[np.ndarray, int]:
    """Read a bundled upstream test sample without writing it anywhere."""
    with wave.open(str(path), "rb") as source:
        channels = source.getnchannels()
        sample_width = source.getsampwidth()
        sample_rate = source.getframerate()
        frames = source.readframes(source.getnframes())
    if channels != 1 or sample_width != 2:
        raise ValueError("probe sample must be mono signed-16-bit PCM")
    samples = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    return samples, int(sample_rate)


async def run_probe(
    output_dir: Path,
    *,
    sample_path: Path,
    chunk_ms: int = 100,
    cancel_after_chunks: Optional[int] = None,
    config: Optional[SherpaOnlineASRConfig] = None,
) -> dict:
    """Run one bounded 16 kHz fixed-sample stream without persisting PCM/text."""
    if int(chunk_ms) <= 0 or int(chunk_ms) > 500:
        raise ValueError("chunk_ms must be within (0, 500]")
    if cancel_after_chunks is not None and int(cancel_after_chunks) <= 0:
        raise ValueError("cancel_after_chunks must be positive when set")
    output_dir.mkdir(parents=True, exist_ok=False)
    provider = SherpaOnlineASRProvider(config or SherpaOnlineASRConfig())
    started = time.perf_counter()
    summary: dict[str, Any] = {
        "probe": "target_sherpa_streaming_asr_v1",
        "status": "failed",
        "device_opened": False,
        "playback_started": False,
        "audio_persisted": False,
        "transcript_persisted": False,
        "sample_source": "bundled_upstream_test_asset",
        "chunk_ms": int(chunk_ms),
        "path": "cancel" if cancel_after_chunks is not None else "normal",
    }
    signal = CancellationSignal()
    stream_id = "probe_stream"
    final_text = ""
    partial_count = 0
    first_partial_ms: Optional[float] = None
    input_duration_s = 0.0
    try:
        samples, sample_rate = _load_fixed_sample(sample_path)
        if sample_rate != 16_000:
            raise ValueError("probe sample must be 16000 Hz")
        input_duration_s = samples.size / float(sample_rate)
        provider.start()
        provider.open_stream(stream_id, 1, sample_rate, 1, signal)
        stream_started = time.perf_counter()
        chunk_samples = int(sample_rate * int(chunk_ms) / 1000)
        chunks_sent = 0
        for offset in range(0, samples.size, chunk_samples):
            updates = provider.push_audio(
                stream_id,
                samples[offset : offset + chunk_samples],
                sample_rate,
                signal,
            )
            for update in updates:
                if update.kind is ASRStreamUpdateKind.PARTIAL:
                    partial_count += 1
                    if first_partial_ms is None:
                        first_partial_ms = round((time.perf_counter() - stream_started) * 1000, 3)
            chunks_sent += 1
            if cancel_after_chunks is not None and chunks_sent >= int(cancel_after_chunks):
                cancel_started = time.perf_counter()
                provider.interrupt("probe_cancel")
                stopped = provider.wait_stopped(1.0)
                summary.update(
                    {
                        "status": "passed" if stopped else "failed",
                        "sample_rate": sample_rate,
                        "input_duration_s": round(input_duration_s, 6),
                        "input_samples": int(samples.size),
                        "chunks_sent": chunks_sent,
                        "partial_count": partial_count,
                        "first_partial_ms": first_partial_ms,
                        "cancel_elapsed_ms": round((time.perf_counter() - cancel_started) * 1000, 3),
                        "cancel_stop_confirmed": bool(stopped),
                        "provider_before_stop": provider.health(),
                    }
                )
                return summary
        final = provider.finish_stream(stream_id, signal)
        if final.kind is ASRStreamUpdateKind.FINAL:
            final_text = final.text
        if final.kind is not ASRStreamUpdateKind.FINAL or not final_text:
            raise ASRProviderError("ASR-PROBE-EMPTY-FINAL")
        processing_s = time.perf_counter() - stream_started
        summary.update(
            {
                "status": "passed",
                "sample_rate": sample_rate,
                "input_duration_s": round(input_duration_s, 6),
                "input_samples": int(samples.size),
                "chunks_sent": chunks_sent,
                "partial_count": partial_count,
                "first_partial_ms": first_partial_ms,
                "final_elapsed_ms": round(processing_s * 1000, 3),
                "rtf": round(processing_s / input_duration_s, 6) if input_duration_s else None,
                "final_text_length": len(final_text),
                "final_text_sha256": hashlib.sha256(final_text.encode("utf-8")).hexdigest(),
                "provider_before_stop": provider.health(),
            }
        )
    except ASRProviderError as exc:
        summary.update(
            {
                "error_code": exc.code,
                "error_type": type(exc).__name__,
                "detail": exc.detail,
            }
        )
    except Exception as exc:
        summary.update(
            {
                "error_code": "ASR-PROBE-FAILED",
                "error_type": type(exc).__name__,
                "detail": str(exc)[:160],
            }
        )
    finally:
        provider.stop("probe_complete")
        summary["stop_confirmed"] = provider.wait_stopped(1.0)
        summary["provider_after_stop"] = provider.health()
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
    parser.add_argument("--chunk-ms", type=int, default=100)
    parser.add_argument("--cancel-after-chunks", type=int, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args(argv)
    summary = asyncio.run(
        run_probe(
            args.output_dir or _default_output_dir(),
            sample_path=args.sample_path,
            chunk_ms=args.chunk_ms,
            cancel_after_chunks=args.cancel_after_chunks,
        )
    )
    # The console output deliberately contains the same redacted summary as
    # the artifact; it never prints PCM or a transcript.
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0 if summary.get("status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
