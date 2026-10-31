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
from backend.target_voice_profile import build_target_qwen_config


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


def _finalize_acceptance(result: dict) -> None:
    """Separate software cancellation evidence from playback continuity.

    Reassessment is also safe for older reports whose port_error_free check
    ignored underruns. Missing evidence never counts as a pass.
    """
    acceptance = result.setdefault("acceptance", {})
    events = result.get("playback_events", [])
    metrics = result.get("playback_metrics_before_shutdown", {})
    required = ["turn_completed", "audio_chunk_seen", "audio_done_seen",
                "port_drained", "entrypoint_untouched"]
    if result.get("scenario") == "interrupt-followup":
        required += ["interrupted_turn_cancelled", "stop_confirmed",
                     "old_output_stable_after_stop", "cancel_queue_drained",
                     "new_turn_id", "followup_output_seen"]
    hard_error = any(e.get("kind") == "PLAYBACK_ERROR" for e in events)
    continuous = metrics.get("underrun_count") == 0 and not any(
        e.get("kind") == "PLAYBACK_UNDERRUN" for e in events)
    acceptance["playback_underrun_free"] = continuous
    acceptance["port_error_free"] = bool(metrics) and continuous and not (
        hard_error or metrics.get("last_error_code") or any(e.get("code") for e in events))
    control = all(acceptance.get(k) is True for k in required) and not hard_error
    control = control and result.get("closed") is True and not result.get("error_code")
    control = control and acceptance.get("scenario_completed", True) is True
    control = control and acceptance.get("shutdown_ok", True) is True
    result["acceptance_groups"] = {
        "control_path_passed": control,
        "playback_continuity_passed": continuous,
        "all_automated_checks_passed": control and all(v is True for v in acceptance.values()),
    }


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


