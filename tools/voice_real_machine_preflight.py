"""Non-streaming real-machine voice preflight for YHLZ.

This command does not start the daemon, open a microphone stream, load an ASR
model, or initialize TTS. It discovers modules/devices (not runtime imports),
checks report-directory writes, and does not certify headset readiness.

Usage:
    python tools/voice_real_machine_preflight.py
    python tools/voice_real_machine_preflight.py --json-out cache/voice_metrics/preflight.json
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import platform
import shutil
import sys
import time
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
DEFAULT_OUT = ROOT / "cache" / "voice_metrics" / "real_machine_preflight.json"

REQUIRED_MODULES = (
    "numpy",
    "sounddevice",
    "soundfile",
    "backend.voice_trace",
    "backend.media_adapter",
    "backend.streaming_asr_bridge",
    "backend.target_chain",
    "backend.target_runtime",
    "backend.target_playback",
)
OPTIONAL_MODULES = (
    "sherpa_onnx",
    "torch",
    "faster_qwen3_tts",
)


def _module_status(name: str) -> dict[str, Any]:
    try:
        found = importlib.util.find_spec(name) is not None
    except Exception as exc:  # pragma: no cover - defensive on broken installs
        return {"available": False, "error": type(exc).__name__}
    return {"available": bool(found)}


def _safe_env() -> dict[str, str]:
    """Expose only operational flags, never values that may contain secrets."""
    keys = (
        "YHLZ_ENV",
        "YHLZ_VOICE_DEVICE",
        "YHLZ_INPUT_DEVICE",
        "YHLZ_OUTPUT_DEVICE",
        "CUDA_VISIBLE_DEVICES",
        "CUDA_DEVICE_ORDER",
    )
    return {key: str(os.environ[key])[:120] for key in keys if key in os.environ}


def _sound_devices() -> dict[str, Any]:
    try:
        import sounddevice as sd

        devices = []
        for index, item in enumerate(sd.query_devices()):
            name = str(item.get("name", ""))[:160]
            devices.append(
                {
                    "index": index,
                    "name": name,
                    "max_input_channels": int(item.get("max_input_channels", 0)),
                    "max_output_channels": int(item.get("max_output_channels", 0)),
                    "default_samplerate": float(item.get("default_samplerate", 0.0)),
                }
            )
        default = sd.default.device
        candidates = [
            item for item in devices
            if any(token in item["name"].lower() for token in ("headphone", "headset", "earphone", "耳机"))
        ]
        return {
            "available": True,
            "default": list(default),
            "devices": devices,
            "headset_candidates": candidates,
        }
    except Exception as exc:
        return {"available": False, "error": type(exc).__name__, "detail": str(exc)[:160]}


def _writable_probe(path: Path) -> dict[str, Any]:
    """Actually verify a small write/delete in the metrics directory."""
    try:
        path.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=path) as probe:
            probe.write(b"ok\n")
            probe.flush()
        return {"writable": True}
    except OSError as exc:
        return {"writable": False, "error": type(exc).__name__}


def _path_status(path: Path) -> dict[str, Any]:
    try:
        stat = path.stat()
    except OSError:
        return {"exists": False}
    return {"exists": True, "bytes": int(stat.st_size), "mtime": float(stat.st_mtime)}


def collect() -> dict[str, Any]:
    report: dict[str, Any] = {
        "schema": "yhlz.voice_real_machine_preflight.v1",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "cwd": str(Path.cwd()),
        "root": str(ROOT),
        "python": {"executable": sys.executable, "version": platform.python_version()},
        "platform": {"system": platform.system(), "release": platform.release(), "machine": platform.machine()},
        "git": {"available": shutil.which("git") is not None},
        "environment": _safe_env(),
        "required_modules": {name: _module_status(name) for name in REQUIRED_MODULES},
        "optional_modules": {name: _module_status(name) for name in OPTIONAL_MODULES},
        "audio": _sound_devices(),
        "paths": {
            "voice_metrics": _path_status(ROOT / "cache" / "voice_metrics"),
            "voice_metrics_write_probe": _writable_probe(ROOT / "cache" / "voice_metrics"),
            "voice_clips": _path_status(ROOT / "cache" / "voice_clips"),
            "target_requirements": _path_status(ROOT / "requirements-target-runtime.txt"),
        },
        "checks": {},
    }
    required = report["required_modules"]
    audio = report["audio"]
    report["checks"] = {
        "required_modules_present": all(item.get("available") for item in required.values()),
        "audio_query_succeeded": bool(audio.get("available")),
        "input_device_present": any(item.get("max_input_channels", 0) > 0 for item in audio.get("devices", [])),
        "output_device_present": any(item.get("max_output_channels", 0) > 0 for item in audio.get("devices", [])),
        "metrics_dir_writable": bool(report["paths"]["voice_metrics_write_probe"].get("writable")),
    }
    # This is only a software/device-enumeration gate. It cannot prove that a
    # physical headset is plugged in or that audio is acoustically audible.
    report["software_preflight_passed"] = all(report["checks"].values())
    report["headset_manual_confirmation_required"] = True
    report["ready_for_supervised_headset_bench"] = False
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json-out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding='utf-8')
    report = collect()
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["software_preflight_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
