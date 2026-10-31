#!/usr/bin/env python3
"""清晰增强 v2 (2026-10-10, 老爹选定 V2b)：把原干声 >6kHz 的齿音/气息
叠回 SVC 干声，改善吐字通透度而不换音色。

Usage:
  wsl_clarity_enhance.py <svc_lead.wav> <orig_lead.wav> <out.wav>
                         [--gain 0.65] [--highcut 6000] [--peak 0.99]

- SVC lead 重采样到 44.1k 立体声；原干声高通后按 gain 叠加；峰值限幅。
"""
from __future__ import annotations

import argparse
import json

import librosa
import numpy as np
import soundfile as sf
from scipy.signal import butter, sosfilt

SR = 44100


def to44(x: np.ndarray, sr: int, ch: int = 2) -> np.ndarray:
    if sr != SR:
        x = librosa.resample(x.astype("float32"), orig_sr=sr, target_sr=SR,
                             axis=0)
    if x.ndim == 1:
        x = np.stack([x] * ch, axis=1)
    if x.shape[1] == 1 and ch == 2:
        x = np.repeat(x, 2, axis=1)
    return x[:, :ch].astype("float32")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("svc_lead")
    ap.add_argument("orig_lead")
    ap.add_argument("out")
    ap.add_argument("--gain", type=float, default=0.65)
    ap.add_argument("--highcut", type=float, default=6000.0)
    ap.add_argument("--peak", type=float, default=0.99)
    a = ap.parse_args()

    svc, sr = sf.read(a.svc_lead, dtype="float32", always_2d=True)
    svc = to44(svc, sr)
    lead, lsr = sf.read(a.orig_lead, dtype="float32", always_2d=True)
    lead = to44(lead, lsr)

    sos = butter(4, a.highcut, btype="highpass", fs=SR, output="sos")
    hb = sosfilt(sos, lead, axis=0).astype("float32")

    n = min(len(svc), len(hb))
    y = svc[:n] + a.gain * hb[:n]
    pk = float(np.abs(y).max())
    if pk > a.peak:
        y *= a.peak / pk
    sf.write(a.out, y, SR, subtype="PCM_16")
    print(json.dumps({"out": a.out, "gain": a.gain, "highcut": a.highcut,
                      "duration_s": round(n / SR, 2),
                      "peak_before": round(pk, 3)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
