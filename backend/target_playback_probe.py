"""Bounded speaker-only probe for the isolated target voice chain.

This executable deliberately uses the new composition root and playback port
without importing the legacy entrypoint. It plays one fixed synthetic reply,
does not open microphone input, and writes only redacted operational metrics.
It is output-path evidence, not B or C certification.
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
from typing import Any, Mapping

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.media_adapter import DeviceDescriptor
from backend.session_kernel import ProviderCapabilities
from backend.target_composition import TargetVoiceComposition, TargetVoiceCompositionConfig
from backend.target_playback import PlaybackConfig, SoundDevicePlaybackPort
from backend.tts_qwen_provider import QwenTTSConfig


_TRANSCRIPT = "元亨，能听到吗"
_REPLY = "进步始于思想，元亨开拓未来。"
_SENSITIVE_KEYS = frozenset({"audio", "content", "input", "raw_audio", "text", "transcript"})


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


def _safe_value(value: Any, key: str = "") -> Any:
    if key.lower() in _SENSITIVE_KEYS:
        return "[redacted]"
    if isinstance(value, Mapping):
        return {str(name): _safe_value(item, str(name)) for name, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe_value(item) for item in value]
    if isinstance(value, str):
        return value[:160]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return repr(value)[:160]


def _event_summary(event: Any) -> dict:
    payload = getattr(event, "payload", {}) or {}
    return {
        "kind": str(getattr(event, "kind", "EVENT")),
        "code": getattr(event, "code", None),
        "event_seq": int(getattr(event, "event_seq", 0) or 0),
        "generation": int(getattr(event, "generation", 0) or 0),
        "payload": _safe_value(dict(payload)) if isinstance(payload, Mapping) else {},
    }


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


async def _run(args: argparse.Namespace) -> dict:
    os.environ.update({"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"})
    import sounddevice as sounddevice

    sounddevice.check_output_settings(
        device=args.output_device,
        samplerate=24_000,
        channels=args.channels,
        dtype="float32",
    )
    playback_events: list[dict] = []
    playback = SoundDevicePlaybackPort(
        PlaybackConfig(
            device=args.output_device,
            channels=args.channels,
            initial_buffer_ms=args.initial_buffer_ms,
            stop_timeout_s=args.stop_timeout_s,
        ),
        on_event=lambda event: playback_events.append(_event_summary(event)),
    )
    qwen = QwenTTSConfig(
        model_dir=Path(args.model_dir),
        speaker=args.speaker,
        language=args.language,
        chunk_size=args.chunk_size,
        max_new_tokens=args.max_new_tokens,
        queue_maxsize=args.queue_maxsize,
        stop_timeout_s=args.stop_timeout_s,
        warmup_text=args.warmup_text,
    )
    composition = TargetVoiceComposition(
        TargetVoiceCompositionConfig(
            qwen=qwen,
            worker_id="target-playback-probe",
            startup_timeout_s=args.startup_timeout_s,
            stop_timeout_s=args.stop_timeout_s,
        ),
        reasoner=_ProbeReasoner(),
        playback=playback,
    )
    result: dict = {
        "probe_version": "target-playback-v1",
        "timestamp": time.time(),
        "python": sys.version,
        "platform": platform.platform(),
        "offline_mode": True,
        "device_access": True,
        "input_access": False,
        "entrypoint_imported": "backend.main" in sys.modules,
        "output": {
            "device": args.output_device,
            "sample_rate": 24_000,
            "channels": args.channels,
            "initial_buffer_ms": args.initial_buffer_ms,
        },
        "input_fingerprint": _fingerprint(_TRANSCRIPT),
        "reply_fingerprint": _fingerprint(_REPLY),
    }
    try:
        runtime = composition.create_runtime(asr=_NoopASR())
        device = DeviceDescriptor(
            device_id="speaker-output-probe",
            name="speaker-output-probe",
            input_channels=1,
            output_channels=args.channels,
            sample_rate=24_000,
        )
        composition.start(device, ProviderCapabilities())
        started_at = time.perf_counter()
        submission = await composition.chain.submit_transcript(_TRANSCRIPT, source="probe")
        if submission.task is None:
            raise RuntimeError("wake gate did not accept the fixed probe transcript")
        outcome = await asyncio.wait_for(submission.task, timeout=args.turn_timeout_s)
        elapsed_ms = int(round((time.perf_counter() - started_at) * 1000))
        events = composition.kernel.recent_events(160)
        event_kinds = [str(event.get("kind", "")) for event in events]
        playback_metrics = dict(playback.metrics())
        result.update(
            {
                "runtime_state_before_shutdown": runtime.state.value,
                "outcome": {
                    "status": outcome.status,
                    "committed": outcome.committed,
                    "error_code": outcome.error_code,
                    "elapsed_ms": elapsed_ms,
                },
                "event_counts": {
                    kind: event_kinds.count(kind) for kind in sorted(set(event_kinds))
                },
                "playback_events": playback_events[:64],
                "playback_metrics_before_shutdown": _safe_value(playback_metrics),
                "tts_metrics": _safe_value(
                    composition.chain.snapshot().get("ports", {}).get("tts_provider_metrics")
                ),
                "provider_health_before_shutdown": _safe_value(composition.tts_provider.health()),
                "acceptance": {
                    "turn_completed": outcome.status == "completed",
                    "audio_chunk_seen": "AUDIO_CHUNK" in event_kinds,
                    "audio_done_seen": "AUDIO_DONE" in event_kinds,
                    "port_drained": playback_metrics.get("queue_depth") == 0,
                    "port_error_free": not any(
                        item.get("code") for item in playback_events if item["kind"] == "PLAYBACK_ERROR"
                    ),
                    "entrypoint_untouched": "backend.main" not in sys.modules,
                },
            }
        )
    finally:
        try:
            await composition.shutdown("target_playback_probe_complete")
        except Exception as exc:
            result["shutdown_error"] = {
                "code": type(exc).__name__,
                "detail": str(exc)[:240],
            }
            raise
        finally:
            result["closed"] = composition.closed
            result["playback_metrics_after_shutdown"] = _safe_value(playback.metrics())
            result["provider_health_after_shutdown"] = _safe_value(composition.tts_provider.health())
    return result


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--output-device", type=int, required=True)
    parser.add_argument("--channels", type=int, default=2)
    parser.add_argument("--speaker", default="Vivian")
    parser.add_argument("--language", default="chinese")
    parser.add_argument("--chunk-size", type=int, default=8)
    parser.add_argument("--max-new-tokens", type=int, default=2048)
    parser.add_argument("--queue-maxsize", type=int, default=32)
    parser.add_argument("--initial-buffer-ms", type=int, default=300)
    parser.add_argument("--stop-timeout-s", type=float, default=5.0)
    parser.add_argument("--startup-timeout-s", type=float, default=90.0)
    parser.add_argument("--turn-timeout-s", type=float, default=45.0)
    parser.add_argument("--warmup-text", default="你好。")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    out_dir = Path(args.out_dir)
    try:
        result = asyncio.run(_run(args))
    except Exception as exc:
        result = {
            "probe_version": "target-playback-v1",
            "timestamp": time.time(),
            "offline_mode": True,
            "device_access": True,
            "input_access": False,
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
