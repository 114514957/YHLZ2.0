"""Local sherpa-onnx TTS benchmark (ledger 0435, KB kb_0d8d1d6c6751).

Piper/VITS ONNX on CPU: measures load + synthesis time and writes a wav.

Usage: python tools/tts_local_bench.py [--model-dir DIR] [--runs 3] [--text ...]
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model-dir", default=str(_ROOT / "models" / "tts" / "piper-zh-huayan"))
    ap.add_argument("--text", default="今晚吃啥都行，你定就好。")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--out", default=str(_ROOT / "cache" / "voice_clips" / "local_tts.wav"))
    a = ap.parse_args()
    d = Path(a.model_dir)
    onnx = next(d.glob("*.onnx"), None)
    tokens = d / "tokens.txt"
    espeak = d / "espeak-ng-data"
    if onnx is None or not tokens.exists():
        print("model missing:", d)
        return 2

    import numpy as np
    import sherpa_onnx
    import soundfile as sf

    t0 = time.perf_counter()
    cfg = sherpa_onnx.OfflineTtsConfig(
        model=sherpa_onnx.OfflineTtsModelConfig(
            vits=sherpa_onnx.OfflineTtsVitsModelConfig(
                model=str(onnx), tokens=str(tokens),
                data_dir=str(espeak) if espeak.exists() else ""),
            num_threads=2,
        ),
        max_num_sentences=1,
    )
    tts = sherpa_onnx.OfflineTts(cfg)
    load_ms = (time.perf_counter() - t0) * 1000

    warm = tts.generate(a.text, sid=0, speed=1.0)
    times = []
    audio = warm
    for i in range(a.runs):
        t0 = time.perf_counter()
        audio = tts.generate(a.text, sid=0, speed=1.0)
        times.append((time.perf_counter() - t0) * 1000)
    sr = int(audio.sample_rate)
    samples = np.asarray(audio.samples, dtype="float32")
    sf.write(a.out, samples, sr, subtype="PCM_16")
    dur = len(samples) / sr
    print(f"model           : {onnx.name}")
    print(f"load (once)     : {load_ms:.0f} ms")
    print(f"synth avg       : {sum(times) / len(times):.0f} ms  (runs={times})")
    print(f"audio duration  : {dur:.2f} s  sr={sr}")
    print(f"RTF             : {(sum(times) / len(times) / 1000) / max(dur, 1e-6):.2f}")
    print(f"wav             : {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
