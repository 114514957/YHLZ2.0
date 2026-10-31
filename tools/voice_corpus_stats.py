#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""语料体检：条数/时长/峰值/采样率/list 完整性；可选 CAM++ 抽检音色一致性。

用法:
  python tools/voice_corpus_stats.py --dir models/tts/voice_train/yuanheng_v2
  python tools/voice_corpus_stats.py --dir ... --ref models/tts/refs/yuanheng/ref01.wav --sv-check 12
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    ap.add_argument("--ref", default=str(ROOT / "models" / "tts" / "refs" / "yuanheng" / "ref01.wav"))
    ap.add_argument("--sv-check", type=int, default=0, help="随机抽 N 条算 CAM++ cos")
    ap.add_argument("--seed", type=int, default=20261018)
    a = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

    d = Path(a.dir)
    wavs = sorted((d / "wavs").glob("*.wav"))
    durs, peaks, srs, shorts, longs, clips = [], [], set(), 0, 0, 0
    total_bytes = 0
    for p in wavs:
        info = sf.info(str(p))
        dur = info.frames / float(info.samplerate)
        durs.append(dur)
        srs.add(info.samplerate)
        total_bytes += p.stat().st_size
        if dur < 0.8:
            shorts += 1
        if dur > 15:
            longs += 1
        x, _ = sf.read(str(p), dtype="float32")
        pk = float(np.max(np.abs(x))) if x.size else 0.0
        peaks.append(pk)
        if pk > 0.99:
            clips += 1

    lines = [ln for ln in (d / "data.list").read_text(encoding="utf-8").splitlines() if ln.strip()]
    bad = 0
    for ln in lines:
        parts = ln.split("|")
        if len(parts) != 4 or not parts[3].strip():
            bad += 1

    out = {
        "dir": str(d),
        "n_wav": len(wavs),
        "n_list": len(lines),
        "list_malformed": bad,
        "total_min": round(sum(durs) / 60.0, 1),
        "dur_mean_s": round(float(np.mean(durs)), 2) if durs else 0,
        "dur_median_s": round(float(np.median(durs)), 2) if durs else 0,
        "dur_min_s": round(float(np.min(durs)), 2) if durs else 0,
        "dur_max_s": round(float(np.max(durs)), 2) if durs else 0,
        "lt_0_8s": shorts,
        "gt_15s": longs,
        "peak_max": round(max(peaks), 3) if peaks else 0,
        "peak_gt_0_99": clips,
        "sample_rates": sorted(srs),
        "total_mb": round(total_bytes / 1e6, 1),
    }

    if a.sv_check and wavs:
        import librosa
        from funasr import AutoModel

        model = AutoModel(
            model=str(ROOT / "models" / "voice" / "sv" / "campplus"), device="cpu",
            disable_update=True, disable_pbar=True, disable_log=True)

        def emb(path):
            x, sr = sf.read(str(path), dtype="float32", always_2d=True)
            x = x.mean(axis=1)
            if sr != 16000:
                x = librosa.resample(x, orig_sr=sr, target_sr=16000)
            r = model.generate(input=x)
            e = np.asarray(r[0]["spk_embedding"], dtype="float32").reshape(-1)
            return e / (np.linalg.norm(e) + 1e-9)

        ref_e = emb(a.ref)
        rng = random.Random(a.seed)
        pick = rng.sample(wavs, min(a.sv_check, len(wavs)))
        cos = [float(emb(p) @ ref_e) for p in pick]
        out["sv_check"] = {
            "n": len(cos),
            "ref": str(a.ref),
            "cos_mean": round(float(np.mean(cos)), 3),
            "cos_min": round(float(np.min(cos)), 3),
            "cos_max": round(float(np.max(cos)), 3),
            "samples": [p.name for p in pick],
        }

    (d / "corpus_stats.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
