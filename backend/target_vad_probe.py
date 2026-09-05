"""No-device verification probe for the local target Silero VAD provider."""

from __future__ import annotations

import argparse
import json
import time
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Sequence

import numpy as np

from backend.target_vad import TargetVADProvider, VADProviderError


_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _default_output_dir() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return _PROJECT_ROOT / "artifacts" / "vad_probe" / ("isolated_" + stamp)


def run_isolated_probe(output_dir: Path, *, blocks: int = 5) -> dict:
    """Load verified ONNX once and process synthetic silence without devices."""
    if blocks <= 0:
        raise ValueError("blocks must be positive")
    output_dir.mkdir(parents=True, exist_ok=False)
    provider = TargetVADProvider()
    started = time.perf_counter()
    decisions: list[bool] = []
    summary: dict[str, Any] = {
        "probe": "target_vad_isolated_v1",
        "device_opened": False,
        "audio_persisted": False,
        "blocks": int(blocks),
        "status": "failed",
    }
    try:
        provider.start()
        load_ms = round((time.perf_counter() - started) * 1000, 3)
        # Five 100 ms float32 mono frames exercise pending windows, context,
        # LSTM state and hysteresis without exposing real microphone audio.
        frame = np.zeros((1_600, 1), dtype=np.float32)
        processing_started = time.perf_counter()
        for _ in range(blocks):
            decisions.append(provider.detect_speech(frame, 16_000))
        process_ms = round((time.perf_counter() - processing_started) * 1000, 3)
        before_stop = provider.health()
        provider.stop("isolated_probe_complete")
        stopped = provider.wait_stopped(1.0)
        summary.update(
            {
                "status": "passed",
                "load_ms": load_ms,
                "process_ms": process_ms,
                "decision_counts": {
                    "speech": sum(1 for value in decisions if value),
                    "non_speech": sum(1 for value in decisions if not value),
                },
                "provider_before_stop": before_stop,
                "stop_confirmed": bool(stopped),
                "provider_after_stop": provider.health(),
            }
        )
    except VADProviderError as exc:
        summary.update(
            {
                "error_code": exc.code,
                "error_type": type(exc).__name__,
                "provider_after_error": provider.health(),
            }
        )
        provider.stop("isolated_probe_failed")
        summary["stop_confirmed"] = provider.wait_stopped(1.0)
        summary["provider_after_stop"] = provider.health()
    except Exception as exc:
        summary.update(
            {
                "error_code": "VAD-PROBE-UNEXPECTED",
                "error_type": type(exc).__name__,
                "provider_after_error": provider.health(),
            }
        )
        provider.stop("isolated_probe_failed")
        summary["stop_confirmed"] = provider.wait_stopped(1.0)
        summary["provider_after_stop"] = provider.health()
    finally:
        summary["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 3)
        (output_dir / "summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    return summary


def run_fixed_sample_probe(
    output_dir: Path,
    *,
    sample_path: Path,
    block_samples: int = 1_600,
) -> dict:
    """Run VAD over one bundled non-user sample without retaining audio/text."""
    if int(block_samples) <= 0 or int(block_samples) > 3_200:
        raise ValueError("block_samples must be within (0, 3200]")
    output_dir.mkdir(parents=True, exist_ok=False)
    provider = TargetVADProvider()
    started = time.perf_counter()
    summary: dict[str, Any] = {
        "probe": "target_vad_fixed_sample_v1",
        "status": "failed",
        "device_opened": False,
        "audio_persisted": False,
        "transcript_persisted": False,
        "sample_source": "bundled_upstream_test_asset",
        "block_samples": int(block_samples),
    }
    try:
        with wave.open(str(sample_path), "rb") as source:
            channels = source.getnchannels()
            sample_width = source.getsampwidth()
            sample_rate = source.getframerate()
            raw = source.readframes(source.getnframes())
        if channels != 1 or sample_width != 2 or sample_rate != 16_000:
            raise ValueError("probe sample must be mono 16-bit 16000 Hz PCM")
        samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        provider.start()
        load_ms = round((time.perf_counter() - started) * 1000, 3)
        processing_started = time.perf_counter()
        decisions: list[bool] = []
        for offset in range(0, samples.size, int(block_samples)):
            decisions.append(provider.detect_speech(samples[offset : offset + int(block_samples)], 16_000))
        process_ms = round((time.perf_counter() - processing_started) * 1000, 3)
        before_stop = provider.health()
        speech_blocks = sum(1 for value in decisions if value)
        provider.stop("fixed_sample_probe_complete")
        stopped = provider.wait_stopped(1.0)
        summary.update(
            {
                "status": "passed" if speech_blocks > 0 and stopped else "failed",
                "sample_rate": int(sample_rate),
                "input_samples": int(samples.size),
                "input_duration_s": round(samples.size / float(sample_rate), 6),
                "load_ms": load_ms,
                "process_ms": process_ms,
                "decision_counts": {
                    "speech": speech_blocks,
                    "non_speech": len(decisions) - speech_blocks,
                },
                "provider_before_stop": before_stop,
                "stop_confirmed": bool(stopped),
                "provider_after_stop": provider.health(),
            }
        )
        if speech_blocks <= 0:
            summary["error_code"] = "VAD-PROBE-NO-SPEECH"
    except VADProviderError as exc:
        summary.update(
            {
                "error_code": exc.code,
                "error_type": type(exc).__name__,
                "provider_after_error": provider.health(),
            }
        )
        provider.stop("fixed_sample_probe_failed")
        summary["stop_confirmed"] = provider.wait_stopped(1.0)
        summary["provider_after_stop"] = provider.health()
    except Exception as exc:
        summary.update(
            {
                "error_code": "VAD-PROBE-UNEXPECTED",
                "error_type": type(exc).__name__,
                "detail": str(exc)[:160],
                "provider_after_error": provider.health(),
            }
        )
        provider.stop("fixed_sample_probe_failed")
        summary["stop_confirmed"] = provider.wait_stopped(1.0)
        summary["provider_after_stop"] = provider.health()
    finally:
        summary["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 3)
        (output_dir / "summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    return summary


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--blocks", type=int, default=5)
    parser.add_argument("--sample-path", type=Path, default=None)
    parser.add_argument("--block-samples", type=int, default=1_600)
    args = parser.parse_args(argv)
    output_dir = args.output_dir or _default_output_dir()
    if args.sample_path is None:
        summary = run_isolated_probe(output_dir, blocks=args.blocks)
    else:
        summary = run_fixed_sample_probe(
            output_dir,
            sample_path=args.sample_path,
            block_samples=args.block_samples,
        )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0 if summary.get("status") == "passed" and summary.get("stop_confirmed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
