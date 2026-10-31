# -*- coding: utf-8 -*-
"""翻唱 v3 定版「柔化 DSP」（2026-10-11；从 cache/tmp/lab_v4_build.py 固化）。

在「清晰增强」后的 AI 干声上做柔化，与群听评/老爹验收过的效果一致：
  e（默认，V3-e）= 轻压缩(-18dB, 2.5:1) + 动态去齿(轻) + 轻饱和 + 等响对齐
  d（V3-d 柔和轻）= 轻压缩(-16dB, 2.0:1) + 软饱和 + 等响对齐

用法: python tools/cover_v3_dsp.py <in.wav> <out.wav> [--preset e|d]
"""
from __future__ import annotations

import argparse
import sys

import numpy as np
import soundfile as sf
from scipy.ndimage import uniform_filter1d
from scipy.signal import butter, sosfilt

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def comp(x: np.ndarray, thr_db: float = -16.0, ratio: float = 2.0,
         smooth: float = 0.02, sr: int = 44100) -> np.ndarray:
    """轻压缩（前馈、软起音；用于收毛刺不改变响度感）。"""
    env = uniform_filter1d(np.abs(x), int(0.005 * sr), axis=0)
    over = np.maximum(20 * np.log10(env + 1e-9) - thr_db, 0)
    g = 10 ** (-over * (1 - 1 / ratio) / 20)
    g = uniform_filter1d(g, int(smooth * sr), axis=0)
    return (x * np.clip(g, 0.2, 1.0)).astype("float32")


def deess_mild(x: np.ndarray, thr: float = 0.06, duck: float = 0.7,
               sr: int = 44100) -> np.ndarray:
    """动态去齿（轻）：只削 5k+ 的尖峰，不做静态高频衰减。"""
    sos = butter(4, 5000, btype="lowpass", fs=sr, output="sos")
    low = sosfilt(sos, x, axis=0).astype("float32")
    high = x - low
    env = uniform_filter1d(np.abs(high), int(0.004 * sr), axis=0)
    over = np.maximum(env - thr, 0)
    g = 1.0 / (1.0 + over * (1.0 / duck) * 6)
    g = uniform_filter1d(g, int(0.012 * sr), axis=0)
    return (low + high * g).astype("float32")


def sat(x: np.ndarray, drive: float = 1.2, mix: float = 0.6) -> np.ndarray:
    """轻饱和（tanh 波形整形，混合回干信号）。"""
    s = np.tanh(drive * x) / np.tanh(drive)
    return (mix * s + (1 - mix) * x).astype("float32")


def rms_match(y: np.ndarray, ref: np.ndarray, peak: float = 0.985) -> np.ndarray:
    """等响对齐（对齐输入 RMS；超高则压回峰值上限）。"""
    r0 = float(np.sqrt(np.mean(ref ** 2))) + 1e-9
    r1 = float(np.sqrt(np.mean(y ** 2))) + 1e-9
    y = y * (r0 / r1)
    pk = float(np.abs(y).max())
    if pk > peak:
        y = y * (peak / pk)
    return y.astype("float32")


def process(x: np.ndarray, preset: str = "e", sr: int = 44100) -> np.ndarray:
    if preset == "d":
        y = comp(x, thr_db=-16, ratio=2.0, smooth=0.02, sr=sr)
        y = sat(y, drive=1.3, mix=0.75)
    else:  # e（定版）
        y = comp(x, thr_db=-18, ratio=2.5, smooth=0.03, sr=sr)
        y = deess_mild(y, sr=sr)
        y = sat(y, drive=1.2, mix=0.6)
    return rms_match(y, x)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="翻唱 v3 定版柔化 DSP")
    ap.add_argument("src", help="输入干声 wav（清晰增强后的 AI 干声）")
    ap.add_argument("dst", help="输出 wav")
    ap.add_argument("--preset", default="e", choices=("e", "d"),
                    help="e=轻压缩+动态去齿+轻饱和（定版默认）；d=柔和轻")
    args = ap.parse_args(argv)
    x, sr = sf.read(args.src, dtype="float32", always_2d=True)
    y = process(x, args.preset, sr)
    sf.write(args.dst, y, sr, subtype="PCM_16")
    print(f"[dsp] preset={args.preset} sr={sr} frames={len(y)} -> {args.dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
