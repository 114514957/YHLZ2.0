#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""用 v5 LoRA 权重批量合成留样。

用法:
  python -X utf8 tools/gsv5_batch_samples.py --weights <pth> --out 音频素材/09_留样...
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

TEXTS = [
    ("01_短句", "元亨，能听到吗？"),
    ("02_日常", "老爹，我是元亨呀。今天风挺大的，你出门记得穿外套。"),
    ("03_长句", "评审记录都在仓库里。那些是你控制不了的，过去你能控制的，是今晚写不写复盘文档。"),
    ("04_疑问", "开发群不会还要我搞宵禁吧？"),
    ("05_收尾", "行吧，那就先这样，有事儿你再喊我。"),
    ("06_吐槽", "我今天真的是服了，怎么会有人这么写代码？"),
    ("07_叮嘱", "这个功能先别上线，等我测完再说。"),
    ("08_认同", "你说得对，我刚才没想到这一层。"),
]


def stats(x, sr):
    spec = np.abs(np.fft.rfft(x * np.hanning(len(x)))) ** 2
    f = np.fft.rfftfreq(len(x), 1 / sr)
    hi = float(spec[f >= 8000].sum()) / float(spec.sum() + 1e-12)
    f0 = librosa.yin(x, fmin=70, fmax=700, sr=sr, frame_length=1024, hop_length=256)
    v = f0[np.isfinite(f0)]
    return {
        "dur": round(len(x) / sr, 2),
        "peak": round(float(np.max(np.abs(x))), 3),
        "rms_db": round(float(20 * np.log10(np.sqrt(np.mean(x ** 2)) + 1e-12)), 1),
        "hi8k_pct": round(hi * 100, 2),
        "f0_med": round(float(np.median(v)), 1) if len(v) else None,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--steps", type=int, default=32)
    ap.add_argument("--cfg", type=float, default=1.3)
    ap.add_argument("--ref", default=str(ROOT / "models" / "tts" / "refs" / "design_bright" / "ref01.wav"))
    ap.add_argument("--ref-text", default=(ROOT / "models" / "tts" / "refs" / "design_bright" / "ref01.txt")
                    .read_text(encoding="utf-8-sig").strip())
    a = ap.parse_args()

    out = Path(a.out)
    if not out.is_absolute():
        out = ROOT / out
    out.mkdir(parents=True, exist_ok=True)

    cfg = {
        "device": "cuda", "is_half": True, "version": "v5dev",
        "t2s_weights_path": str(PM / "s1v3.ckpt"),
        "vits_weights_path": str(Path(a.weights).resolve()),
        "cnhuhbert_base_path": str(PM / "chinese-hubert-base"),
        "bert_base_path": str(PM / "chinese-roberta-wwm-ext-large"),
    }
    t0 = time.time()
    tts = TTS(TTS_Config({"custom": cfg}))
    load_s = time.time() - t0
    print(json.dumps({"event": "loaded", "load_s": round(load_s, 1)}), flush=True)

    rows = []
    for tag, text in TEXTS:
        t1 = time.time()
        gen = tts.run({
            "text": text, "text_lang": "zh",
            "ref_audio_path": a.ref, "prompt_text": a.ref_text, "prompt_lang": "zh",
            "text_split_method": "cut5", "batch_size": 1, "media_type": "wav",
            "streaming_mode": False, "sample_steps": a.steps, "cfg_rate": a.cfg,
            "speed_factor": 1.0, "parallel_infer": True,
        })
        sr, audio = next(gen)
        audio = np.asarray(audio, dtype="float32").squeeze()
        if float(np.max(np.abs(audio))) > 1.5:
            audio = audio / 32768.0
        gen_s = time.time() - t1
        p = out / f"{tag}.wav"
        sf.write(str(p), audio, sr)
        row = {"tag": tag, "text": text, "file": p.name,
               "sr": int(sr), "gen_s": round(gen_s, 1),
               "rtf": round(gen_s / max(len(audio) / sr, 1e-6), 2),
               **stats(audio, sr)}
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)

    (out / "manifest.json").write_text(json.dumps({
        "weights": str(Path(a.weights).resolve()), "steps": a.steps, "cfg": a.cfg,
        "ref": a.ref, "rows": rows}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    lines = [f"v5 LoRA 留样（{Path(a.weights).name}）",
             f"采样：{a.steps} 步 / CFG {a.cfg} / v5dev / 48 kHz", ""]
    for r in rows:
        lines.append(f"{r['tag']:<8} {r['dur']:>5.2f}s peak={r['peak']:.2f} "
                     f"8k+={r['hi8k_pct']:.2f}% F0={r['f0_med']} RTF={r['rtf']}")
        lines.append(f"         {r['text']}")
    (out / "说明.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"event": "done", "n": len(rows), "out": str(out)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
