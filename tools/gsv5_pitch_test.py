#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""默认测试文本 + 音域（高/低音）测试。

用法:
  python -X utf8 tools/gsv5_pitch_test.py --weights <pth> --out 音频素材/10_默认文本与音域测试

音域做法:
  把参考音按 -6/-4/-2/0/+2/+4/+6 半音变调，再让 v5 合成同一句；
  测输出的 F0 中位、峰值、8k+ 能量，找「最低/最高可用音高」。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GSV = ROOT / "GPT-SoVITS"
PM = GSV / "GPT_SoVITS" / "pretrained_models"

os.environ["PYTHONIOENCODING"] = "utf-8"
os.environ["NO_PROXY"] = "localhost,127.0.0.1,::1,.maas.aliyuncs.com"
os.environ.pop("no_proxy", None)
os.environ["PATH"] = (str(ROOT / "cache" / "tools" / "ffmpeg-9.0.1-essentials_build" / "bin")
                      + os.pathsep + os.environ.get("PATH", ""))
os.environ.pop("HF_HUB_OFFLINE", None)
os.environ.pop("TRANSFORMERS_OFFLINE", None)
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
sys.path.insert(0, str(GSV / "GPT_SoVITS"))
sys.path.insert(0, str(GSV))
os.chdir(str(GSV))

import librosa  # noqa: E402
import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402
from TTS_infer_pack.TTS import TTS, TTS_Config  # noqa: E402

BASE_TEXT = "元亨，能听到吗？"
DEFAULT_TEXTS = [
    ("默认_进步始于思想", "进步始于思想，元亨开拓未来"),
    ("默认_能听到吗", "元亨，能听到吗？"),
]
SHIFTS = [-6, -4, -2, 0, 2, 4, 6]


def stats(x, sr):
    spec = np.abs(np.fft.rfft(x * np.hanning(len(x)))) ** 2
    f = np.fft.rfftfreq(len(x), 1 / sr)
    hi = float(spec[f >= 8000].sum()) / float(spec.sum() + 1e-12)
    cen = float((f * spec).sum() / (spec.sum() + 1e-12))
    f0 = librosa.yin(x, fmin=60, fmax=900, sr=sr, frame_length=1024, hop_length=256)
    v = f0[np.isfinite(f0)]
    return {
        "dur": round(len(x) / sr, 2),
        "peak": round(float(np.max(np.abs(x))), 3),
        "hi8k_pct": round(hi * 100, 2),
        "centroid": round(cen),
        "f0_med": round(float(np.median(v)), 1) if len(v) else None,
        "f0_min": round(float(np.percentile(v, 5)), 1) if len(v) else None,
        "f0_max": round(float(np.percentile(v, 95)), 1) if len(v) else None,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--steps", type=int, default=32)
    ap.add_argument("--cfg", type=float, default=1.3)
    ap.add_argument("--shifts", default="-6,-4,-2,0,2,4,6",
                    help="逗号分隔的半音数")
    ap.add_argument("--ref", default=str(ROOT / "models" / "tts" / "refs" / "design_bright" / "ref01.wav"))
    ap.add_argument("--ref-text", default=(ROOT / "models" / "tts" / "refs" / "design_bright" / "ref01.txt")
                    .read_text(encoding="utf-8-sig").strip())
    a = ap.parse_args()

    out = Path(a.out)
    if not out.is_absolute():
        out = ROOT / out
    (out / "refs").mkdir(parents=True, exist_ok=True)

    cfg = {
        "device": "cuda", "is_half": True, "version": "v5dev",
        "t2s_weights_path": str(PM / "s1v3.ckpt"),
        "vits_weights_path": str(Path(a.weights).resolve()),
        "cnhuhbert_base_path": str(PM / "chinese-hubert-base"),
        "bert_base_path": str(PM / "chinese-roberta-wwm-ext-large"),
    }
    t0 = time.time()
    tts = TTS(TTS_Config({"custom": cfg}))
    print(json.dumps({"event": "loaded", "load_s": round(time.time() - t0, 1)}), flush=True)

    def synth(text: str, ref: str) -> tuple[np.ndarray, int, float]:
        t1 = time.time()
        gen = tts.run({
            "text": text, "text_lang": "zh",
            "ref_audio_path": ref, "prompt_text": a.ref_text, "prompt_lang": "zh",
            "text_split_method": "cut5", "batch_size": 1, "media_type": "wav",
            "streaming_mode": False, "sample_steps": a.steps, "cfg_rate": a.cfg,
            "speed_factor": 1.0, "parallel_infer": True,
        })
        sr, audio = next(gen)
        audio = np.asarray(audio, dtype="float32").squeeze()
        if float(np.max(np.abs(audio))) > 1.5:
            audio = audio / 32768.0
        return audio, int(sr), time.time() - t1

    rows = []
    for tag, text in DEFAULT_TEXTS:
        audio, sr, gen_s = synth(text, a.ref)
        p = out / f"{tag}.wav"
        sf.write(str(p), audio, sr)
        rows.append({"kind": "default", "tag": tag, "text": text,
                     "file": p.name, "sr": sr, "gen_s": round(gen_s, 1),
                     **stats(audio, sr)})
        print(json.dumps(rows[-1], ensure_ascii=False), flush=True)

    ref_y, ref_sr = sf.read(a.ref, dtype="float32")
    shifts = [int(x) for x in a.shifts.split(",") if x.strip()]
    for shift in shifts:
        if shift == 0:
            ref_path = a.ref
        else:
            y = librosa.effects.pitch_shift(ref_y, sr=ref_sr, n_steps=shift)
            ref_path = str(out / "refs" / f"ref_{shift:+d}.wav")
            sf.write(ref_path, y, ref_sr)
        audio, sr, gen_s = synth(BASE_TEXT, ref_path)
        tag = f"音域_{shift:+d}半音"
        p = out / f"{tag}.wav"
        sf.write(str(p), audio, sr)
        row = {"kind": "pitch", "shift": shift, "tag": tag, "text": BASE_TEXT,
               "ref": ref_path, "file": p.name, "sr": sr,
               "gen_s": round(gen_s, 1), **stats(audio, sr)}
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)

    (out / "manifest.json").write_text(json.dumps({
        "weights": str(Path(a.weights).resolve()), "steps": a.steps, "cfg": a.cfg,
        "base_text": BASE_TEXT, "shifts": shifts, "rows": rows},
        ensure_ascii=False, indent=2), encoding="utf-8")

    pitch_rows = [r for r in rows if r["kind"] == "pitch"]
    lines = ["v5 LoRA 默认文本 + 音域测试",
             f"权重：{Path(a.weights).name}；{a.steps} 步 / CFG {a.cfg} / 48 kHz", ""]
    for r in rows:
        lines.append(f"{r['tag']:<14} F0中位={r['f0_med']}Hz (p5={r['f0_min']} p95={r['f0_max']}) "
                     f"peak={r['peak']:.2f} 8k+={r['hi8k_pct']:.2f}%")
    lines += ["", f"音域（按参考变调）：最低 {min(r['f0_med'] for r in pitch_rows)} Hz，"
              f"最高 {max(r['f0_med'] for r in pitch_rows)} Hz"]
    (out / "说明.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"event": "done", "n": len(rows), "out": str(out)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
