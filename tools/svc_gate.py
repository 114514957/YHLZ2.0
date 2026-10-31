#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""按源人声的有声区给 SVC 输出做门控，堵掉"在器乐段硬唱"。

背景（2026-10-30）：htdemucs 分出的人声轨在无唱段仍有能量，Seed-VC 的
f0 条件会把这些噪声硬合成成有声人声——整首歌因此出现大量失稳与破音。
统计上：BANG 源人声 20–35s 仅 7% 帧有音高，转换后 50%。

做法：对源人声做 pyin，取有声帧掩码，先闭运算补 60ms 以内的小洞、
再去掉短于 80ms 的孤立段，边界各加 30ms 淡入淡出，然后乘到 SVC 输出上。

    python tools/svc_gate.py <源人声.wav> <svc输出.wav> <结果.wav>
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import librosa
import numpy as np
import soundfile as sf

SR_ANALYSIS = 22050
HOP = 256


def voiced_mask(src: Path, sr_out: int, total: int) -> np.ndarray:
    y, sr = librosa.load(str(src), sr=SR_ANALYSIS, mono=True)
    f0, voiced, prob = librosa.pyin(y, fmin=70, fmax=1000, sr=SR_ANALYSIS,
                                    frame_length=1024, hop_length=HOP, fill_na=np.nan)
    mask = (voiced & np.isfinite(f0) & (prob > 0.5)).astype(np.uint8)
    frame_s = HOP / SR_ANALYSIS

    # 闭运算：补小于 60ms 的洞
    gap = max(1, int(round(0.060 / frame_s)))
    filled = mask.copy()
    i = 0
    while i < len(filled):
        if filled[i] == 0:
            j = i
            while j < len(filled) and filled[j] == 0:
                j += 1
            if i > 0 and j < len(filled) and (j - i) <= gap:
                filled[i:j] = 1
            i = j
        else:
            i += 1

    # 去掉短于 80ms 的孤立有声段
    min_len = max(1, int(round(0.080 / frame_s)))
    i = 0
    while i < len(filled):
        if filled[i] == 1:
            j = i
            while j < len(filled) and filled[j] == 1:
                j += 1
            if (j - i) < min_len:
                filled[i:j] = 0
            i = j
        else:
            i += 1

    # 上采样到输出采样率，边界做 30ms 淡入淡出
    idx = np.repeat(filled.astype(np.float32), int(round(HOP * sr_out / SR_ANALYSIS)))
    if idx.size < total:
        idx = np.pad(idx, (0, total - idx.size), mode="edge")
    idx = idx[:total]
    fade = max(1, int(0.030 * sr_out))
    kernel = np.ones(fade, dtype=np.float32) / fade
    sm = np.convolve(idx, kernel, mode="same")
    return np.clip(sm, 0.0, 1.0)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("source")
    ap.add_argument("svc")
    ap.add_argument("out")
    ap.add_argument("--floor", type=float, default=0.0,
                    help="掩码为 0 处的残余增益（默认 0 = 完全静音）")
    args = ap.parse_args()

    src, svc = Path(args.source), Path(args.svc)
    y, sr = sf.read(str(svc), dtype="float32", always_2d=True)
    mask = voiced_mask(src, sr, len(y))
    if args.floor > 0:
        mask = args.floor + (1.0 - args.floor) * mask
    out = y * mask[:, None]

    before = float(np.mean(np.abs(y).max(1) > 1e-4))
    after = float(np.mean(np.abs(out).max(1) > 1e-4))
    print(f"[gate] 有声占比 {before:.1%} -> {after:.1%}", file=sys.stderr)

    dst = Path(args.out)
    dst.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(dst), out, sr, subtype="PCM_16")
    print(f"[ok] {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
