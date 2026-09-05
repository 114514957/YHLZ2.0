"""No-device end-to-end probe for :mod:`backend.target_composition`.

The executable routes one fixed synthetic turn through the composition root and
the Qwen process Provider.  It never imports ``main.py``, opens a microphone
or speaker, writes PCM, touches business data, or mutates ``memory``.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import platform
import sys
import time
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.media_adapter import DeviceDescriptor
from backend.session_kernel import ProviderCapabilities
from backend.target_composition import TargetVoiceComposition, TargetVoiceCompositionConfig
from backend.tts_qwen_provider import QwenTTSConfig


_TRANSCRIPT = "元亨，能听到吗"
_REPLY = "进步始于思想，元亨开拓未来。"


class _ProbeReasoner:
    async def generate(self, text: str, signal: Any):
        yield _REPLY


class _NoopASR:
    async def transcribe(self, segment: Any, signal: Any) -> str:
        return ""

    def start(self) -> None:
        return None

    def interrupt(self, reason: str = "interrupt") -> None:
        return None

    async def wait_stopped(self, timeout_s: float) -> bool:
        return True

    def stop(self, reason: str = "shutdown") -> None:
        return None

    def health(self) -> dict:
        return {"available": False, "state": "probe_no_asr"}


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


async def _run(args: argparse.Namespace) -> dict:
    os.environ.update({"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"})
    qwen = QwenTTSConfig(
        model_dir=Path(args.model_dir),
        speaker=args.speaker,
        language=args.language,
        chunk_size=args.chunk_size,
        max_new_tokens=args.max_new_tokens,
        queue_maxsize=args.queue_maxsize,
        stop_timeout_s=args.stop_timeout_s,
        warmup_text=None if args.no_warmup else args.warmup_text,
    )
    composition = TargetVoiceComposition(
        TargetVoiceCompositionConfig(
            qwen=qwen,
            worker_id="target-composition-probe",
            startup_timeout_s=args.startup_timeout_s,
            stop_timeout_s=args.stop_timeout_s,
        ),
        reasoner=_ProbeReasoner(),
    )
    result: dict = {
        "probe_version": "target-composition-v1",
        "timestamp": time.time(),
        "python": sys.version,
        "platform": platform.platform(),
        "offline_mode": True,
        "device_access": False,
        "entrypoint_imported": "backend.main" in sys.modules,
        "input_fingerprint": _fingerprint(_TRANSCRIPT),
        "reply_fingerprint": _fingerprint(_REPLY),
        "config": composition.config.to_dict(),
    }
    try:
        runtime = composition.create_runtime(asr=_NoopASR())
        device = DeviceDescriptor(
            device_id="no-device-probe",
            name="no-device-probe",
            input_channels=1,
            output_channels=0,
            sample_rate=24_000,
        )
        assessment = composition.start(device, ProviderCapabilities())
        started_at = time.perf_counter()
        submission = await composition.chain.submit_transcript(_TRANSCRIPT, source="probe")
        if submission.task is None:
            raise RuntimeError("wake gate did not accept fixed probe transcript")
        outcome = await submission.task
        elapsed_ms = int(round((time.perf_counter() - started_at) * 1000))
        events = composition.kernel.recent_events(128)
        event_kinds = [str(event.get("kind", "")) for event in events]
        tts_metrics = composition.chain.snapshot().get("ports", {}).get("tts_provider_metrics")
        result.update(
            {
                "runtime_state_before_shutdown": runtime.state.value,
                "capability_mode": assessment.mode.value,
                "outcome": {
                    "status": outcome.status,
                    "committed": outcome.committed,
                    "error_code": outcome.error_code,
                    "elapsed_ms": elapsed_ms,
                },
                "event_kinds": event_kinds,
                "event_counts": {kind: event_kinds.count(kind) for kind in sorted(set(event_kinds))},
                "tts_metrics": tts_metrics,
                "provider_health_before_shutdown": composition.tts_provider.health(),
                "provider_metrics_before_shutdown": composition.tts_provider.metrics(),
                "acceptance": {
                    "turn_completed": outcome.status == "completed",
                    "audio_chunk_seen": "AUDIO_CHUNK" in event_kinds,
                    "audio_done_seen": "AUDIO_DONE" in event_kinds,
                    "entrypoint_untouched": "backend.main" not in sys.modules,
                },
            }
        )
    finally:
        await composition.shutdown("composition_probe_complete")
        result["closed"] = composition.closed
        result["provider_health_after_shutdown"] = composition.tts_provider.health()
    return result


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--speaker", default="Vivian")
    parser.add_argument("--language", default="chinese")
    parser.add_argument("--chunk-size", type=int, default=8)
    parser.add_argument("--max-new-tokens", type=int, default=2048)
    parser.add_argument("--queue-maxsize", type=int, default=32)
    parser.add_argument("--stop-timeout-s", type=float, default=5.0)
    parser.add_argument("--startup-timeout-s", type=float, default=90.0)
    parser.add_argument("--warmup-text", default="你好。")
    parser.add_argument("--no-warmup", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    out_dir = Path(args.out_dir)
    try:
        result = asyncio.run(_run(args))
    except Exception as exc:
        result = {
            "probe_version": "target-composition-v1",
            "timestamp": time.time(),
            "offline_mode": True,
            "device_access": False,
            "error_code": type(exc).__name__,
            "detail": str(exc)[:400],
        }
        _write_json(out_dir / "summary.json", result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1
    _write_json(out_dir / "summary.json", result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    acceptance = result.get("acceptance", {})
    return 0 if all(bool(value) for value in acceptance.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
