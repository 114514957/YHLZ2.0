"""Speaker -> mic -> VAD -> ASR echo-chain probe (no human speech needed).

Synthesizes/plays the fixed TTS sentence on the speaker while the mic is
already capturing; the capture runs through VAD and a streaming ASR
provider to verify the assistant can "hear" its own output well enough to
trigger windows and recognize content.  Audio is never persisted; the
summary keeps counts/hashes only (final text may print to stdout for
diagnosis with --print-text).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Sequence

import numpy as np
import sounddevice as sd

from backend.target_vad import TargetVADProvider
from backend.target_funasr_asr import FunasrOnlineASRProvider, FunasrASRConfig, CHUNK_STRIDE
from backend.target_chain import CancellationSignal
from backend.streaming_asr_bridge import ASRStreamUpdateKind

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SENTENCE = "进步始于思想，元亨开拓未来"
_MODEL_DIR = _PROJECT_ROOT / "models" / "voice" / "asr" / "paraformer-zh-streaming"


def _default_output_dir() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return _PROJECT_ROOT / "artifacts" / "echo_chain_probe" / ("echo_" + stamp)


def run_probe(
    output_dir: Path,
    *,
    sentence: str = _SENTENCE,
    device_id: int = 1,
    capture_rate: int = 16_000,
    duration_s: float = 14.0,
    asr_backend: str = "funasr",
    print_text: bool = False,
    play_gain: float = 1.0,
    cap_gain: float = 1.0,
    no_tts: bool = False,
    tts_device: int = 3,
) -> dict:
    output_dir.mkdir(parents=True, exist_ok=False)
    summary: dict[str, Any] = {
        "probe": "target_echo_chain_v1",
        "status": "failed",
        "audio_persisted": False,
        "text_persisted": False,
    }
    vad = TargetVADProvider()
    if asr_backend == "funasr":
        asr = FunasrOnlineASRProvider(FunasrASRConfig(model_dir=_MODEL_DIR))
    else:
        from backend.target_sherpa_asr import SherpaOnlineASRProvider

        asr = SherpaOnlineASRProvider()
    vad.start()
    asr.start()

    stream = sd.InputStream(
        device=device_id, samplerate=capture_rate, channels=1,
        dtype="float32", blocksize=1600,
    )
    stream.start()
    time.sleep(1.0)
    _primed = stream.read(1600)
    print(
        f"[echo-chain] primed peak={float(np.abs(_primed[0]).max()):.5f}",
        flush=True,
    )

    tts = None
    if not no_tts:
        tts = subprocess.Popen(
            [
                sys.executable, "-m", "backend.tts_speaker_probe",
                "--speakers", "Vivian", "--text", sentence,
                "--play-gain", str(max(1.0, float(play_gain))),
                "--device", str(int(tts_device)),
            ],
            cwd=str(_PROJECT_ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    sig = CancellationSignal()
    asr.open_stream("echo", 1, capture_rate, 1, sig)
    transcript_parts: list[str] = []
    vad_frames = 0
    speech_frames = 0
    prob_peak = 0.0
    rms_peak = 0.0
    updates: list[str] = []
    t0 = time.time()
    accumulated = ""
    _log_period = 0

    while time.time() - t0 < float(duration_s):
        try:
            data, _ = stream.read(1600)
        except Exception as exc:
            print(f"[echo-chain] read error: {exc!r}", flush=True)
            break
        period = int((time.time() - t0) / 2)
        if period > _log_period:
            _log_period = period
            print(
                f"[echo-chain] t={period}s peak={float(np.abs(data).max()):.5f}",
                flush=True,
            )
        mono = data[:, 0].astype("float32") if data.ndim > 1 else np.asarray(data, dtype="float32")
        if float(cap_gain) != 1.0:
            mono = np.clip(mono * float(cap_gain), -1.0, 1.0).astype("float32")
        rms = float(np.sqrt(np.mean(np.square(mono))))
        rms_peak = max(rms_peak, rms)
        speech = bool(vad.detect_speech(mono, capture_rate))
        prob = float(vad.health().get("last_probability", 0.0) or 0.0)
        vad_frames += 1
        prob_peak = max(prob_peak, prob)
        if speech:
            speech_frames += 1
        for upd in asr.push_audio("echo", mono, capture_rate, sig):
            accumulated = accumulated + upd.text if upd.text else accumulated
            if upd.kind in (ASRStreamUpdateKind.PARTIAL, ASRStreamUpdateKind.FINAL):
                updates.append(upd.kind.value)
                if upd.kind is ASRStreamUpdateKind.FINAL:
                    transcript_parts.append(upd.text)

    final = asr.finish_stream("echo", sig)
    if final.kind is ASRStreamUpdateKind.FINAL and final.text:
        transcript_parts.append(final.text if not transcript_parts else "")
    stream.stop()
    stream.close()
    if tts is not None:
        tts.wait(timeout=120)

    transcript = "".join(transcript_parts) or accumulated
    norm = lambda s: "".join(ch for ch in s if ch not in "，。！？、 　, .!?")
    target_norm = norm(sentence)
    got_norm = norm(transcript)
    exact_ok = got_norm == target_norm
    if not exact_ok:
        from difflib import SequenceMatcher

        ratio = SequenceMatcher(None, target_norm, got_norm).ratio()
    else:
        ratio = 1.0
    summary.update(
        {
            "status": "passed" if speech_frames > 0 and ratio >= 0.9 else "failed",
            "vad_frames": int(vad_frames),
            "vad_speech_frames": int(speech_frames),
            "vad_prob_peak": round(float(prob_peak), 4),
            "rms_peak": round(float(rms_peak), 6),
            "asr_updates": updates,
            "asr_text_len": len(transcript),
            "asr_text_sha256": hashlib.sha256(transcript.encode("utf-8")).hexdigest()[:16],
            "match_exact": bool(exact_ok),
            "match_ratio": round(float(ratio), 4),
            "asr_backend": asr_backend,
            "tts_exit": int(tts.returncode) if tts is not None else -1,
        }
    )
    if print_text:
        print("[echo-chain] transcript:", transcript, flush=True)
    vad.stop("done")
    asr.stop("done")
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return summary


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sentence", default=_SENTENCE)
    parser.add_argument("--device-id", type=int, default=1)
    parser.add_argument("--duration-s", type=float, default=14.0)
    parser.add_argument("--asr-backend", choices=["funasr", "sherpa"], default="funasr")
    parser.add_argument("--print-text", action="store_true")
    parser.add_argument("--play-gain", type=float, default=1.0)
    parser.add_argument("--cap-gain", type=float, default=1.0)
    parser.add_argument("--no-tts", action="store_true", help="capture-only baseline (no playback)")
    parser.add_argument("--tts-device", type=int, default=3,
                        help="output device for TTS playback (3=Realtek speakers)")
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args(argv)
    summary = run_probe(
        args.output_dir or _default_output_dir(),
        sentence=args.sentence,
        device_id=args.device_id,
        duration_s=args.duration_s,
        asr_backend=args.asr_backend,
        print_text=args.print_text,
        play_gain=args.play_gain,
        cap_gain=args.cap_gain,
        no_tts=args.no_tts,
        tts_device=args.tts_device,
    )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0 if summary.get("status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