async def _wait_for_output(playback: Any, task: Any, timeout_s: float, baseline_frames: int = 0) -> float:
    """Observe nonempty device callbacks, not a claim about acoustic latency."""
    started = time.perf_counter()
    while playback.metrics().get("played_frames", 0) <= baseline_frames:
        if task.done():
            raise RuntimeError("turn ended before any callback output")
        if time.perf_counter() - started >= timeout_s:
            raise TimeoutError("no callback output within turn timeout")
        await asyncio.sleep(0.01)
    return round((time.perf_counter() - started) * 1000, 1)


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
    probe_clock = time.perf_counter()
    playback = SoundDevicePlaybackPort(
        PlaybackConfig(
            device=args.output_device,
            channels=args.channels,
            initial_buffer_ms=args.initial_buffer_ms,
            stop_timeout_s=args.stop_timeout_s,
        ),
        on_event=lambda event: playback_events.append({
            **_event_summary(event), "probe_ms": round((time.perf_counter() - probe_clock) * 1000, 1)}),
    )
    qwen = build_target_qwen_config(
        voice_profile=args.voice_profile,
        model_dir=args.model_dir,
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
            segmented_tts_enabled=getattr(args, "segmented_tts", False),
        ),
        reasoner=_ProbeReasoner(),
        playback=playback,
    )
    result: dict = {
        "probe_version": "target-playback-v3",
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
        "qwen_config": qwen.to_dict(),
        "ref_audio_sha256": hashlib.sha256(qwen.ref_audio.read_bytes()).hexdigest() if qwen.ref_audio else None,
        "scenario": args.scenario,
        "physical_tail_confirmation": "requires_user_listening",

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
        first_output_ms = None
        if args.scenario == "interrupt-followup":
            first_output_ms = await _wait_for_output(playback, submission.task, args.turn_timeout_s)
            await asyncio.sleep(max(0, args.interrupt_after_ms) / 1000)
            if submission.task.done():
                raise RuntimeError("probe turn ended before interrupt; no live interruption was tested")
            stop_started = time.perf_counter()
            old_turn = submission.lease.turn_id
            aborted = await composition.chain.interrupt("real_probe_barge_in", timeout_s=args.stop_timeout_s)
            abort_ok = (aborted.requested and aborted.turn_id == old_turn
                        and not aborted.timed_out_tasks and not aborted.failed_tasks)
            playback_stopped = await playback.wait_stopped(0.1)
            tts_stopped = await composition.tts_provider.wait_idle_stopped(0.1)
            stopped = bool(abort_ok and playback_stopped and tts_stopped)

            cancelled_outcome = await asyncio.wait_for(submission.task, args.stop_timeout_s + 1)
            stop_ms = (time.perf_counter() - stop_started) * 1000
            stopped_frames = playback.metrics().get("played_frames", 0)
            await asyncio.sleep(0.12)
            stable = playback.metrics().get("played_frames", 0) == stopped_frames
            result["interruption"] = {
                "old_turn_id": old_turn, "stop_confirmed": stopped,
                "playback_stop_confirmed": playback_stopped,
                "tts_stop_confirmed": tts_stopped,
                "abort_requested": aborted.requested,
                "completed_tasks": list(aborted.completed_tasks),
                "timed_out_tasks": list(aborted.timed_out_tasks),
                "failed_tasks": list(aborted.failed_tasks),
                "cancelled_status": cancelled_outcome.status,
                "submit_to_callback_output_ms": first_output_ms,
                "stop_confirmed_ms": round(stop_ms, 1),
                "played_frames_stable_after_stop": stable,
                "queue_depth_after_stop": playback.metrics().get("queue_depth"),
                "tts_metrics": _safe_value(composition.chain.snapshot().get("ports", {}).get("tts_provider_metrics")),
            }
            if not stopped:
                raise RuntimeError("stop was not confirmed; follow-up must stay blocked")
            submission = await composition.chain.submit_transcript(_TRANSCRIPT, source="probe-followup")
            if submission.task is None:
                raise RuntimeError("wake gate rejected follow-up")
            result["interruption"]["followup_turn_id"] = submission.lease.turn_id
            result["interruption"]["followup_submit_to_callback_output_ms"] = await _wait_for_output(
                playback, submission.task, args.turn_timeout_s, baseline_frames=stopped_frames)
        else:
            first_output_ms = await _wait_for_output(playback, submission.task, args.turn_timeout_s)
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
                    "submit_to_callback_output_ms": first_output_ms,
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
        if args.scenario == "interrupt-followup":
            inter = result["interruption"]
            result["acceptance"].update({
                "interrupted_turn_cancelled": inter["cancelled_status"] == "interrupted",
                "stop_confirmed": inter["stop_confirmed"],
                "old_output_stable_after_stop": inter["played_frames_stable_after_stop"],
                "cancel_queue_drained": inter["queue_depth_after_stop"] == 0,
                "new_turn_id": inter["old_turn_id"] != inter["followup_turn_id"],
                "followup_output_seen": inter["followup_submit_to_callback_output_ms"] is not None,
            })
    except Exception as exc:
        result["error_code"] = type(exc).__name__
        result["detail"] = str(exc)[:400]
        result.setdefault("acceptance", {})["scenario_completed"] = False
        result["provider_health_before_shutdown"] = _safe_value(composition.tts_provider.health())
        result["tts_metrics"] = _safe_value(composition.chain.snapshot().get("ports", {}).get("tts_provider_metrics"))
        result["playback_events"] = list(playback_events)
        result["playback_metrics_before_shutdown"] = _safe_value(playback.metrics())

    finally:
        try:
            await composition.shutdown("target_playback_probe_complete")
        except Exception as exc:
            result["shutdown_error"] = {
                "code": type(exc).__name__,
                "detail": str(exc)[:240],
            }
            result.setdefault("acceptance", {})["shutdown_ok"] = False
        finally:
            result["closed"] = composition.closed
            result["playback_metrics_after_shutdown"] = _safe_value(playback.metrics())
            result["provider_health_after_shutdown"] = _safe_value(composition.tts_provider.health())
    _finalize_acceptance(result)
    return result


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-dir", help="Explicit legacy CustomVoice override unless --voice-profile is supplied")
    parser.add_argument("--voice-profile", choices=("xiaoyi", "customvoice"), default=None,
                        help="Default: local Xiaoyi clone; model-only override preserves legacy CustomVoice")
    parser.add_argument("--scenario", choices=("normal", "interrupt-followup"), default="normal")
    parser.add_argument("--interrupt-after-ms", type=int, default=250)
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
    parser.add_argument("--segmented-tts", action="store_true",
                        help="Opt-in serial segment commits on the existing Xiaoyi Qwen worker")
    parser.add_argument("--warmup-text", default="你好。")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    out_dir = Path(args.out_dir)
    try:
        result = asyncio.run(_run(args))
    except Exception as exc:
        result = {
            "probe_version": "target-playback-v3",
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
    return 0 if result.get("acceptance_groups", {}).get("all_automated_checks_passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
